"""Multi-agent research assistant built with Google ADK.

Agent tree
----------
coordinator (root, LlmAgent)                 routes requests, stores them in state
├── research_workflow (SequentialAgent)       research -> validate -> refine
│   ├── researcher (LlmAgent)                 -> state["research_findings"]
│   │     └── tool: AgentTool(web_searcher)   Google Search
│   ├── drafter (LlmAgent)                    -> state["draft_response"]
│   ├── validate_refine_loop (LoopAgent)      max 3 iterations
│   │   ├── validator (LlmAgent)              -> state["validation_report"], may exit loop
│   │   └── refiner (LlmAgent)                -> state["draft_response"] (rewritten)
│   └── presenter (LlmAgent)                  -> state["final_response"], asks the user
└── feedback_agent (LlmAgent)                 human-in-the-loop: records verdict,
                                              hands back to the workflow if needed
"""

import os

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.models import FallbackModel
from google.adk.models.google_llm import Gemini
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from .tools import (
    approve_response,
    handle_search_error,
    init_session_state,
    mark_awaiting_feedback,
    record_feedback,
    save_user_request,
)

# --------------------------------------------------------------------------
# Model configuration
# --------------------------------------------------------------------------
# The primary model is tried first. If it is overloaded (503), rate limited
# (429) or erroring (5xx), FallbackModel moves on to the next model in the
# list. Each model also retries briefly on its own before giving up.
PRIMARY_MODEL = os.getenv("ADK_MODEL", "gemini-3.5-flash")
FALLBACK_MODELS = [
    name.strip()
    for name in os.getenv(
        "ADK_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash-lite"
    ).split(",")
    if name.strip()
]
_RETRY = types.HttpRetryOptions(
    attempts=2,
    initial_delay=2,
    max_delay=10,
    http_status_codes=[500, 502, 503, 504],
)

MODEL = FallbackModel(
    models=[Gemini(model=name, retry_options=_RETRY) for name in [PRIMARY_MODEL, *FALLBACK_MODELS]]
)
MAX_REFINE_ITERATIONS = int(os.getenv("MAX_REFINE_ITERATIONS", "3"))


# --------------------------------------------------------------------------
# 1. Research
# --------------------------------------------------------------------------
# Built-in tools such as google_search must live in their own agent, which is
# then exposed to the researcher as a tool.
web_searcher = LlmAgent(
    name="web_searcher",
    model=MODEL,
    description="Searches the web with Google Search and returns relevant facts with sources.",
    instruction=(
        "Use Google Search to answer the query you are given. Return the key "
        "facts as concise bullet points, each followed by its source URL."
    ),
    tools=[google_search],
    # Google Search has its own quota. If it is exhausted or down, return a
    # short notice instead of crashing the whole workflow.
    on_model_error_callback=handle_search_error,
)

researcher = LlmAgent(
    name="researcher",
    model=MODEL,
    description="Gathers facts and sources for the user's request.",
    instruction="""You are a research specialist.

User request: {user_request}
Feedback from the user on a previous answer (may be empty): {user_feedback}

Research the request with the web_searcher tool. Run 2-4 focused searches that
cover the different parts of the request. If there is user feedback, focus
your searches on what the user said was missing or wrong.

If web_searcher replies "WEB SEARCH UNAVAILABLE", stop searching and use your
own knowledge instead, marking each such fact "(unverified - model knowledge)".

Output ONLY structured research notes:
## Key facts
- fact (source URL, or "unverified - model knowledge")
## Open questions / uncertainties
- ...
""",
    tools=[AgentTool(agent=web_searcher)],
    output_key="research_findings",
)

drafter = LlmAgent(
    name="drafter",
    model=MODEL,
    description="Writes a first-draft answer from the research notes.",
    instruction="""Write a first draft that answers the user's request.

User request: {user_request}
User feedback to address (may be empty): {user_feedback}
Research notes:
{research_findings}

Use only facts from the research notes. Be clear and well structured, cite
sources inline as [source](url). If the notes say facts are unverified model
knowledge, add one short note at the end saying live web sources were not
available. Output only the draft.
""",
    output_key="draft_response",
)


