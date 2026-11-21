"""Creates a Gemini Enterprise app (if needed) and registers the deployed ADK agent in it.

Usage (after deploy/deploy_agent_engine.py):
    python deploy/register_gemini_enterprise.py
    python deploy/register_gemini_enterprise.py --list      # list agents registered in the app

Steps:
  1. Gemini Enterprise app = Discovery Engine engine with app_type APP_TYPE_INTRANET
     ("ads-gemini-enterprise", global), with the ADS policy datastore attached for search.
  2. Register the Agent Engine reasoning engine as an ADK agent in the app's default assistant
     (Discovery Engine v1alpha agents API).
Writes the result into deploy/deployment.json.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google.api_core.exceptions import AlreadyExists
from google.cloud import discoveryengine_v1 as de

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "ads_agent" / ".env")
STATE_FILE = ROOT / "deploy" / "deployment.json"
STATE = json.loads(STATE_FILE.read_text())
PROJECT, NUMBER = STATE["project"], STATE["project_number"]
APP_ID = os.getenv("GEMINI_ENTERPRISE_APP_ID", "ads-gemini-enterprise")
COLLECTION = f"projects/{PROJECT}/locations/global/collections/default_collection"
API = "https://discoveryengine.googleapis.com/v1alpha"
AGENTS_URL = f"{API}/projects/{NUMBER}/locations/global/collections/default_collection/engines/{APP_ID}/assistants/default_assistant/agents"
GCLOUD = "gcloud.cmd" if os.name == "nt" else "gcloud"


def headers() -> dict:
    token = subprocess.run([GCLOUD, "auth", "print-access-token"], text=True, capture_output=True).stdout.strip()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Goog-User-Project": PROJECT}


def create_app() -> None:
    print(f"==> Gemini Enterprise app {APP_ID}")
    try:
        de.EngineServiceClient().create_engine(
            parent=COLLECTION, engine_id=APP_ID,
            engine=de.Engine(
                display_name="Alaska Department of Snow",
                solution_type=de.SolutionType.SOLUTION_TYPE_SEARCH,
                industry_vertical=de.IndustryVertical.GENERIC,
                app_type=de.Engine.AppType.APP_TYPE_INTRANET,
                data_store_ids=["ads-policy-docs"],
                search_engine_config=de.Engine.SearchEngineConfig(
                    search_tier=de.SearchTier.SEARCH_TIER_ENTERPRISE,
                    search_add_ons=[de.SearchAddOn.SEARCH_ADD_ON_LLM],
                ),
            ),
        ).result(timeout=600)
        print("    created")
    except AlreadyExists:
        print("    exists")


def list_agents() -> list[dict]:
    r = httpx.get(AGENTS_URL, headers=headers(), timeout=60)
    r.raise_for_status()
    return r.json().get("agents", [])


def register() -> dict:
    existing = [a for a in list_agents()
                if a.get("adkAgentDefinition", {}).get("provisionedReasoningEngine", {}).get("reasoningEngine") == STATE["reasoning_engine"]]
    if existing:
        print(f"==> Agent already registered: {existing[0]['name']}")
        return existing[0]
    print("==> Registering ADK agent")
    body = {
        "displayName": "ADS Storm Response Assistant",
        "description": "Alaska Department of Snow storm-response assistant: road closures, plow fleet, "
                       "service requests, ADS policies, Google Maps routes and live conditions.",
        "adk_agent_definition": {
            "tool_settings": {
                "tool_description": "Answers Alaska Department of Snow storm-response questions using ADS policies, "
                                    "ADS operations records, Google Maps and live web conditions."
            },
            "provisioned_reasoning_engine": {"reasoning_engine": STATE["reasoning_engine"]},
        },
    }
    r = httpx.post(AGENTS_URL, headers=headers(), json=body, timeout=120)
    if r.status_code >= 400:
        sys.exit(f"Registration failed {r.status_code}: {r.text[:800]}")
    return r.json()


if __name__ == "__main__":
    if "--list" in sys.argv:
        for a in list_agents():
            print(a.get("displayName"), "|", a.get("name"), "|", a.get("state"))
        sys.exit()
    create_app()
    agent = register()
    STATE.update(gemini_enterprise_app=f"{COLLECTION}/engines/{APP_ID}", gemini_enterprise_agent=agent.get("name"))
    STATE_FILE.write_text(json.dumps(STATE, indent=2), encoding="utf-8")
    print(f"    agent: {agent.get('name')}  state: {agent.get('state')}")
    print(f"\nOpen Gemini Enterprise: https://console.cloud.google.com/gemini-enterprise/locations/global/engines/{APP_ID}/overview?project={PROJECT}")
