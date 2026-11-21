"""Prints per-case metric scores from an ADK eval result file.

Usage:  python ads_eval/show_results.py reports/eval_results_rerun.json
"""

import json
import sys

STATUS = {1: "PASSED", 2: "FAILED", 3: "NOT_EVALUATED", 4: "INFO"}
METRICS = ["routing_accuracy", "ads_grounded_factuality", "rubric_based_final_response_quality_v1", "safety_v1"]

data = json.loads(open(sys.argv[1], encoding="utf-8").read())
data = json.loads(data) if isinstance(data, str) else data
for r in data["eval_case_results"]:
    m = {x["metric_name"]: x for x in r["overall_eval_metric_results"]}
    cells = []
    for k in METRICS:
        x = m.get(k, {})
        score = "n/a" if x.get("score") is None else f"{x['score']:.2f}"
        cells.append(f"{k.split('_')[0]}={score} ({STATUS.get(x.get('eval_status'), '-')})")
    print(f"{r['eval_id']:30} " + "  ".join(cells))
