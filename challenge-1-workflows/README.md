# Challenge 1 – Multi-Agent Workflows with Google ADK

A multi-agent research assistant built with the [Agent Development Kit (ADK)](https://google.github.io/adk-docs/).
A root **coordinator** routes each user message to the right specialist. A **research workflow**
researches, drafts, validates and refines an answer. A **feedback agent** asks the user whether the
answer is adequate and sends it back for rework if it is not. All agents share data through
**session state**.

## Architecture

```
coordinator (root LlmAgent)  ── routes requests, saves them to state
├── research_workflow (SequentialAgent)
│   ├── researcher      → state["research_findings"]   (uses web_searcher → Google Search)
│   ├── drafter         → state["draft_response"]
│   ├── validate_refine_loop (LoopAgent, max 3 iterations)
│   │   ├── validator   → state["validation_report"]   (calls approve_response to exit loop)
│   │   └── refiner     → state["draft_response"]      (rewrites the draft)
│   └── presenter       → state["final_response"]      (asks "Is this response adequate?")
└── feedback_agent      ── human-in-the-loop: records verdict, hands back to the workflow
```

### Request flow

1. **Routing**: the coordinator calls `save_user_request`, which writes `user_request` and
   `request_history` to state, and then transfers to `research_workflow`.
2. **Research**: `researcher` runs Google searches through the `web_searcher` sub-agent (used as a tool)
   and saves its notes to `research_findings`.
3. **Draft**: `drafter` reads `{research_findings}` from state and writes `draft_response`.
4. **Validate and refine loop**: `validator` checks accuracy, completeness and relevance.
   - If the draft passes, it calls `approve_response`. This sets `validation_status = "approved"` and
     escalates out of the loop.
   - If the draft fails, it writes a list of issues to `validation_report`. `refiner` then rewrites
     `draft_response`, and the loop repeats up to 3 times.
5. **Present**: `presenter` delivers the answer and asks the user whether it is adequate. An
   `after_agent_callback` sets `awaiting_feedback = True`.
6. **Human feedback (bonus)**: the coordinator sees `awaiting_feedback` and transfers to `feedback_agent`.
   - **"yes"**: the feedback agent records acceptance and the conversation continues.
   - **"add X / fix Y"**: the feedback agent stores the comments in `user_feedback` and transfers back
     to `research_workflow`. The researcher, drafter, validator and refiner all read `{user_feedback}`.

### Session state keys

| Key | Written by | Read by |
|-----|-----------|---------|
| `user_request`, `request_history` | coordinator (`save_user_request`) | all agents |
| `research_findings` | researcher | drafter, validator, refiner |
| `draft_response` | drafter, refiner | validator, refiner, presenter |
| `validation_report` | validator | refiner |
| `validation_status` | `approve_response` tool | presenter |
| `final_response` | presenter | feedback_agent |
| `awaiting_feedback` | workflow callback, `record_feedback` | coordinator |
| `user_feedback`, `feedback_rounds` | feedback_agent (`record_feedback`) | researcher, drafter, validator, refiner |

## Project structure

```
challenge-1-workflows/
├── research_assistant/
│   ├── __init__.py
│   ├── agent.py          # agent definitions (root_agent)
│   ├── tools.py          # state tools + callbacks
│   └── .env.example      # copy to .env and add your API key
├── run_demo.py           # terminal demo that can print session state
├── requirements.txt
└── README.md
```

## Setup

You need **Python 3.10–3.13**. Some ADK dependencies don't publish wheels for newer versions yet.

```powershell
cd challenge-1-workflows
python -m venv .venv            # or: uv venv --python 3.12
.venv\Scripts\activate
pip install -r requirements.txt

copy research_assistant\.env.example research_assistant\.env
# edit research_assistant\.env and set GOOGLE_API_KEY (https://aistudio.google.com/apikey)
```

## Run

**Web UI.** This is the best option for seeing events, agent handoffs and the State tab:

```powershell
adk web
```

Open http://localhost:8000 and select `research_assistant`.

**Terminal:**

```powershell
adk run research_assistant
# or, to inspect session state between turns (type "state"):
python run_demo.py
```

### Example conversation

```
You: What are the main differences between solar and wind power for a small farm?
presenter: ...validated answer with sources...
           Is this response adequate? Reply 'yes' or tell me what to change.
You: Add rough installation costs please.
presenter: ...revised answer including costs...
           Is this response adequate? Reply 'yes' or tell me what to change.
You: yes
feedback_agent: Glad it helps! Ask me anything else.
```

## Notes

- `google_search` is a built-in Gemini tool. It runs in its own agent (`web_searcher`) that is wrapped
  with `AgentTool`, because built-in tools can't be mixed with other tools or used directly inside
  sub-agents.
- In ADK 2.x, `SequentialAgent` and `LoopAgent` print a deprecation warning that points to the newer
  `Workflow` class. This project still uses them because `Workflow` can't yet be a sub-agent of an
  `LlmAgent`, and this design needs that so the coordinator can route to it.
- **Model fallback:** every agent uses ADK's `FallbackModel`. The primary model is `gemini-3.5-flash`.
  If it is overloaded (503), rate limited (429) or erroring (5xx), the request moves on to
  `gemini-3.6-flash` and then `gemini-3.5-flash-lite`. Each model also retries briefly first.
  Change the order with `ADK_MODEL` and `ADK_FALLBACK_MODELS` in `.env`.
- **Search quota:** Google Search grounding has its own quota, separate from normal model calls, and
  free-tier keys often have little or none. If search fails, an `on_model_error_callback` on
  `web_searcher` returns a "search unavailable" notice. The researcher then uses model knowledge and
  marks it as unverified, and the final answer says that live sources weren't available.
