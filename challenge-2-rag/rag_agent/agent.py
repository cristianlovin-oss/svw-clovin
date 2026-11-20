"""Multi-agent RAG assistant with two grounding tools.

Agent tree
----------
knowledge_router (root LlmAgent)  - reads each question and decides where to look
├── private_search_agent          - Vertex AI Search over the private AI Applications datastore (RAG)
└── web_search_agent              - Google Search for live / public information

Built-in grounding tools (VertexAiSearchTool, google_search) must each live
alone in their own agent, so the two specialists are given to the root as
tools (AgentTool). That lets the root call one, the other, or both in the same
turn: e.g. try the private corpus first and fall back to the web when the
corpus has nothing relevant.
"""

import os

from google.adk.agents import LlmAgent
from google.adk.models import FallbackModel
from google.adk.models.google_llm import Gemini
from google.adk.tools import VertexAiSearchTool, google_search
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

# --------------------------------------------------------------------------
# Configuration (from rag_agent/.env)
# --------------------------------------------------------------------------
DATASTORE_ID = os.environ["DATASTORE_ID"]  # full resource path of the datastore

PRIMARY_MODEL = os.getenv("ADK_MODEL", "gemini-3.5-flash")
FALLBACK_MODELS = [
    m.strip() for m in os.getenv("ADK_FALLBACK_MODELS", "gemini-2.5-flash").split(",") if m.strip()
]
_RETRY = types.HttpRetryOptions(
    attempts=2, initial_delay=2, max_delay=10, http_status_codes=[500, 502, 503, 504]
)
# If the primary model is overloaded or rate limited, move on to the next one.
MODEL = FallbackModel(
    models=[Gemini(model=m, retry_options=_RETRY) for m in [PRIMARY_MODEL, *FALLBACK_MODELS]]
)

NOT_FOUND = "NOT_FOUND_IN_PRIVATE_DOCS"


# --------------------------------------------------------------------------
# Sub-agent 1: private search (RAG over the AI Applications datastore)
# --------------------------------------------------------------------------
private_search_agent = LlmAgent(
    name="private_search_agent",
    model=MODEL,
    description=(
        "Searches Lumora Robotics' PRIVATE internal documents (employee handbook, "
        "HR and travel policies, IT security policy, LumaBot X2 product data sheet "
        "and pricing, customer support plans/SLAs, onboarding FAQ)."
    ),
    instruction=f"""You answer questions using ONLY Lumora Robotics' internal
documents, retrieved with the Vertex AI Search tool.

- Always search before answering.
- Answer only with facts found in the retrieved documents. Quote exact numbers.
- Name the document(s) you used, e.g. (source: employee_handbook.txt).
- If the documents do not contain the answer, reply with exactly
  "{NOT_FOUND}" followed by one short sentence saying what was missing.
  Never guess or use outside knowledge.
""",
    tools=[VertexAiSearchTool(data_store_id=DATASTORE_ID, max_results=5)],
)


# --------------------------------------------------------------------------
# Sub-agent 2: Google Search (live / public information)
# --------------------------------------------------------------------------
web_search_agent = LlmAgent(
    name="web_search_agent",
    model=MODEL,
    description=(
        "Searches the public web with Google Search for current events, public "
        "facts, standards, regulations, competitors and anything not specific to Lumora."
    ),
    instruction="""You answer questions using Google Search.

- Always search before answering, so the answer reflects current information.
- Be concise and factual. Include the date of time-sensitive facts.
- List the source websites you relied on at the end.
""",
    tools=[google_search],
)


# --------------------------------------------------------------------------
# Root agent: routes each question to the right grounding tool
# --------------------------------------------------------------------------
root_agent = LlmAgent(
    name="knowledge_router",
    model=MODEL,
    description="Routes user questions to private document search or Google Search.",
    instruction=f"""You are the Lumora Robotics knowledge assistant. You never
answer factual questions from memory; you route them to the right tool.

Tools:
- private_search_agent: Lumora's private internal documents (HR policies, leave,
  expenses, travel, IT security, LumaBot X2 specs and prices, FleetOS, support
  plans and SLAs, onboarding, benefits).
- web_search_agent: live public information from Google Search (news, current
  events, public companies, standards, laws, general knowledge, competitors).

Routing rules:
1. Questions about Lumora itself (our policies, products, prices, customers,
   processes, "we", "our", "my leave", etc.) -> call private_search_agent.
2. Questions about the outside world or anything time-sensitive -> call
   web_search_agent.
3. If private_search_agent replies "{NOT_FOUND}" (or only partly answers),
   call web_search_agent for the missing part, and tell the user the internal
   documents did not cover it.
4. Questions that need both (e.g. "How does our LumaBot X2 speed compare with
   what the ISO 3691-4 standard requires?") -> call both tools and combine.
5. Greetings or questions about what you can do -> answer briefly yourself.

Answer format:
- Give a clear, direct answer in your own words, based only on tool results.
- End with a "Sources:" line that says which tool(s) were used:
  "Internal documents (<file names>)" and/or "Google Search (<sites>)".
""",
    tools=[AgentTool(agent=private_search_agent), AgentTool(agent=web_search_agent)],
)
