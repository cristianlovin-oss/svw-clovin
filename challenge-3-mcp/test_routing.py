"""Runs sample questions through the full agent system and shows the routing.

Usage (from the challenge-3-mcp folder):
    python test_routing.py                  # built-in sample questions
    python test_routing.py "your question"  # ask your own
"""

import asyncio
import sys
import time
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / "mcp_agent" / ".env")
warnings.filterwarnings("ignore")

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from mcp_agent.agent import root_agent, trout_agent, weather_agent  # noqa: E402

SAMPLES = [
    ("What's the weather forecast for Georgetown, Colorado for the next two days?", ["weather_agent"]),
    ("What lures and flies should I use at Georgetown Reservoir this time of year?", ["trout_agent"]),
    ("What time is sunrise at the reservoir on Saturday, and is the ice safe to walk on?", ["trout_agent"]),
    ("Is tomorrow a good day to go trout fishing at Georgetown Reservoir?", ["weather_agent", "trout_agent"]),
    ("Are there any weather alerts for Denver right now?", ["weather_agent"]),
]


async def ask(runner, sessions, question):
    session = await sessions.create_session(app_name="mcp", user_id="tester")
    calls, answer, t = [], "", time.time()
    async for ev in runner.run_async(
        user_id="tester", session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=question)]),
    ):
        for p in (ev.content.parts if ev.content else None) or []:
            if p.function_call:
                calls.append(p.function_call.name)
                if ev.author == root_agent.name:
                    print(f"   root -> {p.function_call.name}({dict(p.function_call.args or {})})")
            if p.text and ev.author == root_agent.name and not getattr(p, "thought", False):
                answer += p.text
    return calls, answer.strip(), time.time() - t


async def main():
    sessions = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name="mcp", session_service=sessions)
    questions = [(" ".join(sys.argv[1:]), None)] if len(sys.argv) > 1 else SAMPLES
    passed = 0
    try:
        for q, expected in questions:
            print(f"\n### Q: {q}")
            calls, answer, secs = await ask(runner, sessions, q)
            root_calls = [c for c in calls if c in ("weather_agent", "trout_agent")]
            print(f"   routing order: {root_calls}  ({secs:.0f}s)")
            print("   answer:\n" + "\n".join("     " + line for line in answer.splitlines()))
            if expected is not None:
                # expected agents must appear, in that order
                it = iter(root_calls)
                ok = all(e in it for e in expected)
                passed += ok
                print(f"   expected {expected} -> {'PASS' if ok else 'CHECK'}")
        if questions is SAMPLES:
            print(f"\nRouting matched expectations for {passed}/{len(SAMPLES)} questions.")
    finally:
        for agent in (weather_agent, trout_agent):
            for tool in agent.tools:
                if hasattr(tool, "close"):
                    await tool.close()


if __name__ == "__main__":
    asyncio.run(main())
