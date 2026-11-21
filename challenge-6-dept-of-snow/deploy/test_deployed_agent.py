"""Sends test questions to the agent deployed on Agent Engine and prints the answers.

Usage:  python deploy/test_deployed_agent.py ["your question"]
"""

import asyncio
import json
import sys
from pathlib import Path

import vertexai

STATE = json.loads((Path(__file__).resolve().parent / "deployment.json").read_text())
QUESTIONS = sys.argv[1:] or [
    "Is the Seward Highway open over Turnagain Pass right now?",
    "How quickly must ADS clear Priority 1 roads after the snow stops?",
]


async def main():
    client = vertexai.Client(project=STATE["project"], location=STATE["region"])
    remote = client.agent_engines.get(name=STATE["reasoning_engine"])
    for q in QUESTIONS:
        print(f"\n### {q}")
        session = await remote.async_create_session(user_id="deploy-test")
        calls, text = [], ""
        async for event in remote.async_stream_query(user_id="deploy-test", session_id=session["id"], message=q):
            for part in (event.get("content") or {}).get("parts", []):
                if "function_call" in part:
                    calls.append(part["function_call"]["name"])
                if "text" in part and event.get("author") == "ads_storm_router":
                    text += part["text"]
        print(f"   tools called: {calls}")
        print("   " + text.strip().replace("\n", "\n   "))


asyncio.run(main())
