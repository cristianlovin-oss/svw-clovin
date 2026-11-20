"""Tools and callbacks that read and write shared session state.

Every agent in the system works on the same session, so anything written to
``state`` here is visible to every other agent (and to instruction templates
such as ``{user_request}``).
"""

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.tool_context import ToolContext
from google.genai import types

# Session state keys shared by all agents.
USER_REQUEST = "user_request"
REQUEST_HISTORY = "request_history"
RESEARCH_FINDINGS = "research_findings"
DRAFT_RESPONSE = "draft_response"
VALIDATION_REPORT = "validation_report"
VALIDATION_STATUS = "validation_status"
FINAL_RESPONSE = "final_response"
AWAITING_FEEDBACK = "awaiting_feedback"
USER_FEEDBACK = "user_feedback"
FEEDBACK_ROUNDS = "feedback_rounds"

_DEFAULTS = {
    USER_REQUEST: "",
    REQUEST_HISTORY: [],
    RESEARCH_FINDINGS: "",
    DRAFT_RESPONSE: "",
    VALIDATION_REPORT: "",
    VALIDATION_STATUS: "pending",
    FINAL_RESPONSE: "",
    AWAITING_FEEDBACK: False,
    USER_FEEDBACK: "",
    FEEDBACK_ROUNDS: 0,
}


# --------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------
def init_session_state(callback_context: CallbackContext) -> None:
    """before_agent_callback on the root agent: makes sure every key exists so
    instruction templates never hit a missing key."""
    for key, value in _DEFAULTS.items():
        if key not in callback_context.state:
            callback_context.state[key] = (
                list(value) if isinstance(value, list) else value
            )


def mark_awaiting_feedback(callback_context: CallbackContext) -> None:
    """after_agent_callback on the workflow: once the answer has been shown,
    flag that the next user message is probably feedback on it."""
    callback_context.state[AWAITING_FEEDBACK] = True


def handle_search_error(
    callback_context: CallbackContext, llm_request: LlmRequest, error: Exception
) -> LlmResponse | None:
    """on_model_error_callback for the web_searcher agent.

    Google Search grounding has a separate quota from normal model calls. When
    every model in the fallback chain fails (quota exhausted, overloaded,
    server error), return a notice the researcher can act on instead of
    crashing the workflow. Other errors (bad API key, etc.) still surface.
    """
    code = getattr(error, "code", None)
    if code not in (429, 500, 502, 503, 504):
        return None
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    text=(
                        f"WEB SEARCH UNAVAILABLE (error {code}). "
                        "Answer from model knowledge and mark facts as unverified."
                    )
                )
            ],
        )
    )


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
def save_user_request(request: str, tool_context: ToolContext) -> dict:
    """Store a new user request in session state before starting the research workflow.

    Args:
        request: The user's request, restated clearly and completely.
    """
    state = tool_context.state
    history = list(state.get(REQUEST_HISTORY, []))
    history.append(request)

    state[USER_REQUEST] = request
    state[REQUEST_HISTORY] = history
    # A new request starts a fresh pipeline.
    state[RESEARCH_FINDINGS] = ""
    state[DRAFT_RESPONSE] = ""
    state[VALIDATION_REPORT] = ""
    state[VALIDATION_STATUS] = "pending"
    state[FINAL_RESPONSE] = ""
    state[AWAITING_FEEDBACK] = False
    state[USER_FEEDBACK] = ""
    state[FEEDBACK_ROUNDS] = 0
    return {"status": "saved", "request": request, "requests_this_session": len(history)}


def approve_response(tool_context: ToolContext) -> dict:
    """Call this ONLY when the draft fully passes validation. Ends the validate/refine loop."""
    tool_context.state[VALIDATION_STATUS] = "approved"
    tool_context.actions.escalate = True  # exits the enclosing LoopAgent
    return {"status": "approved"}


def record_feedback(is_adequate: bool, comments: str, tool_context: ToolContext) -> dict:
    """Record the user's verdict on the last answer.

    Args:
        is_adequate: True if the user is satisfied with the answer, False otherwise.
        comments: What the user wants changed or added (empty string if satisfied).
    """
    state = tool_context.state
    state[AWAITING_FEEDBACK] = False
    if is_adequate:
        state[USER_FEEDBACK] = ""
        return {"status": "accepted"}

    state[USER_FEEDBACK] = comments
    state[FEEDBACK_ROUNDS] = state.get(FEEDBACK_ROUNDS, 0) + 1
    state[VALIDATION_STATUS] = "pending"
    return {"status": "revision_requested", "round": state[FEEDBACK_ROUNDS]}
