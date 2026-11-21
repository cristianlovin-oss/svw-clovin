"""Deploys ads_agent to Vertex AI Agent Engine and grants the IAM roles it needs.

Usage (from the challenge-6-dept-of-snow folder):
    python deploy/deploy_agent_engine.py            # create a new Agent Engine instance
    python deploy/deploy_agent_engine.py --update   # redeploy to the instance in deploy/deployment.json

Writes deploy/deployment.json with the reasoning engine resource name.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "ads_agent" / ".env")
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION = os.getenv("AGENT_ENGINE_REGION", "us-central1")
STATE = ROOT / "deploy" / "deployment.json"
ADK = Path(sys.executable).parent / ("adk.exe" if os.name == "nt" else "adk")
GCLOUD = "gcloud.cmd" if os.name == "nt" else "gcloud"


def run(cmd, **kw):
    print("$", " ".join(cmd[:6]), "..." if len(cmd) > 6 else "", flush=True)
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def project_number() -> str:
    return run([GCLOUD, "projects", "describe", PROJECT, "--format=value(projectNumber)"]).stdout.strip()


def deploy(update: bool) -> str:
    cmd = [str(ADK), "deploy", "agent_engine", "--project", PROJECT, "--region", REGION,
           "--display_name", "ADS Storm Response Assistant",
           "--description", "Alaska Department of Snow storm-response assistant (policy RAG, ADS backend MCP, Google Maps MCP, Google Search).",
           "ads_agent"]
    if update and STATE.exists():
        engine_id = json.loads(STATE.read_text())["reasoning_engine"].rsplit("/", 1)[-1]
        cmd[3:3] = ["--agent_engine_id", engine_id]
    proc = run(cmd, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = proc.stdout + proc.stderr
    (ROOT / "deploy" / "deploy.log").write_text(out, encoding="utf-8")
    m = re.findall(r"projects/[\w-]+/locations/[\w-]+/reasoningEngines/\d+", out)
    if proc.returncode != 0 or not m:
        sys.exit(f"Deployment failed (exit {proc.returncode}); see deploy/deploy.log")
    return m[-1]


def grant_roles(number: str) -> None:
    """Agent Engine runs as the AI Platform Reasoning Engine service agent; it needs to read/write
    the AI Applications datastores (Vertex AI Search grounding + ADS backend MCP server)."""
    members = [
        f"serviceAccount:service-{number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com",
        f"serviceAccount:service-{number}@gcp-sa-aiplatform.iam.gserviceaccount.com",
    ]
    for member in members:
        for role in ("roles/discoveryengine.editor", "roles/aiplatform.user"):
            p = run([GCLOUD, "projects", "add-iam-policy-binding", PROJECT, f"--member={member}",
                     f"--role={role}", "--condition=None", "--quiet", "--format=none"])
            print(f"   {role} -> {member.split(':')[1]}: {'ok' if p.returncode == 0 else p.stderr.strip()[:120]}")


if __name__ == "__main__":
    resource = deploy(update="--update" in sys.argv)
    print(f"Deployed: {resource}")
    number = project_number()
    grant_roles(number)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}  # keep Gemini Enterprise fields
    state.update(project=PROJECT, project_number=number, region=REGION, reasoning_engine=resource)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Saved {STATE}")
