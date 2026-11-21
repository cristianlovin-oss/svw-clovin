"""Builds reports/storm_response_eval_report.md from the ADK eval result file.

Usage:  python ads_eval/make_report.py
Inputs: reports/eval_results.json (copied from ads_agent/.adk/eval_history after `adk eval`),
        reports/factuality_details.jsonl (judge rationales), ads_eval/storm_response.evalset.json
"""

import json
import statistics
import sys
from pathlib import Path

from google.adk.evaluation.eval_case import Invocation
from google.adk.evaluation.eval_metrics import EvalMetric

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ads_eval.metrics import SPECIALISTS, _tool_names, routing_accuracy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
METRICS = [
    ("routing_accuracy", "Routing"),
    ("ads_grounded_factuality", "Factuality"),
    ("rubric_based_final_response_quality_v1", "Quality"),
    ("safety_v1", "Safety"),
]
STATUS = {1: "PASSED", 2: "FAILED", 3: "NOT_EVALUATED", 4: "INFORMATIONAL"}


def text(content):
    return "".join(p.get("text") or "" for p in (content or {}).get("parts") or [])


def main():
    data = json.loads((REPORTS / "eval_results.json").read_text(encoding="utf-8"))
    data = json.loads(data) if isinstance(data, str) else data
    evalset = json.loads((ROOT / "ads_eval" / "storm_response.evalset.json").read_text(encoding="utf-8"))
    meta = {c["eval_id"]: c for c in evalset["eval_cases"]}
    judge = {}
    if (REPORTS / "factuality_details.jsonl").exists():
        for line in (REPORTS / "factuality_details.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                judge[row["question"]] = row

    rows = []
    for r in data["eval_case_results"]:
        m = {x["metric_name"]: x for x in r["overall_eval_metric_results"]}
        case = meta[r["eval_id"]]
        q = text(case["conversation"][0]["user_content"])
        per = r.get("eval_metric_result_per_invocation") or [{}]
        inv = per[0].get("actual_invocation") or {}
        actual = Invocation.model_validate(inv) if inv else None
        expected_inv = Invocation.model_validate(per[0]["expected_invocation"]) if per[0].get("expected_invocation") else None
        tools = [n for n in _tool_names(actual) if n in SPECIALISTS] if actual else []
        statuses = {k: STATUS.get(m.get(k, {}).get("eval_status"), "n/a") for k, _ in METRICS}
        # Re-score routing from the stored invocations with the fixed metric (the run used a version that
        # could not read ADK 2.x invocation events). Deterministic, so no model calls are needed.
        if actual and expected_inv:
            rescored = routing_accuracy(EvalMetric(metric_name="routing_accuracy", threshold=1.0), [actual], [expected_inv])
            status = rescored.overall_eval_status.value
            m["routing_accuracy"] = {"score": rescored.overall_score, "eval_status": status}
            statuses["routing_accuracy"] = STATUS.get(status)
        failed = [label for k, label in METRICS if statuses[k] == "FAILED"]
        is_live = text(case["conversation"][0]["final_response"]).startswith("[LIVE]")
        # A missing score is legitimate only for factuality on [LIVE] cases; anything else was not
        # scored (lab rate limits) and makes the case INCOMPLETE rather than passed.
        missing = [label for k, label in METRICS
                   if m.get(k, {}).get("score") is None and not (k == "ads_grounded_factuality" and is_live)]
        result = "FAIL" if failed else ("INCOMPLETE" if missing else "PASS")
        rows.append({
            "id": r["eval_id"], "category": case["session_input"]["state"]["category"], "question": q,
            "scores": {k: m.get(k, {}).get("score") for k, _ in METRICS}, "statuses": statuses,
            "result": result, "failed": failed, "missing": missing,
            "expected": [t["name"] for t in case["conversation"][0]["intermediate_data"]["tool_uses"]],
            "called": tools, "answer": text(inv.get("final_response")),
            "tokens": (m.get("token_usage_v1") or {}).get("score"),
            "seconds": (m.get("invocation_duration_v1") or {}).get("score"),
            "judge": judge.get(q, {}),
        })

    def f(v):
        return "n/a" if v is None else f"{v:.2f}"

    lines = [
        "# Storm-response evaluation report – ADS Storm Response Assistant",
        "",
        f"Eval set `ads_storm_response` ({len(rows)} cases, Winter Storm Kodiak snapshot) · run with `adk eval` · "
        "config `ads_eval/eval_config.json` · agent model `gemini-3.6-flash`, judge `gemini-2.5-pro`.",
        "",
        f"**Result: {sum(r['result'] == 'PASS' for r in rows)} passed, {sum(r['result'] == 'FAIL' for r in rows)} failed, "
        f"{sum(r['result'] == 'INCOMPLETE' for r in rows)} incomplete (a metric could not be scored because of lab rate limits).**",
        "",
        "## Scores by metric",
        "",
        "| Metric | What it checks | Mean | Passed / scored |",
        "|---|---|---|---|",
    ]
    desc = {
        "routing_accuracy": "Root agent called the expected specialist(s) (custom, deterministic)",
        "ads_grounded_factuality": "Facts match ADS policies + operations records + reference (custom LLM judge; live cases skipped)",
        "rubric_based_final_response_quality_v1": "Direct answer, safety rules, cites sources, actionable (LLM judge)",
        "safety_v1": "Harmlessness (Vertex AI evaluation service)",
    }
    for k, label in METRICS:
        scored = [r["scores"][k] for r in rows if r["scores"][k] is not None]
        passed = sum(r["statuses"][k] == "PASSED" for r in rows)
        lines.append(f"| {label} | {desc[k]} | {f(statistics.mean(scored)) if scored else 'n/a'} | {passed}/{len(scored)} |")
    toks = [r["tokens"] for r in rows if r["tokens"]]
    secs = [r["seconds"] for r in rows if r["seconds"]]
    if toks and secs:
        lines += ["", f"Efficiency (reported by ADK): {statistics.mean(toks):,.0f} tokens and {statistics.mean(secs):.1f} s per answer on average."]

    lines += ["", "## Per-case results", "",
              "| Case | Category | Expected → called | Routing | Factuality | Quality | Safety | Result |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        exp = ", ".join(e.replace("_agent", "") for e in r["expected"]) or "(none)"
        got = ", ".join(c.replace("_agent", "") for c in r["called"]) or "(none)"
        s = r["scores"]
        lines.append(f"| `{r['id']}` | {r['category']} | {exp} → {got} | {f(s['routing_accuracy'])} | "
                     f"{f(s['ads_grounded_factuality']) if r['statuses']['ads_grounded_factuality'] != 'NOT_EVALUATED' else 'live'} | "
                     f"{f(s['rubric_based_final_response_quality_v1'])} | {f(s['safety_v1'])} | {r['result']} |")

    problems = [r for r in rows if r["result"] != "PASS"]
    lines += ["", f"## Analysis of non-passing cases ({len(problems)})", ""]
    for r in problems:
        lines += [f"### `{r['id']}` – {r['result']}", f"- **Question:** {r['question']}"]
        if r["failed"]:
            lines.append(f"- **Failed:** {', '.join(r['failed'])}")
        if r["missing"]:
            lines.append(f"- **Not scored (rate limit):** {', '.join(r['missing'])}")
        lines.append(f"- **Specialists expected / called:** {r['expected'] or '(none)'} / {r['called'] or '(none)'}")
        if r["judge"]:
            lines.append(f"- **Factuality judge ({r['judge'].get('score')}):** {r['judge'].get('reason')}")
            if r["judge"].get("problems"):
                lines.append(f"- **Problems found:** {'; '.join(r['judge']['problems'])}")
        lines.append(f"- **Answer (excerpt):** {r['answer'][:500].replace(chr(10), ' ')}")
        lines.append("")
    (REPORTS / "storm_response_eval_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS / "eval_summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("Wrote reports/storm_response_eval_report.md")
    for r in rows:
        print(f"{r['id']:36} {r['result']:10} " + " ".join(f"{label}={f(r['scores'][k])}" for k, label in METRICS))


if __name__ == "__main__":
    main()
