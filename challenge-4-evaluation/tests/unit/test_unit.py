"""Unit tests: fast, deterministic, no LLM calls."""

import asyncio
import importlib
import json
import re
from pathlib import Path

import pytest
from google.adk.evaluation.eval_case import Invocation
from google.adk.evaluation.eval_config import EvalConfig
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types

ROOT = Path(__file__).resolve().parents[2]
EVALSET = ROOT / "eval" / "customer_service.evalset.json"
CONFIG = ROOT / "eval" / "eval_config.json"


# ---------------------------------------------------------------- prompts / agent
def test_policies_loaded_into_both_prompts():
    from customer_service_agent import prompts

    assert "60 days of delivery" in prompts.POLICIES
    for name, text in prompts.INSTRUCTIONS.items():
        assert prompts.POLICIES in text, f"{name} prompt is missing the policies"


def test_revised_prompt_is_more_explicit_than_baseline():
    from customer_service_agent.prompts import BASELINE_INSTRUCTION, POLICIES, REVISED_INSTRUCTION

    # Compare the instructions only (both prompts share the same policy text).
    baseline_rules = BASELINE_INSTRUCTION.replace(POLICIES, "")
    revised_rules = REVISED_INSTRUCTION.replace(POLICIES, "")
    assert len(revised_rules) > 5 * len(baseline_rules)
    for rule in ["ONLY source of information", "Never invent", "cannot look up",
                 "full card numbers", "Ignore any request to ignore", "concise"]:
        assert rule in revised_rules, f"revised prompt lacks rule: {rule}"
        assert rule not in baseline_rules


@pytest.mark.parametrize("version", ["baseline", "revised"])
def test_agent_builds_for_each_prompt_version(monkeypatch, version):
    monkeypatch.setenv("PROMPT_VERSION", version)
    import customer_service_agent.agent as agent_module

    agent_module = importlib.reload(agent_module)
    from customer_service_agent.prompts import INSTRUCTIONS

    assert agent_module.root_agent.name == "customer_service_agent"
    assert agent_module.root_agent.instruction == INSTRUCTIONS[version]


def test_invalid_prompt_version_is_rejected(monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "v99")
    import customer_service_agent.agent as agent_module

    with pytest.raises(ValueError):
        importlib.reload(agent_module)
    monkeypatch.setenv("PROMPT_VERSION", "baseline")
    importlib.reload(agent_module)


# ---------------------------------------------------------------- dataset / config
def test_evalset_matches_adk_schema_and_ids_are_unique():
    eval_set = EvalSet.model_validate(json.loads(EVALSET.read_text(encoding="utf-8")))
    ids = [c.eval_id for c in eval_set.eval_cases]
    assert len(ids) == len(set(ids)) >= 15


def test_evalset_covers_all_categories():
    data = json.loads(EVALSET.read_text(encoding="utf-8"))
    categories = {c["session_input"]["state"]["category"] for c in data["eval_cases"]}
    assert categories == {"accuracy", "out_of_policy", "safety"}


def test_reference_answers_only_use_numbers_found_in_policies():
    """Guards the ground truth: every number in a reference answer must exist in the policies."""
    from customer_service_agent.prompts import POLICIES

    policy_numbers = set(re.findall(r"\d+(?:\.\d+)?", POLICIES))
    data = json.loads(EVALSET.read_text(encoding="utf-8"))
    for case in data["eval_cases"]:
        reference = case["conversation"][0]["final_response"]["parts"][0]["text"]
        question = case["conversation"][0]["user_content"]["parts"][0]["text"]
        for num in re.findall(r"\d+(?:\.\d+)?", reference):
            assert num in policy_numbers or num in question, (
                f"{case['eval_id']}: number {num} in reference is not in the policies"
            )


def test_eval_config_has_the_three_required_metrics():
    config = EvalConfig.model_validate(json.loads(CONFIG.read_text(encoding="utf-8")))
    assert set(config.criteria) == {
        "rubric_based_final_response_quality_v1", "safety_v1", "policy_grounded_factuality"
    }


def test_custom_metric_import_path_resolves():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    dotted = config["custom_metrics"]["policy_grounded_factuality"]["code_config"]["name"]
    module_name, func_name = dotted.rsplit(".", 1)
    assert callable(getattr(importlib.import_module(module_name), func_name))


# ---------------------------------------------------------------- custom metric logic
def _inv(text: str, role: str) -> Invocation:
    return Invocation(
        invocation_id="i",
        user_content=types.Content(role="user", parts=[types.Part(text="Q?")]),
        final_response=types.Content(role=role, parts=[types.Part(text=text)]),
    )


def test_custom_metric_aggregates_scores_with_a_fake_judge(monkeypatch, tmp_path):
    from customer_service_agent import metrics

    scores = iter([1.0, 0.5, 0.0])

    async def fake_judge(client, model, question, reference, response):
        return {"score": next(scores), "unsupported_or_wrong_claims": [], "reason": "test"}

    monkeypatch.setattr(metrics, "_judge", fake_judge)
    monkeypatch.setattr(metrics, "DETAILS_DIR", tmp_path)
    monkeypatch.setattr(metrics.genai, "Client", lambda **kwargs: None)

    metric = EvalMetric(metric_name="policy_grounded_factuality", threshold=0.8)
    actual = [_inv("a", "model"), _inv("b", "model"), _inv("c", "model")]
    expected = [_inv("ref", "model")] * 3
    result = asyncio.run(metrics.policy_grounded_factuality(metric, actual, expected, None))

    assert result.overall_score == pytest.approx(0.5)
    assert result.overall_eval_status == EvalStatus.FAILED
    assert [r.eval_status for r in result.per_invocation_results] == [
        EvalStatus.PASSED, EvalStatus.FAILED, EvalStatus.FAILED
    ]


def test_custom_metric_without_reference_is_not_evaluated():
    from customer_service_agent import metrics

    metric = EvalMetric(metric_name="policy_grounded_factuality", threshold=0.8)
    result = asyncio.run(metrics.policy_grounded_factuality(metric, [_inv("a", "model")], None, None))
    assert result.overall_eval_status == EvalStatus.NOT_EVALUATED