# --------------------------------------------------------------------------
# 2. Validate + refine (loop)
# --------------------------------------------------------------------------
validator = LlmAgent(
    name="validator",
    model=MODEL,
    description="Checks the draft for accuracy, completeness and relevance.",
    instruction="""You are a strict reviewer.

User request: {user_request}
User feedback to address (may be empty): {user_feedback}
Research notes:
{research_findings}
Current draft:
{draft_response}

Check the draft against these criteria:
1. Accuracy: every claim is supported by the research notes.
2. Completeness: every part of the request (and the user feedback) is answered.
3. Relevance and clarity: no filler, well organised, sources cited (facts
   marked as unverified model knowledge do not need a URL).

If ALL criteria pass, call the approve_response tool, then reply exactly "APPROVED".
Otherwise do NOT call the tool; reply with a numbered list of specific,
actionable problems to fix.
""",
    tools=[approve_response],
    output_key="validation_report",
)

refiner = LlmAgent(
    name="refiner",
    model=MODEL,
    description="Rewrites the draft to fix every issue the validator raised.",
    instruction="""Improve the draft.

User request: {user_request}
User feedback to address (may be empty): {user_feedback}
Research notes:
{research_findings}
Current draft:
{draft_response}
Validator issues:
{validation_report}

Fix every issue listed by the validator and make sure any user feedback is
addressed, without introducing unsupported claims.
Output only the full revised draft.
""",
    output_key="draft_response",
)

validate_refine_loop = LoopAgent(
    name="validate_refine_loop",
    description="Repeats validation and refinement until the draft is approved.",
    sub_agents=[validator, refiner],
    max_iterations=MAX_REFINE_ITERATIONS,
)


# --------------------------------------------------------------------------
# 3. Present + ask the user (human input)
# --------------------------------------------------------------------------
presenter = LlmAgent(
    name="presenter",
    model=MODEL,
    description="Delivers the validated answer and asks the user whether it is adequate.",
    instruction="""Deliver the final answer to the user.

Validated draft:
{draft_response}
Validation status: {validation_status}

Present the draft as the final answer (light formatting fixes only). If the
validation status is not "approved", add one short note that some points could
not be fully verified.

End with this question on its own line:
"Is this response adequate? Reply 'yes' or tell me what to change."
""",
    output_key="final_response",
)

research_workflow = SequentialAgent(
    name="research_workflow",
    description=(
        "Full research pipeline: researches the request, drafts an answer, "
        "validates and refines it, then presents it to the user."
    ),
    sub_agents=[researcher, drafter, validate_refine_loop, presenter],
    after_agent_callback=mark_awaiting_feedback,
)


# --------------------------------------------------------------------------
# 4. Human feedback
# --------------------------------------------------------------------------
feedback_agent = LlmAgent(
    name="feedback_agent",
    model=MODEL,
    description="Handles the user's reply to 'Is this response adequate?'.",
    instruction="""The user is replying to this answer:
{final_response}

Decide whether the user is satisfied.
- Satisfied (e.g. "yes", "great", "thanks"): call record_feedback with
  is_adequate=true and comments="", then thank the user briefly and say they
  can ask something new.
- Not satisfied: call record_feedback with is_adequate=false and comments set
  to a clear summary of what they want changed, then call transfer_to_agent
  with agent_name="research_workflow" so the answer is reworked.
- If the message is a brand new, unrelated request, call transfer_to_agent
  with agent_name="coordinator".
""",
    tools=[record_feedback],
)


# --------------------------------------------------------------------------
# Root agent
# --------------------------------------------------------------------------
root_agent = LlmAgent(
    name="coordinator",
    model=MODEL,
    description="Routes user messages to the right specialist agent.",
    instruction="""You are the coordinator of a research assistant team. You
never answer research questions yourself; you route them.

Session state:
- Awaiting feedback on the last answer: {awaiting_feedback}
- Current request: {user_request}
- Requests so far this session: {request_history}

Routing rules:
1. If awaiting feedback is True and the message reacts to the last answer
   (approval, complaint, correction, "add more about X"), transfer to
   feedback_agent.
2. If the message is a new question or task, call save_user_request with a
   clear, self-contained restatement of it (resolve references such as "it"
   using earlier requests), then transfer to research_workflow.
3. For greetings or questions about what you can do, reply briefly yourself
   and invite the user to ask a research question.
""",
    tools=[save_user_request],
    sub_agents=[research_workflow, feedback_agent],
    before_agent_callback=init_session_state,
)
