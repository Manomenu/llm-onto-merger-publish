#!/usr/bin/env python3
"""Per-turn LLM error/fallback rate for the article repeated-runs analyses.

Unlike tests/analiza*/errors/error_rate.py — which reads only the LAST run of
each dataset from the global logs/app.log — this script recovers the error
rate of EVERY article turn from the per-run `run.log` files that each run dir
already contains.  It never invokes any merging or measure computation: it is
pure log parsing, safe to run at any time.

A "failed" environment fails in one of these modes (same taxonomy as
tests/analiza/errors/error_rate.py):
    parse_fail   'LLM response could not be parsed'  (WARNING → deterministic
                 fallback merge of the seed correspondence)
    empty_graph  'LLM returned EMPTY merged graph'   (ERROR)
    other_error  any other '| ERROR ' line tagged with 'env N:'

An EMPTY graph with `env N audit | input=0` is a DEGENERATE environment
(leaf/peripheral pair with no interior structure — the LLM correctly returns
nothing), not a real failure:

    real_failures   = failed envs EXCLUDING empty-graph-with-input=0
    real_error_rate = real_failures / total_environments

Run-dir resolution mirrors the corresponding analyze-all.sh:

  --layout gptoss   (scenarios s2=aml, s3=ref), per turn × dataset:
      1. tests/scenarios/outputs/<turn>/<ds>-s2/<ds>-s2_aml_15k_p24/run.log
         (the analiza-variance tree; turn1 entries are symlinks to the
          original non-turn run dirs)
      2. tests/article_scenarios/outputs/<turn>/s2/<ds>/<ds>_aml_15k_p24/run.log
  --layout deepseek (scenarios s5=aml, s6=ref), per turn × dataset:
      tests/article_scenarios/outputs/<turn>/s5/<ds>/
          <ds>_aml_15000c_p1000_deepseek_deepseek-v4-flash/run.log

Outputs:
  --out-csv      one row per (scenario, dataset, turn)
  --out-summary  one row per (scenario, dataset): median [min; max] across turns

Usage (from either side's errors/ dir):
    uv run python3 ../../article_analysis_deepseek/error_rate_turns.py \\
        --layout gptoss --model gpt-oss-20b \\
        --turn turn1 --turn turn2 --turn turn3 --turn turn4 --turn turn5 \\
        --dataset confOf-ekaw --dataset human-mouse --dataset swo-acm \\
        --out-csv errors.csv --out-summary errors_summary.csv
"""

import argparse
import csv
import re
import statistics
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent  # tests/

ARGS_RE = re.compile(r"Arguments loaded ")
MERGING_RE = re.compile(r"Merging\s+(\d+)\s+environments")
AUDIT_RE = re.compile(r"env\s+(\d+)\s+audit\s+\|\s+input=(\d+)")
ENV_ID_RE = re.compile(r"env\s+(\d+):")
PARSE_FAIL = "could not be parsed"
EMPTY_GRAPH = "LLM returned EMPTY merged graph"

# scenario -> list of run.log path templates, tried in order ({t}=turn, {d}=dataset)
LAYOUTS = {
    "gptoss": {
        "s2": [
            "scenarios/outputs/{t}/{d}-s2/{d}-s2_aml_15k_p24/run.log",
            "article_scenarios/outputs/{t}/s2/{d}/{d}_aml_15k_p24/run.log",
        ],
        "s3": [
            "scenarios/outputs/{t}/{d}-s3/{d}-s3_ref_15k_p24/run.log",
            "article_scenarios/outputs/{t}/s3/{d}/{d}_ref_15k_p24/run.log",
        ],
    },
    "deepseek": {
        "s5": [
            "article_scenarios/outputs/{t}/s5/{d}/"
            "{d}_aml_15000c_p1000_deepseek_deepseek-v4-flash/run.log",
        ],
        "s6": [
            "article_scenarios/outputs/{t}/s6/{d}/"
            "{d}_ref_15000c_p1000_deepseek_deepseek-v4-flash/run.log",
        ],
    },
}
SCENARIO_INPUT = {"s2": "aml", "s3": "ref", "s5": "aml", "s6": "ref"}


def resolve_log(layout: str, scenario: str, turn: str, dataset: str) -> Path | None:
    for tpl in LAYOUTS[layout][scenario]:
        p = TESTS_ROOT / tpl.format(t=turn, d=dataset)
        if p.is_file():
            return p
    return None


def parse_run_log(log_path: Path) -> dict:
    """Parse a single-run run.log; if the file holds several runs (re-executed
    dir), keep the LAST one, matching error_rate.py's last-run semantics."""
    cur = None
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if ARGS_RE.search(line):
                cur = {"total": None, "env_input": {},
                       "parse_ids": set(), "empty_ids": set(), "error_ids": set()}
                continue
            if cur is None:
                continue
            mm = MERGING_RE.search(line)
            if mm:
                cur["total"] = int(mm.group(1))
                continue
            am = AUDIT_RE.search(line)
            if am:
                cur["env_input"][am.group(1)] = int(am.group(2))
                continue
            idm = ENV_ID_RE.search(line)
            env_id = idm.group(1) if idm else None
            if EMPTY_GRAPH in line:
                if env_id:
                    cur["empty_ids"].add(env_id)
            elif PARSE_FAIL in line:
                if env_id:
                    cur["parse_ids"].add(env_id)
            elif "| ERROR " in line and env_id:
                cur["error_ids"].add(env_id)
    return cur or {"total": None, "env_input": {},
                   "parse_ids": set(), "empty_ids": set(), "error_ids": set()}


