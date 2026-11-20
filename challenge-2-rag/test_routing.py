"""Runs sample questions through the agent and shows which tool(s) the root chose.

Usage (from the challenge-2-rag folder):
    python test_routing.py                 # run the built-in sample questions
    python test_routing.py "your question" # ask your own question
"""

import asyncio
import sys
import time
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / "rag_agent" / ".env")
warnings.filterwarnings("ignore")

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from rag_agent.agent import root_agent  # noqa: E402

SAMPLES = [
    # (question, expected tool(s))
    ("How many days of annual leave do I get after 5 years at Lumora?", {"private_search_agent"}),
    ("What is the list price of a LumaBot X2-C and how much is the FleetOS licence?", {"private_search_agent"}),
    ("What was the most important AI news this week?", {"web_search_agent"}),
    ("What is our hotel cap in Zurich, and what is today's EUR to CHF exchange rate?", {"private_search_agent", "web_search_agent"}),
    ("Can I bring my dog to the Munich office?", {"private_search_agent", "web_search_agent"}),
]


async def ask(runner, session_service, question):
    session = await session_service.create_session(app_name="rag", user_id="tester")
    tools_called, answer, t = [], "", time.time()
    async for ev in runner.run_async(
        user_id="tester",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=question)]),
    ):
        for p in (ev.content.parts if ev.content else None) or []:
            if p.function_call:
                tools_called.append(p.function_call.name)
            if p.function_response and p.function_response.name == "private_search_agent":
                body = str(p.function_response.response)
                print(f"   private_search_agent returned: {body[:160]!r}...")
            if p.text and ev.author == root_agent.name and not getattr(p, "thought", False):
                answer += p.text
    return tools_called, answer.strip(), time.time() - t


async def main():
    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name="rag", session_service=session_service)
    questions = [(" ".join(sys.argv[1:]), None)] if len(sys.argv) > 1 else SAMPLES
    passed = 0
    for q, expected in questions:
        print(f"\n### Q: {q}")
        tools, answer, secs = await ask(runner, session_service, q)
        print(f"   routed to: {tools}  ({secs:.0f}s)")
        print("   answer:\n" + "\n".join("     " + line for line in answer.splitlines()))
        if expected is not None:
            ok = expected.issubset(set(tools))
            passed += ok
            print(f"   expected {sorted(expected)} -> {'PASS' if ok else 'CHECK'}")
    if questions is SAMPLES:
        print(f"\nRouting matched expectations for {passed}/{len(SAMPLES)} questions.")


if __name__ == "__main__":
    asyncio.run(main())
