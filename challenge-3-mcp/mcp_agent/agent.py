"""Multi-agent system that uses two MCP servers.

Agent tree
----------
fishing_trip_router (root LlmAgent)          routes each question to the right sub-agent
├── weather_agent  ── McpToolset (stdio) ──> mcp_servers/nws_weather_server.py
│                                            National Weather Service: forecast, hourly,
│                                            current conditions, alerts
└── trout_agent    ── McpToolset (stdio) ──> mcp_servers/trout_conditions_server.py
                                             Custom Python tools: Georgetown Reservoir info,
                                             seasonal conditions, sun/moon, 1-10 rating, tactics

The sub-agents are given to the root as AgentTools, so for a question like
"Is tomorrow good for fishing?" the root can first get the forecast from the
weather agent and then pass those numbers to the trout agent's rating tool.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models import FallbackModel
from google.adk.models.google_llm import Gemini
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

SERVERS_DIR = Path(__file__).resolve().parent.parent / "mcp_servers"
GEORGETOWN_LAT, GEORGETOWN_LON = 39.7269, -105.6919

# --------------------------------------------------------------------------
# Model: primary + fallback (skips a model that is overloaded or rate limited)
# --------------------------------------------------------------------------
PRIMARY_MODEL = os.getenv("ADK_MODEL", "gemini-3.5-flash")
FALLBACK_MODELS = [
    m.strip() for m in os.getenv("ADK_FALLBACK_MODELS", "gemini-2.5-flash").split(",") if m.strip()
]
_RETRY = types.HttpRetryOptions(
    attempts=2, initial_delay=2, max_delay=10, http_status_codes=[500, 502, 503, 504]
)
MODEL = FallbackModel(
    models=[Gemini(model=m, retry_options=_RETRY) for m in [PRIMARY_MODEL, *FALLBACK_MODELS]]
)


def _stdio_mcp(script: str) -> McpToolset:
    """Launch one of our MCP servers as a subprocess and connect to it over stdio."""
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,  # the same Python/venv that runs the agent
                args=[str(SERVERS_DIR / script)],
            ),
            timeout=30,
        )
    )


# --------------------------------------------------------------------------
# Sub-agent 1: weather (NWS MCP server)
# --------------------------------------------------------------------------
weather_agent = LlmAgent(
    name="weather_agent",
    model=MODEL,
    description=(
        "Gets US weather from the National Weather Service: multi-day and hourly "
        "forecasts, current observed conditions and active weather alerts."
    ),
    instruction=f"""You are a weather specialist. Use the National Weather Service
tools to answer; never guess the weather.

- Georgetown Reservoir / Georgetown Lake, Colorado is at latitude {GEORGETOWN_LAT},
  longitude {GEORGETOWN_LON}. Use these coordinates when no other place is named.
- For other US places, use their approximate latitude/longitude.
- For "today/tonight/tomorrow/this weekend" use get_forecast; for the next few
  hours use get_hourly_forecast; for "right now" use get_current_conditions.
- Always check get_active_alerts when someone plans to go outdoors.
- Report: temperatures (F), wind speed range and direction, sky, precipitation
  chance, and any alerts. Mention that data comes from the National Weather Service.
""",
    tools=[_stdio_mcp("nws_weather_server.py")],
)


# --------------------------------------------------------------------------
# Sub-agent 2: trout conditions (custom MCP server)
# --------------------------------------------------------------------------
trout_agent = LlmAgent(
    name="trout_agent",
    model=MODEL,
    description=(
        "Trout fishing expert for Georgetown Reservoir (Georgetown Lake), Colorado: "
        "lake info, seasonal water temperature and ice status, sun and moon times, "
        "a 1-10 fishing-conditions rating, and recommended baits, lures and flies."
    ),
    instruction="""You are a trout fishing guide for Georgetown Reservoir in Colorado.
Use the georgetown-trout tools; do not invent facts.

- Lake details, species, regulations -> get_reservoir_info
- Water temperature, ice, where fish are -> get_seasonal_conditions
- Best times of day, sunrise/sunset, moon -> get_sun_and_moon
- "Is it a good day to fish?" -> rate_fishing_conditions, using the weather
  values provided in the request (high temp, wind mph, sky, precipitation chance,
  pressure trend). If no weather values were provided, say that a forecast is
  needed instead of guessing them.
- What to use -> recommend_tactics

Always pass dates as YYYY-MM-DD. Clearly label water temperature, ice and
ratings as estimates. Repeat any ice-safety warnings returned by the tools.
Only recommend baits, lures, flies and times that the tools returned; do not
add brand names, line weights or patterns of your own.
""",
    tools=[_stdio_mcp("trout_conditions_server.py")],
)


# --------------------------------------------------------------------------
# Root agent: routes questions to the sub-agents
# --------------------------------------------------------------------------
def root_instruction(_context: ReadonlyContext) -> str:
    """Builds the root instruction each turn so it always knows today's date."""
    today = datetime.now(ZoneInfo("America/Denver"))
    return _ROOT_INSTRUCTION.replace("{TODAY}", today.strftime("%A %Y-%m-%d"))


_ROOT_INSTRUCTION = """You help people plan trout fishing at Georgetown Reservoir
(Georgetown Lake) in Colorado. Today is {TODAY} (Colorado time).
Route every factual question to a sub-agent:

- weather_agent: weather forecasts, current conditions and alerts (any US place).
- trout_agent: the reservoir, fishing conditions, water temperature, ice,
  best times, ratings, and tactics/baits/lures/flies.

Routing rules:
1. Pure weather questions -> weather_agent only.
2. Pure fishing questions that do not depend on the weather (lake info, what
   lures to use, sunrise, ice safety) -> trout_agent only.
3. "Is today/tomorrow/Saturday a good day to fish?" or "should I go?" ->
   FIRST ask weather_agent for that day's forecast at Georgetown Reservoir,
   THEN ask trout_agent to rate the conditions, passing the forecast numbers
   explicitly (date as YYYY-MM-DD, high temperature F, wind mph, sky,
   precipitation chance, and pressure trend if known), and to recommend tactics.
4. Greetings or "what can you do?" -> answer briefly yourself.

When the user says "tomorrow" or a weekday, convert it to a YYYY-MM-DD date
(based on today's date above) before asking the sub-agents.

Final answer: a short, friendly summary that combines the sub-agents' results.
Keep any safety warnings (ice, wind, alerts). End with "Sources:" naming
"National Weather Service" and/or "Georgetown trout MCP server" as used.
"""

root_agent = LlmAgent(
    name="fishing_trip_router",
    model=MODEL,
    description="Plans trout fishing trips to Georgetown Reservoir, CO by routing to weather and trout experts.",
    instruction=root_instruction,
    tools=[AgentTool(agent=weather_agent), AgentTool(agent=trout_agent)],
)
