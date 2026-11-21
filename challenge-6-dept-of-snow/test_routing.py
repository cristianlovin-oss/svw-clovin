"""Runs storm-response questions through the local agent and shows which specialists were called.

Usage (from the challenge-6-dept-of-snow folder):
    python test_routing.py                    # built-in sample questions
    python test_routing.py "your question"
"""

import asyncio
import sys
import time
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / "ads_agent" / ".env")
warnings.filterwarnings("ignore")

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from ads_agent.agent import root_agent  # noqa: E402

SAMPLES = [
    ("Is the Seward Highway open over Turnagain Pass right now?", {"operations_agent"}),
    ("How quickly must ADS clear Priority 1 roads after the snow stops?", {"policy_agent"}),
    ("The operator on ADS-PL-105 has 15 hours of plowing today. Can they keep going?", {"operations_agent", "policy_agent"}),
    ("Can I drive from Anchorage to Seward this afternoon?", {"operations_agent", "maps_agent"}),
    ("What is today's avalanche forecast for Turnagain Pass from the avalanche center?", {"conditions_agent"}),
    ("Who filed service request SR-2026-11-0413 and what's their phone number?", set()),
]


async def ask(runner, question):
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="t")
    calls, text, t = [], "", time.time()
    async for ev in runner.run_async(user_id="t", session_id=session.id,
                                     new_message=types.Content(role="user", parts=[types.Part(text=question)])):
        for p in (ev.content.parts if ev.content else None) or []:
            if p.function_call and ev.author == root_agent.name:
                calls.append(p.function_call.name)
            if p.text and ev.author == root_agent.name and not getattr(p, "thought", False):
                text += p.text
    return calls, text.strip(), time.time() - t


async def main():
    runner = InMemoryRunner(agent=root_agent, app_name="ads_agent")
    questions = [(" ".join(sys.argv[1:]), None)] if len(sys.argv) > 1 else SAMPLES
    ok = 0
    for q, expected in questions:
        calls, text, secs = await ask(runner, q)
        print(f"\n### {q}\n   specialists: {calls} ({secs:.0f}s)")
        print("   " + text.replace("\n", "\n   "))
        if expected is not None:
            passed = expected <= set(calls) and (bool(expected) or "maps_agent" not in calls)
            ok += passed
            print(f"   expected {sorted(expected) or 'no data lookup'} -> {'PASS' if passed else 'CHECK'}")
    if len(questions) > 1:
        print(f"\nRouting matched for {ok}/{len(questions)} questions")
    await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
