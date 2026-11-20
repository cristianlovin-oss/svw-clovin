# Challenge 3 – Custom MCP Servers with an ADK Multi-Agent System

A trout-fishing trip planner for **Georgetown Reservoir (Georgetown Lake), Colorado**, built with
the [Agent Development Kit (ADK)](https://adk.dev/). Python functions are exposed as tools through
**MCP (Model Context Protocol) servers**. Two sub-agents each use one MCP server, and a root agent
routes user questions to them.

## Architecture

```
fishing_trip_router (root LlmAgent)
├── AgentTool → weather_agent ── McpToolset (stdio) ──> mcp_servers/nws_weather_server.py
│                                                       National Weather Service API
└── AgentTool → trout_agent   ── McpToolset (stdio) ──> mcp_servers/trout_conditions_server.py
                                                        Custom Python trout-conditions tools
```

ADK's `McpToolset` starts each MCP server as a subprocess, discovers its tools over the MCP protocol
(`list_tools`) and turns them into tools the agent can call.

### MCP server 1: NWS weather (`nws_weather_server.py`)

| Tool | What it does |
|---|---|
| `get_forecast(latitude, longitude, periods)` | Multi-day forecast in 12-hour day and night periods |
| `get_hourly_forecast(latitude, longitude, hours)` | Hour-by-hour forecast |
| `get_current_conditions(latitude, longitude)` | Latest observation from the nearest NWS station, including temperature, wind, humidity and pressure |
| `get_active_alerts(latitude, longitude)` | Active warnings, watches and advisories |

The data comes live from [api.weather.gov](https://www.weather.gov/documentation/services-web-api).
No API key is needed.

### MCP server 2: Georgetown trout conditions (`trout_conditions_server.py`), custom

| Tool | What it does |
|---|---|
| `get_reservoir_info()` | Location, coordinates, elevation (8,445 ft), species, access and where to check regulations |
| `get_seasonal_conditions(date)` | Season phase, estimated water temperature, ice status, where trout hold |
| `get_sun_and_moon(date)` | Sunrise and sunset, best low-light bite windows, moon phase and illumination |
| `rate_fishing_conditions(air_temp_high_f, wind_mph, sky, date, precipitation_chance_pct, pressure_trend)` | Score from 1 to 10 with a breakdown by factor and safety warnings |
| `recommend_tactics(date, sky)` | Baits, lures, flies and approach for the season and light |

These tools are plain Python functions with no network calls. Sunrise and sunset use the NOAA
solar-position equations, and the moon phase is calculated from the lunar cycle. Water temperature
and ice status come from a seasonal model for a lake at about 8,400 ft and are labeled as estimates.
The coordinates and elevation were checked against OpenStreetMap and USGS.

### Routing

| Question | Route |
|---|---|
| "What's the forecast for Georgetown this weekend?" | `weather_agent` |
| "What lures should I use this time of year?" | `trout_agent` |
| "Is tomorrow a good day to fish?" | `weather_agent` gets the forecast, then `trout_agent` rates it using those numbers |

For the last pattern, the root agent passes the weather agent's forecast values (temperature, wind,
sky, precipitation chance) to the trout agent's `rate_fishing_conditions` tool. The root agent is
given today's Colorado date every turn, so it can resolve "tomorrow" and weekday names to real dates.

## Project structure

```
challenge-3-mcp/
├── mcp_servers/
│   ├── nws_weather_server.py       # MCP server: NWS weather tools
│   └── trout_conditions_server.py  # custom MCP server: trout tools
├── mcp_agent/
│   ├── __init__.py
│   ├── agent.py                    # root router + weather_agent + trout_agent
│   └── .env.example
├── test_mcp_servers.py             # tests both MCP servers directly (no LLM)
├── test_routing.py                 # runs sample questions through the agents
├── requirements.txt
└── README.md
```

## Setup

You need Python 3.10–3.13.

```powershell
cd challenge-3-mcp
uv venv --python 3.12 .venv          # or: python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy mcp_agent\.env.example mcp_agent\.env   # then fill it in
```

The `.env` file supports either backend:
- **Vertex AI:** set `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, your project ID and `GOOGLE_CLOUD_LOCATION=global`, then run `gcloud auth application-default login`.
- **Gemini API key:** set `GOOGLE_GENAI_USE_VERTEXAI=FALSE` and `GOOGLE_API_KEY`.

## Run

```powershell
python test_mcp_servers.py   # 1. check both MCP servers and all 9 tools (no LLM needed)
python test_routing.py       # 2. sample questions through the full agent system
adk web                      # 3. open http://localhost:8000 and select "mcp_agent"
```

### Example results (live test run, 2026-11-20, 5/5 routed correctly)

| Question | Routing | Answer (excerpt) |
|---|---|---|
| Forecast for Georgetown for the next two days? | weather | Sat high 40°F, W 5–14 mph, 30% snow showers; Sun 48°F; no alerts |
| Lures and flies for this time of year? | trout | Slow small spoons and jigs, PowerBait, midges and small nymphs; ice not safe |
| Sunrise on Saturday, and is the ice safe? | trout | 06:53 MST; skim ice is NOT safe to walk on |
| Is tomorrow a good day to fish? | weather → trout | 6/10 "Good": forecast fed into the rating, plus bite windows, tactics and shore-only warning |
| Any weather alerts for Denver right now? | weather | No active alerts |

Each MCP server can also be run on its own (`python mcp_servers/nws_weather_server.py`) and connected
to any MCP client, such as Claude Code or VS Code, over stdio.

## Notes

- **Requirement not met (Google-provided MCP server):** the assignment asks for one sub-agent to use
  an existing MCP server provided by Google. This build uses the National Weather Service instead,
  by choice. To meet that requirement, add a sub-agent that uses Google Maps Grounding Lite
  (`https://mapstools.googleapis.com/mcp`, which needs a Maps API key) through
  `McpToolset(StreamableHTTPConnectionParams(...))`, as shown in the
  [ADK MCP docs](https://adk.dev/tools-custom/mcp-tools/).
- **MCP SDK version:** this project uses MCP Python SDK 2.x, where `FastMCP` was renamed `MCPServer`
  (`from mcp.server.mcpserver import MCPServer`).
- **Regulations:** fishing regulations, limits and stocking change. Always confirm with Colorado
  Parks and Wildlife (cpw.state.co.us) before fishing, and never walk on ice you haven't checked.
