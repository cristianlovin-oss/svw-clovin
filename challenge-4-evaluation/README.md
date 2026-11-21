# Challenge 4 – Evaluating a Customer Service Agent with the ADK Evaluation API

This project builds a simple customer service agent for **Summit Trail Outfitters**, a fictional
online outdoor-gear retailer, and tests it systematically with the
[ADK Agent Evaluation API](https://adk.dev/evaluate/).

1. A **baseline** agent gets deliberately simple instructions plus the company's FAQ and policies.
2. An **evaluation dataset** (18 cases) is run against it, and the results are written up in a report.
3. The system prompt is **revised** with explicit instructions, based on the baseline failures.
4. The evaluation is **re-run**, and a comparison report shows whether the change helped.
5. **Bonus:** unit and integration tests.

## The agent

| File | Purpose |
|---|---|
| `customer_service_agent/policies.md` | The FAQ and policies (11 sections: returns, refunds, shipping, order changes, price match, warranty, damaged items, loyalty, payment, privacy, contact) |
| `customer_service_agent/prompts.py` | `BASELINE_INSTRUCTION` (2 sentences + policies) and `REVISED_INSTRUCTION` (explicit rules + the same policies) |
| `customer_service_agent/agent.py` | `root_agent`; the prompt version comes from `PROMPT_VERSION=baseline\|revised` |

Both versions use the same model (`gemini-2.5-flash`) and the same policy text, so any difference in
scores comes from the instructions alone.

## Evaluation design

**Dataset:** `eval/customer_service.evalset.json` (ADK `EvalSet` format), generated from the readable
case list in `eval/build_evalset.py`. Each case has a customer message and a reference answer written
from the policies.

| Category | Cases | What it tests |
|---|---|---|
| Policy accuracy | 10 | Return window, refund timing, shipping thresholds and cutoffs, cancellations, price match exclusions, warranty, loyalty points, damaged items, gift cards |
| Outside policy / needs a human | 3 | No physical stores, used item after 60 days, order-status lookup (the agent has no order access) |
| Safety and adversarial | 5 | Prompt injection asking for a discount code, a shared card number, another customer's data, an abusive customer, a dangerous request (refilling fuel canisters) |

**Metrics** (`eval/eval_config.json`, threshold 0.8 each):

| Metric | ADK criterion | How it scores |
|---|---|---|
| **FINAL_RESPONSE_QUALITY** | `rubric_based_final_response_quality_v1` | A Gemini judge (3 samples, majority vote) checks 5 rubrics: answers directly, no invented policy, handles unknowns by escalating, professional tone, concise |
| **SAFETY** | `safety_v1` | Vertex AI Gen AI Evaluation Service harmlessness score |
| **policy_grounded_factuality** | custom metric (`customer_service_agent/metrics.py`) | A Gemini judge compares each answer with the policy document and the reference answer: 1.0 = fully grounded, 0.5 = missing a key condition, 0.0 = wrong or invented |

ADK also reports **token usage** and **response time** for every case. They don't pass or fail a
case; the comparison report uses them to show the cost of the longer revised prompt.

## Results

### Baseline run (completed, `gemini-2.5-flash`, 18 cases): see [`reports/baseline_report.md`](reports/baseline_report.md)

| Metric | Mean | Cases passing (of those scored) |
|---|---|---|
| FINAL_RESPONSE_QUALITY | 1.00 | 18/18 |
| SAFETY | 1.00 | 15/15 |
| policy_grounded_factuality | 0.71 | 6/14 |

- **No unsafe answers.** Every scored response passed SAFETY, including the prompt-injection, card-number,
  other-customer, abusive-customer and dangerous-request cases.
- **The generic quality rubric is too lenient.** It gave 1.00 to every answer, including answers the
  factuality judge marked incomplete. A domain-specific metric (`policy_grounded_factuality`) was needed to
  find the real weakness.
- **The baseline omits conditions and next steps rather than inventing facts.** Every factuality failure
  scored 0.5, not 0.0. The simple prompt left out policy conditions and next steps: the wear-and-tear
  exclusion on the warranty, delivery times, other price-match conditions, how to start a return, the
  warranty alternative for a used tent, and "contact support". The one unsupported claim was extra safety
  detail about fuel canisters.

**How the revised prompt responds** (`REVISED_INSTRUCTION` in `prompts.py`): it makes the policies the
only source of truth, requires the relevant conditions and exceptions to be mentioned, requires contact
details whenever something can't be answered, and adds explicit rules for security, manipulation and harm.

### Revised run: pending

The revised evaluation could not finish in the lab project. Its Vertex AI quota for `gemini-2.5-flash`
(the agent model, judge model and the SAFETY service's internal judge) was exhausted (HTTP 429 on every
request). Rate limits also left 3 SAFETY and 4 factuality baseline scores unscored; the report marks these
cases INCOMPLETE rather than failed. When quota is available:

```powershell
python run_evaluation.py revised          # revised prompt, same dataset and metrics
python run_evaluation.py fill baseline    # re-score only the baseline cases with missing scores
```

`make_reports.py` then writes `reports/revised_report.md` and `reports/comparison_report.md`
automatically. These cover the before/after scores, the case-level fixes and regressions, and a table of
the prompt changes.

## Project structure

```
challenge-4-evaluation/
├── customer_service_agent/
│   ├── __init__.py
│   ├── agent.py            # root_agent (PROMPT_VERSION selects the prompt)
│   ├── prompts.py          # baseline + revised system prompts
│   ├── policies.md         # FAQ and policies given to the agent
│   ├── metrics.py          # custom metric: policy_grounded_factuality
│   └── .env.example
├── eval/
│   ├── build_evalset.py    # authors the dataset
│   ├── customer_service.evalset.json
│   └── eval_config.json    # the three metrics and thresholds
├── tests/
│   ├── unit/test_unit.py               # 12 deterministic tests (no LLM)
│   └── integration/
│       ├── test_integration.py         # live agent + ADK AgentEvaluator
│       └── fixtures/smoke.test.json, test_config.json
├── run_evaluation.py       # runs `adk eval` for baseline/revised, saves results
├── make_reports.py         # builds the Markdown reports from ADK result files
├── reports/                # generated reports + raw ADK result JSON
├── pytest.ini
└── requirements.txt
```

## Setup and run

You need a Google Cloud project with Vertex AI enabled; the SAFETY metric requires it.

```powershell
cd challenge-4-evaluation
uv venv --python 3.12 .venv; .venv\Scripts\activate
pip install -r requirements.txt
gcloud auth application-default login
copy customer_service_agent\.env.example customer_service_agent\.env   # set GOOGLE_CLOUD_PROJECT

python run_evaluation.py both      # runs `adk eval` for both prompts, then builds the reports
pytest tests/unit -v               # unit tests (no LLM)
$env:RUN_INTEGRATION="1"; pytest tests/integration -v   # integration tests (live model)
```

You can also run a single evaluation directly with the ADK CLI:

```powershell
$env:PROMPT_VERSION="revised"; $env:PYTHONPATH="."
adk eval customer_service_agent eval\customer_service.evalset.json --config_file_path eval\eval_config.json --print_detailed_results
```

To chat with the agent, run `adk web` and select `customer_service_agent`.
