"""Smoke test for both MCP servers, without any LLM.

Starts each server over stdio with ADK's McpToolset (the same client the agents
use), lists the tools it exposes, and calls a few of them.

Usage (from the challenge-3-mcp folder):
    python test_mcp_servers.py
"""

import asyncio
import json
import sys
from pathlib import Path

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

SERVERS = Path(__file__).parent / "mcp_servers"
LAT, LON = 39.7269, -105.6919  # Georgetown Lake, CO


def toolset(script: str) -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(command=sys.executable, args=[str(SERVERS / script)]),
            timeout=30,
        )
    )


async def call(ts: McpToolset, name: str, **args):
    session = await ts._mcp_session_manager.create_session()
    result = await session.call_tool(name, args)
    text = result.content[0].text if result.content else "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def main():
    nws, trout = toolset("nws_weather_server.py"), toolset("trout_conditions_server.py")
    try:
        for label, ts in [("NWS weather", nws), ("Georgetown trout", trout)]:
            tools = await ts.get_tools()
            print(f"\n[{label}] MCP server exposes {len(tools)} tools: {[t.name for t in tools]}")

        f = await call(nws, "get_forecast", latitude=LAT, longitude=LON, periods=2)
        print("\nget_forecast:", f["location"], "|", [(p["name"], p["temperature_f"], p["wind"], p["short_forecast"]) for p in f["periods"]])
        c = await call(nws, "get_current_conditions", latitude=LAT, longitude=LON)
        print("get_current_conditions:", c["station"], f'({c["station_distance_miles"]} mi)', c["temperature_f"], "F", c["description"])
        a = await call(nws, "get_active_alerts", latitude=LAT, longitude=LON)
        print("get_active_alerts:", a["active_alert_count"], "alert(s)")

        print("\nget_reservoir_info:", (await call(trout, "get_reservoir_info"))["elevation_ft"], "ft")
        s = await call(trout, "get_seasonal_conditions", date="")
        print("get_seasonal_conditions:", s["season_phase"], "| water ~", s["estimated_surface_water_temp_f"], "F |", s["ice_status"])
        m = await call(trout, "get_sun_and_moon", date="")
        print("get_sun_and_moon: sunrise", m["sunrise"], "sunset", m["sunset"], "| moon", m["moon"])
        r = await call(trout, "rate_fishing_conditions", air_temp_high_f=43, wind_mph=23, sky="sunny", pressure_trend="falling")
        print("rate_fishing_conditions:", r["score_1_to_10"], "/10 -", r["verdict"], "| warnings:", r["warnings"])
        t = await call(trout, "recommend_tactics", date="2026-07-20", sky="sunny")
        print("recommend_tactics (July):", t["season_phase"], "|", t["lures"])
        print("\nAll MCP tool calls succeeded.")
    finally:
        await nws.close()
        await trout.close()


if __name__ == "__main__":
    asyncio.run(main())
