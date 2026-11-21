"""Runs the ADK evaluation for one or both prompt versions and saves the results.

Usage (from the challenge-4-evaluation folder):
    python run_evaluation.py baseline        # full run for one prompt version
    python run_evaluation.py revised
    python run_evaluation.py both
    python run_evaluation.py fill baseline   # re-run only cases with missing metric scores
                                             # (e.g. after rate-limit errors) and merge them in

Each run calls `adk eval` (ADK's Agent Evaluation CLI) with eval/eval_config.json on
eval/customer_service.evalset.json, copies the result file ADK writes to
customer_service_agent/.adk/eval_history/ into reports/results_<version>.json, and then
regenerates the Markdown reports (make_reports.py).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
HISTORY = ROOT / "customer_service_agent" / ".adk" / "eval_history"
REPORTS = ROOT / "reports"
EVALSET = "eval/customer_service.evalset.json"
ADK = Path(sys.executable).parent / ("adk.exe" if os.name == "nt" else "adk")
QUALITY_METRICS = ("rubric_based_final_response_quality_v1", "safety_v1", "policy_grounded_factuality")


def _adk_eval(version: str, case_ids: list[str] | None = None) -> Path:
    """Runs `adk eval` and returns the path of the result file it wrote."""
    REPORTS.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PROMPT_VERSION": version,
        "PYTHONWARNINGS": "ignore",
        "PYTHONIOENCODING": "utf-8",
        # lets ADK import the custom metric (customer_service_agent.metrics) from this folder
        "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    target = EVALSET + (":" + ",".join(case_ids) if case_ids else "")
    started = time.time()
    log_name = f"raw_{version}_{'fill' if case_ids else 'run'}.log"
    with open(REPORTS / log_name, "w", encoding="utf-8") as log:
        proc = subprocess.run(
            [str(ADK), "eval", "customer_service_agent", target,
             "--config_file_path", "eval/eval_config.json",
             # fewer concurrent cases keeps lab projects under their Vertex AI rate limits
             "--parallelism", os.getenv("EVAL_PARALLELISM", "1")],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, text=True,
        )
    # `adk eval` exits non-zero when any case fails; that is expected for a baseline.
    newest = max(HISTORY.glob("*.evalset_result.json"), key=lambda p: p.stat().st_mtime, default=None)
    if newest is None or newest.stat().st_mtime < started:
        sys.exit(f"No new result file found (exit code {proc.returncode}); see reports/{log_name}")
    print(f"  adk eval finished in {time.time() - started:.0f}s")
    return newest


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.loads(data) if isinstance(data, str) else data


def _missing_cases(results: dict) -> list[str]:
    missing = []
    for r in results["eval_case_results"]:
        scores = {m["metric_name"]: m.get("score") for m in r.get("overall_eval_metric_results") or []}
        if any(scores.get(k) is None for k in QUALITY_METRICS):
            missing.append(r["eval_id"])
    return missing


def run(version: str) -> None:
    print(f"\n=== Evaluating prompt version: {version} ===", flush=True)
    (REPORTS / f"factuality_details_{version}.jsonl").unlink(missing_ok=True)
    shutil.copy(_adk_eval(version), REPORTS / f"results_{version}.json")
    print(f"  saved reports/results_{version}.json")


def fill(version: str) -> None:
    path = REPORTS / f"results_{version}.json"
    results = _read(path)
    missing = _missing_cases(results)
    print(f"\n=== Filling gaps for {version}: {missing or 'none'} ===", flush=True)
    if not missing:
        return
    new = _read(_adk_eval(version, missing))
    replacements = {r["eval_id"]: r for r in new["eval_case_results"]}
    results["eval_case_results"] = [replacements.get(r["eval_id"], r) for r in results["eval_case_results"]]
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"  merged {len(replacements)} re-run case(s); still missing: {_missing_cases(results) or 'none'}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["both"]
    if args[0] == "fill":
        for v in (args[1:] or ["baseline", "revised"]):
            fill(v)
    else:
        for v in (["baseline", "revised"] if args[0] == "both" else [args[0]]):
            run(v)
    subprocess.run([sys.executable, str(ROOT / "make_reports.py")], cwd=ROOT, check=False)
