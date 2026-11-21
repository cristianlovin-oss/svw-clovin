"""Summit Trail Outfitters customer service agent.

The system prompt version is chosen with the PROMPT_VERSION environment variable:
  PROMPT_VERSION=baseline  (default) - simple instructions
  PROMPT_VERSION=revised             - explicit instructions after evaluation
"""

import os

from google.adk.agents import LlmAgent

from .prompts import INSTRUCTIONS

PROMPT_VERSION = os.getenv("PROMPT_VERSION", "baseline").strip().lower()
if PROMPT_VERSION not in INSTRUCTIONS:
    raise ValueError(f"PROMPT_VERSION must be one of {sorted(INSTRUCTIONS)}, got {PROMPT_VERSION!r}")

MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")

root_agent = LlmAgent(
    name="customer_service_agent",
    model=MODEL,
    description="Answers customer questions about Summit Trail Outfitters' policies.",
    instruction=INSTRUCTIONS[PROMPT_VERSION],
)
