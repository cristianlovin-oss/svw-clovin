"""Terminal demo that runs the agent and prints the shared session state.

Usage (from the challenge-1-workflows folder):
    python run_demo.py

Type your request, answer the "Is this response adequate?" question, and type
"state" to dump the session state or "quit" to exit.
"""

import asyncio
import json

from dotenv import load_dotenv

load_dotenv("research_assistant/.env")

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from research_assistant.agent import root_agent  # noqa: E402

APP_NAME = "research_assistant"
USER_ID = "demo_user"


async def main() -> None:
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)

    print("Research assistant ready. Type 'state' to see session state, 'quit' to exit.\n")
    while True:
        text = input("You: ").strip()
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            break
        if text.lower() == "state":
            current = await session_service.get_session(
                app_name=APP_NAME, user_id=USER_ID, session_id=session.id
            )
            print(json.dumps(current.state, indent=2, default=str))
            continue

        message = types.Content(role="user", parts=[types.Part(text=text)])
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        ):
            if not (event.content and event.content.parts):
                continue
            for part in event.content.parts:
                if part.function_call:
                    print(f"  [{event.author}] -> calls {part.function_call.name}")
                elif part.text and event.author in {"coordinator", "presenter", "feedback_agent"}:
                    print(f"\n{event.author}: {part.text}\n")
                elif part.text:
                    print(f"  [{event.author}] finished ({len(part.text)} chars)")


if __name__ == "__main__":
    asyncio.run(main())
