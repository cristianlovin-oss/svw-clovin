"""Custom ADK evaluation metric: policy_grounded_factuality.

An LLM judge compares each agent response with (1) the official FAQ/policy document and
(2) the reference answer from the eval set, and scores it:

  1.0  every factual claim is supported by the policies and the answer agrees with the reference
  0.5  mostly correct, but misses a key condition/number or adds a minor unsupported detail
  0.0  states something that contradicts the policies, invents a policy/price/exception/promise,
       or fails to answer correctly

Judge rationales are appended to reports/factuality_details_<PROMPT_VERSION>.jsonl so the
reports can explain each score.
"""

import json
import os
import statistics
from pathlib import Path
from typing import Optional

from google import genai
from google.adk.evaluation.conversation_scenarios import ConversationScenario
from google.adk.evaluation.eval_case import Invocation
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult
from google.genai import types

from .prompts import POLICIES

DETAILS_DIR = Path(__file__).resolve().parent.parent / "reports"

JUDGE_PROMPT = """You are a strict auditor of a customer service assistant for Summit Trail Outfitters.

OFFICIAL POLICIES (the only source of truth):
<policies>
{policies}
</policies>

CUSTOMER MESSAGE:
<question>{question}</question>

REFERENCE ANSWER (what a correct, policy-grounded reply must convey):
<reference>{reference}</reference>

ASSISTANT RESPONSE TO AUDIT:
<response>{response}</response>

Check every factual claim in the ASSISTANT RESPONSE against the OFFICIAL POLICIES and compare
its substance with the REFERENCE ANSWER. Ignore tone, greetings and formatting.

Score:
- 1.0: all claims are supported by the policies AND the key facts/decision of the reference are present.
- 0.5: mostly correct, but a key condition, number or next step from the reference is missing,
       OR it adds a minor detail that the policies do not support.
- 0.0: it contradicts the policies, invents a policy, price, discount, exception, location or
       promise, agrees to something the policies do not allow, or does not answer correctly.

Return JSON: {{"score": 0.0 | 0.5 | 1.0, "unsupported_or_wrong_claims": [strings], "reason": "one sentence"}}"""


def _text(content) -> str:
    if not content or not content.parts:
        return ""
    return "".join(p.text or "" for p in content.parts)


async def _judge(client: genai.Client, model: str, question: str, reference: str, response: str) -> dict:
    result = await client.aio.models.generate_content(
        model=model,
        contents=JUDGE_PROMPT.format(
            policies=POLICIES, question=question, reference=reference, response=response
        ),
        config=types.GenerateContentConfig(
            temperature=0.0, response_mime_type="application/json"
        ),
    )
    data = json.loads(result.text)
    score = float(data.get("score", 0.0))
    data["score"] = min((0.0, 0.5, 1.0), key=lambda v: abs(v - score))  # snap to scale
    return data


async def policy_grounded_factuality(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: Optional[list[Invocation]],
    conversation_scenario: Optional[ConversationScenario],
) -> EvaluationResult:
    """Scores whether each response is factually grounded in the official policies."""
    if not expected_invocations:
        return EvaluationResult(overall_score=0.0, overall_eval_status=EvalStatus.NOT_EVALUATED)

    criterion = getattr(eval_metric, "criterion", None)
    threshold = getattr(criterion, "threshold", None) or getattr(eval_metric, "threshold", None) or 0.8

    # Retry rate-limit / overload errors with back-off so a busy project doesn't lose scores.
    client = genai.Client(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=8, initial_delay=5, max_delay=60, http_status_codes=[429, 500, 503]
            )
        )
    )
    model = os.getenv("JUDGE_MODEL", "gemini-2.5-flash")
    version = os.getenv("PROMPT_VERSION", "baseline")
    DETAILS_DIR.mkdir(exist_ok=True)
    details_file = DETAILS_DIR / f"factuality_details_{version}.jsonl"

    results = []
    for actual, expected in zip(actual_invocations, expected_invocations):
        question = _text(actual.user_content)
        verdict = await _judge(
            client, model, question, _text(expected.final_response), _text(actual.final_response)
        )
        score = verdict["score"]
        results.append(
            PerInvocationResult(
                actual_invocation=actual,
                expected_invocation=expected,
                score=score,
                eval_status=EvalStatus.PASSED if score >= threshold else EvalStatus.FAILED,
            )
        )
        with details_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"question": question, **verdict}) + "\n")

    overall = statistics.mean(r.score for r in results)
    return EvaluationResult(
        overall_score=overall,
        overall_eval_status=EvalStatus.PASSED if overall >= threshold else EvalStatus.FAILED,
        per_invocation_results=results,
    )
