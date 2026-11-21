"""Unit tests (no cloud or model calls): backend MCP tools, privacy, metrics, dataset, agent wiring."""

import importlib.util
import json
from pathlib import Path

import pytest
from google.adk.evaluation.eval_case import IntermediateData, Invocation
from google.adk.evaluation.eval_config import EvalConfig
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types

ROOT = Path(__file__).resolve().parents[2]
RECORDS = [json.loads(l) for l in (ROOT / "data" / "backend" / "ads_operations.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.fixture()
def backend(monkeypatch):
    """Loads the ADS backend MCP server module with the datastore replaced by the local JSONL."""
    spec = importlib.util.spec_from_file_location("ads_backend_server", ROOT / "ads_agent" / "mcp_servers" / "ads_backend_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_records", lambda max_age_s=20: [dict(r) for r in RECORDS])
    return mod


# ------------------------------------------------------------------ backend MCP tools
def test_storm_status_lists_active_level_3_in_southcentral(backend):
    out = backend.get_storm_status("Southcentral")
    assert out["count"] == 1 and out["active_declarations"][0]["level"] == 3


def test_road_status_finds_turnagain_closed(backend):
    out = backend.get_road_status("Turnagain")
    assert out["count"] == 1 and out["segments"][0]["status"] == "closed"


def test_closures_exclude_reopened_by_default(backend):
    active = backend.list_road_closures()
    every = backend.list_road_closures(include_reopened=True)
    assert active["count"] == 4 and every["count"] == 5
    assert all(c["status"] == "active" for c in active["closures"])


def test_fleet_availability_calculation(backend):
    out = backend.get_plow_fleet_status("Southcentral")
    assert out["available_pct"] == 90.0 and out["meets_85pct_requirement"] is True
    assert out["operators_near_16h_limit"] == ["ADS-PL-105"]


def test_service_request_status_never_returns_personal_data(backend):
    out = backend.get_service_request_status("sr-2026-11-0413")
    assert out["found"] is True
    flat = json.dumps(out)
    assert "Luis Ortega" not in flat and "907-555-0172" not in flat
    assert "requester_name" not in out["request"]


def test_keyword_search_never_matches_on_personal_data(backend):
    assert backend.search_operations_records("Ortega")["count"] == 0
    assert backend.search_operations_records("Milepost 26")["count"] >= 1


def test_create_service_request_writes_document_without_pii(backend, monkeypatch):
    created = {}

    class FakeClient:
        def create_document(self, parent, document, document_id):
            created.update(parent=parent, id=document_id, data=dict(document.struct_data))

    monkeypatch.setattr(backend, "_docs_client", lambda: FakeClient())
    out = backend.create_service_request("Icy road or intersection needing sand", "5th Ave & A St, Anchorage", "Very icy")
    assert out["created"] and out["request_id"].startswith("SR-")
    assert created["parent"].endswith("/branches/default_branch")
    assert not set(created["data"]) & backend.PRIVATE_FIELDS


# ------------------------------------------------------------------ routing metric
def _inv(tools: list[str]) -> Invocation:
    return Invocation(
        invocation_id="i",
        user_content=types.Content(role="user", parts=[types.Part(text="q")]),
        final_response=types.Content(role="model", parts=[types.Part(text="a")]),
        intermediate_data=IntermediateData(tool_uses=[types.FunctionCall(name=t, args={}) for t in tools]),
    )


@pytest.mark.parametrize("expected, actual, score", [
    (["operations_agent"], ["operations_agent"], 1.0),
    (["operations_agent", "policy_agent"], ["operations_agent"], 0.5),
    (["operations_agent", "maps_agent"], ["maps_agent", "conditions_agent", "operations_agent"], 1.0),
    ([], [], 1.0),                    # refusal without lookups
    ([], ["maps_agent"], 0.0),        # refusal case must not plan a route
])
def test_routing_accuracy_scores(expected, actual, score):
    from ads_eval.metrics import routing_accuracy

    result = routing_accuracy(EvalMetric(metric_name="routing_accuracy", threshold=1.0), [_inv(actual)], [_inv(expected)])
    assert result.overall_score == pytest.approx(score)
    assert result.overall_eval_status == (EvalStatus.PASSED if score == 1.0 else EvalStatus.FAILED)


# ------------------------------------------------------------------ dataset, config, data
def test_evalset_and_config_are_valid():
    es = EvalSet.model_validate(json.loads((ROOT / "ads_eval" / "storm_response.evalset.json").read_text(encoding="utf-8")))
    cfg = EvalConfig.model_validate(json.loads((ROOT / "ads_eval" / "eval_config.json").read_text(encoding="utf-8")))
    assert len(es.eval_cases) >= 12
    assert {"routing_accuracy", "ads_grounded_factuality", "safety_v1"} <= set(cfg.criteria)


def test_reference_answers_agree_with_backend_ids():
    """Every closure/incident/unit/request ID mentioned in a reference answer exists in the backend."""
    import re

    ids = {r["id"] for r in RECORDS}
    data = json.loads((ROOT / "ads_eval" / "storm_response.evalset.json").read_text(encoding="utf-8"))
    for case in data["eval_cases"]:
        ref = case["conversation"][0]["final_response"]["parts"][0]["text"]
        for found in re.findall(r"\b(?:CL|INC|SR|ADS-PL|SEG)-[\w-]+\d", ref):
            assert found in ids, f"{case['eval_id']}: {found} not in backend data"


def test_policy_documents_present():
    docs = sorted(p.name for p in (ROOT / "data" / "policies").glob("*.txt"))
    assert len(docs) == 6


# ------------------------------------------------------------------ agent wiring
def test_agent_tree(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    from ads_agent.agent import root_agent

    names = sorted(t.agent.name for t in root_agent.tools)
    assert names == ["conditions_agent", "maps_agent", "operations_agent", "policy_agent"]
    tool_types = {t.agent.name: type(t.agent.tools[0]).__name__ for t in root_agent.tools}
    assert tool_types == {"policy_agent": "VertexAiSearchTool", "operations_agent": "McpToolset",
                          "maps_agent": "McpToolset", "conditions_agent": "GoogleSearchTool"}
    assert all(m.client_kwargs["location"] == "global" for m in root_agent.model.models)
