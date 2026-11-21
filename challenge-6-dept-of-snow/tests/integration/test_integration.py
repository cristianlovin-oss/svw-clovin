"""Integration tests against live Google Cloud services (datastores, Maps MCP, Gemini).

    $env:RUN_INTEGRATION="1"; pytest tests/integration -v
"""

import json
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "ads_agent" / ".env")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use live services"),
]


def _stdio_toolset():
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    from mcp import StdioServerParameters

    return McpToolset(connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(command=sys.executable,
                                            args=[str(ROOT / "ads_agent" / "mcp_servers" / "ads_backend_server.py")],
                                            env={**os.environ}),
        timeout=60))


async def _call(ts, name, **args):
    session = await ts._mcp_session_manager.create_session()
    result = await session.call_tool(name, args)
    return json.loads(result.content[0].text)


async def test_ads_backend_mcp_server_over_stdio_reads_live_datastore():
    ts = _stdio_toolset()
    try:
        names = sorted(t.name for t in await ts.get_tools())
        assert names == sorted([
            "create_service_request", "get_plow_fleet_status", "get_road_status", "get_service_request_status",
            "get_storm_status", "list_incidents", "list_road_closures", "search_operations_records",
        ])
        closures = await _call(ts, "list_road_closures")
        assert closures["count"] == 4
        fleet = await _call(ts, "get_plow_fleet_status", region="Southcentral")
        assert fleet["meets_85pct_requirement"] is True
        sr = await _call(ts, "get_service_request_status", request_id="SR-2026-11-0413")
        assert "Luis Ortega" not in json.dumps(sr)
    finally:
        await ts.close()


async def test_google_maps_mcp_server_lists_tools():
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    ts = McpToolset(connection_params=StreamableHTTPConnectionParams(
        url="https://mapstools.googleapis.com/mcp",
        headers={"X-Goog-Api-Key": os.environ["GOOGLE_MAPS_API_KEY"]}, timeout=30))
    try:
        names = {t.name for t in await ts.get_tools()}
        assert {"search_places", "compute_routes", "lookup_weather"} <= names
    finally:
        await ts.close()


async def test_policy_datastore_search_returns_results():
    from google.cloud import discoveryengine_v1 as de

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    serving = (f"projects/{project}/locations/global/collections/default_collection/engines/"
               "ads-policy-search/servingConfigs/default_search")
    res = list(de.SearchServiceClient().search(request=de.SearchRequest(
        serving_config=serving, query="mailbox damage reimbursement", page_size=3)).results)
    assert res, "policy search returned no results"


async def test_root_agent_routes_closure_question_to_operations():
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from ads_agent.agent import root_agent

    runner = InMemoryRunner(agent=root_agent, app_name="it")
    session = await runner.session_service.create_session(app_name="it", user_id="u")
    calls, text = [], ""
    async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=types.Content(
            role="user", parts=[types.Part(text="Is Thompson Pass on the Richardson Highway open?")])):
        for p in (ev.content.parts if ev.content else None) or []:
            if p.function_call and ev.author == root_agent.name:
                calls.append(p.function_call.name)
            if p.text and ev.author == root_agent.name:
                text += p.text
    await runner.close()
    assert "operations_agent" in calls
    assert "closed" in text.lower()
