# Challenge 2 – Multi-Agent RAG with Private Search and Google Search

A multi-agent assistant built with the [Agent Development Kit (ADK)](https://adk.dev/) that has
**two grounding tools**:

1. **Private RAG search**: a **Google Cloud AI Applications** (Vertex AI Search) data store holding
   the internal documents of a fictional company, Lumora Robotics.
2. **Google Search**: live public information, used when the private corpus can't answer.

A **root agent** reads each question and routes it to the right tool. It can also use both tools,
or fall back to the web when the internal documents don't have the answer.

## Architecture

```
knowledge_router (root LlmAgent)
├── AgentTool → private_search_agent   VertexAiSearchTool → AI Applications data store "lumora-internal-docs"
└── AgentTool → web_search_agent       google_search      → live Google Search results
```

| Question type | Route |
|---|---|
| About Lumora: policies, leave, expenses, IT security, LumaBot X2 specs and prices, support SLAs, onboarding | `private_search_agent` |
| Outside world or time-sensitive: news, exchange rates, standards, competitors | `web_search_agent` |
| Needs both, e.g. "our Zurich hotel cap + today's EUR/CHF rate" | both, combined into one answer |
| Private docs return `NOT_FOUND_IN_PRIVATE_DOCS` | falls back to `web_search_agent` and tells the user |

**Why `AgentTool`?** ADK's built-in grounding tools (`VertexAiSearchTool`, `google_search`) must be
the only tool in their agent. Each one therefore lives in its own specialist sub-agent, and the root
calls the specialists as tools. This is the approach ADK's documentation recommends, and it lets the
root call one tool, then the other, in the same turn.

**Model resilience:** every agent uses ADK `FallbackModel`, with `gemini-3.5-flash` as the primary
model and `gemini-2.5-flash` as the fallback. A model that is overloaded or rate limited is skipped
automatically.

## The RAG data store

`setup_datastore.py` creates everything with the Google Cloud Python SDKs. It is safe to re-run:

1. Creates the Cloud Storage bucket `<project>-lumora-corpus` and uploads the documents in `corpus/`.
2. Creates the AI Applications data store `lumora-internal-docs` (generic, unstructured documents).
3. Imports the documents from Cloud Storage. Each import fully replaces the data store contents.
4. Creates the search app `lumora-internal-search` (Enterprise tier with LLM add-on) on top of the data store.
5. Polls a test query until the documents are indexed.

You can see the data store and app in the Cloud console under **AI Applications → Data stores / Apps**.

### Corpus (`corpus/`)

| File | Contents |
|---|---|
| `employee_handbook.txt` | Hybrid work, leave, parental leave, expenses and travel caps, learning budget |
| `product_lumabot_x2.txt` | LumaBot X2 robot specs, FleetOS 4.3, list prices, discounts, warranty, lead times |
| `it_security_policy.txt` | Passwords, MFA, devices, VPN, data classification, incident reporting |
| `customer_support_sla.txt` | Standard, Premium and Enterprise support plans, response times, escalation |
| `onboarding_faq.txt` | First week, probation, payday, tools, desk booking, benefits, referral bonus |

All of this content is fictional, so Google Search can't know it. That makes it easy to see when
the agent is grounded in the private data and when it's using the web.

## Project structure

```
challenge-2-rag/
├── rag_agent/
│   ├── __init__.py
│   ├── agent.py          # root router + private_search_agent + web_search_agent
│   └── .env.example      # copy to .env
├── corpus/               # private documents indexed by the data store
├── setup_datastore.py    # creates bucket, data store, import, search app
├── test_routing.py       # sample questions; shows which tool was chosen
├── requirements.txt
└── README.md
```

## Setup

Prerequisites:
- A Google Cloud project with billing, such as a Qwiklabs lab project.
- The gcloud CLI.
- Python 3.10–3.13.

```powershell
cd challenge-2-rag
uv venv --python 3.12 .venv          # or: python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Sign in (user + Application Default Credentials) and pick the project
gcloud auth login --update-adc
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
gcloud services enable discoveryengine.googleapis.com aiplatform.googleapis.com storage.googleapis.com

copy rag_agent\.env.example rag_agent\.env   # then set GOOGLE_CLOUD_PROJECT and DATASTORE_ID
python setup_datastore.py                    # creates and indexes the data store (about 5 min)
```

## Run

```powershell
adk web                 # open http://localhost:8000 and select "rag_agent"
python test_routing.py  # runs the sample questions and prints the routing decision for each
python test_routing.py "What is the Premium support response time for a P1 issue?"
```

### Example results (live test run)

| Question | Routed to | Answer (excerpt) |
|---|---|---|
| How many days of annual leave do I get after 5 years at Lumora? | private | 30 days (28 base + 2 after 5 years) |
| List price of a LumaBot X2-C and the FleetOS licence? | private | EUR 46,900; EUR 1,100 per robot per year |
| What was the most important AI news this week? | web | Summary of the week's news with sources |
| Our hotel cap in Zurich, and today's EUR/CHF rate? | private + web | EUR 220 per night; the live exchange rate |
| Can I bring my dog to the Munich office? | private → `NOT_FOUND` → web | Neither source has it, so the agent says so and suggests asking HR instead of guessing |

## Notes

- This agent runs on **Vertex AI** (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`) because the AI Applications
  data store is a Google Cloud resource. Google Search grounding on Vertex AI uses the project's
  billing, not the AI Studio free-tier quota.
- In the lab project, `gemini-3.5-flash` is available in the `global` location only, which is why
  `GOOGLE_CLOUD_LOCATION=global`.
- Qwiklabs projects are deleted when the lab ends. To run this again in a new project, update `.env`
  and re-run `setup_datastore.py`.