def classify(info: dict) -> dict:
    total = info["total"]
    degenerate = {i for i in info["empty_ids"] if info["env_input"].get(i, 1) == 0}
    failed = info["parse_ids"] | info["empty_ids"] | info["error_ids"]
    real_failed = failed - degenerate
    rate = round(100.0 * len(real_failed) / total, 2) if total else None
    return {
        "total_environments": total or 0,
        "real_failures": len(real_failed),
        "degenerate_empty_input": len(degenerate),
        "parse_fail": len(info["parse_ids"]),
        "empty_graph_total": len(info["empty_ids"]),
        "other_error": len(info["error_ids"] - info["empty_ids"]),
        "real_error_rate_pct": rate,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layout", required=True, choices=sorted(LAYOUTS))
    ap.add_argument("--model", required=True, help="model label written to the CSVs")
    ap.add_argument("--turn", action="append", required=True)
    ap.add_argument("--dataset", action="append", required=True)
    ap.add_argument("--scenario", action="append", default=None,
                    help="subset of the layout's scenarios (default: all)")
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument("--out-summary", type=Path, default=None)
    args = ap.parse_args()

    scenarios = args.scenario or sorted(LAYOUTS[args.layout])
    for s in scenarios:
        if s not in LAYOUTS[args.layout]:
            sys.exit(f"scenario '{s}' not defined for layout '{args.layout}'")

    rows: list[dict] = []
    found = 0
    for scen in scenarios:
        for ds in args.dataset:
            for turn in args.turn:
                log = resolve_log(args.layout, scen, turn, ds)
                base = {"model": args.model, "scenario": scen,
                        "input": SCENARIO_INPUT[scen], "dataset": ds, "turn": turn}
                if log is None:
                    print(f"  WARNING: no run.log for {scen}/{ds}/{turn} — skipped")
                    rows.append({**base, "source_log": "",
                                 "total_environments": "", "real_failures": "",
                                 "degenerate_empty_input": "", "parse_fail": "",
                                 "empty_graph_total": "", "other_error": "",
                                 "real_error_rate_pct": ""})
                    continue
                c = classify(parse_run_log(log))
                found += 1
                rows.append({**base,
                             "source_log": str(log.relative_to(TESTS_ROOT)), **c})
                print(f"  [{scen}/{ds}/{turn}] {c['real_failures']}/{c['total_environments']} "
                      f"real failures → {c['real_error_rate_pct']}% "
                      f"(parse={c['parse_fail']} empty={c['empty_graph_total']} "
                      f"other={c['other_error']} degenerate={c['degenerate_empty_input']})")

    fieldnames = ["model", "scenario", "input", "dataset", "turn", "source_log",
                  "total_environments", "real_failures", "degenerate_empty_input",
                  "parse_fail", "empty_graph_total", "other_error",
                  "real_error_rate_pct"]
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {args.out_csv}")

    if args.out_summary is not None:
        srows = []
        for scen in scenarios:
            for ds in args.dataset:
                sub = [r for r in rows
                       if r["scenario"] == scen and r["dataset"] == ds
                       and r["source_log"]]
                if not sub:
                    continue
                fails = [r["real_failures"] for r in sub]
                rates = [r["real_error_rate_pct"] for r in sub
                         if r["real_error_rate_pct"] is not None]
                srows.append({
                    "model": args.model, "scenario": scen,
                    "input": SCENARIO_INPUT[scen], "dataset": ds,
                    "turns_found": len(sub),
                    "total_environments_median":
                        int(statistics.median(r["total_environments"] for r in sub)),
                    "real_failures_median": statistics.median(fails),
                    "real_failures_min": min(fails),
                    "real_failures_max": max(fails),
                    "real_error_rate_pct_median":
                        round(statistics.median(rates), 2) if rates else "",
                    "real_error_rate_pct_min": min(rates) if rates else "",
                    "real_error_rate_pct_max": max(rates) if rates else "",
                })
        sfields = ["model", "scenario", "input", "dataset", "turns_found",
                   "total_environments_median", "real_failures_median",
                   "real_failures_min", "real_failures_max",
                   "real_error_rate_pct_median", "real_error_rate_pct_min",
                   "real_error_rate_pct_max"]
        with args.out_summary.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=sfields)
            w.writeheader()
            w.writerows(srows)
        print(f"  wrote {args.out_summary}")

    if found == 0:
        sys.exit("ERROR: no run.log resolved for any scenario/dataset/turn")


if __name__ == "__main__":
    main()
