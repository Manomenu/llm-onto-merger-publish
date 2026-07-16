#!/usr/bin/env python3
"""LLM error-rate per dataset, read from logs/app.log.

For each requested dataset we locate its LAST run (runs delimited by
'Arguments loaded ... base: tests/inputs/<dataset>/...') and classify each
environment's outcome.

A "failed" environment fails in one of these modes:
    parse_fail   'LLM response could not be parsed'   (WARNING → fallback merge)
    empty_graph  'LLM returned EMPTY merged graph'     (ERROR)
    other_error  any other '| ERROR ' line tagged with 'env N:'

CRUCIAL distinction — an EMPTY graph is NOT a real failure when the environment
had no content to merge in the first place.  The per-env audit line
    'env N audit | input=K ...'
gives K = number of URI–URI input triples.  An EMPTY graph with input=0 is a
DEGENERATE environment (leaf/peripheral pair with no interior structure — the LLM
correctly returns nothing), not a merge failure.  We therefore report:

    real_failures        = failed envs EXCLUDING empty-graph-with-input=0
    degenerate_empty     = empty-graph envs with input=0 (not real failures)
    real_error_rate      = real_failures / total_environments

Usage:
    uv run python error_rate.py --log ../../../logs/app.log \\
        --dataset conference --dataset human-mouse \\
        --out-csv error_rate.csv --out-jpg error_rate.jpg
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ARGS_RE = re.compile(r"Arguments loaded .* base:\s*(\S+)")
INPUT_RE = re.compile(r"tests/inputs/([^/]+)/")
MERGING_RE = re.compile(r"Merging\s+(\d+)\s+environments")
AUDIT_RE = re.compile(r"env\s+(\d+)\s+audit\s+\|\s+input=(\d+)")
ENV_ID_RE = re.compile(r"env\s+(\d+):")
PARSE_FAIL = "could not be parsed"
EMPTY_GRAPH = "LLM returned EMPTY merged graph"


def parse_log(log_path: Path) -> dict[str, dict]:
    """Return {dataset: run_info} for the LAST run of each dataset."""
    last: dict[str, dict] = {}
    cur_ds: str | None = None
    cur: dict | None = None

    def flush() -> None:
        if cur_ds is not None and cur is not None:
            last[cur_ds] = cur

    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = ARGS_RE.search(line)
            if m:
                flush()
                im = INPUT_RE.search(m.group(1))
                cur_ds = im.group(1) if im else None
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
    flush()
    return last


def classify(info: dict) -> dict:
    total = info["total"]
    empty_ids = info["empty_ids"]
    parse_ids = info["parse_ids"]
    error_ids = info["error_ids"]
    env_input = info["env_input"]

    # Degenerate: empty graph whose env had zero URI–URI input triples.
    degenerate = {i for i in empty_ids if env_input.get(i, 1) == 0}
    failed = parse_ids | empty_ids | error_ids
    real_failed = failed - degenerate
    rate = round(100.0 * len(real_failed) / total, 2) if total else None
    return {
        "total_environments": total or 0,
        "real_failures": len(real_failed),
        "degenerate_empty_input": len(degenerate),
        "parse_fail": len(parse_ids),
        "empty_graph_total": len(empty_ids),
        "other_error": len(error_ids - empty_ids),
        "real_error_rate_pct": rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--dataset", action="append", required=True)
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-jpg", type=Path, required=True)
    args = parser.parse_args()

    if not args.log.exists():
        sys.exit(f"log not found: {args.log}")
    runs = parse_log(args.log)

    rows: list[dict] = []
    for ds in args.dataset:
        info = runs.get(ds)
        if info is None:
            print(f"  WARNING: no run found for '{ds}' in {args.log}")
            rows.append({"dataset": ds, "total_environments": 0, "real_failures": 0,
                         "degenerate_empty_input": 0, "parse_fail": 0,
                         "empty_graph_total": 0, "other_error": 0,
                         "real_error_rate_pct": None})
            continue
        c = classify(info)
        rows.append({"dataset": ds, **c})
        print(f"  [{ds}] {c['real_failures']}/{c['total_environments']} REAL failures "
              f"→ {c['real_error_rate_pct']}% | "
              f"degenerate empty-input envs (not failures): {c['degenerate_empty_input']} "
              f"| empty_total={c['empty_graph_total']} parse={c['parse_fail']} "
              f"other_error={c['other_error']}")

    fieldnames = ["dataset", "total_environments", "real_failures",
                  "degenerate_empty_input", "parse_fail", "empty_graph_total",
                  "other_error", "real_error_rate_pct"]
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {args.out_csv}")

    # ── chart: real error rate (degenerate envs annotated separately) ────────
    labels = [r["dataset"] for r in rows]
    rates = [r["real_error_rate_pct"] or 0 for r in rows]
    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(labels, rates, color="#c0392b")
    ax.set_title("LLM merge REAL error rate per dataset (last run)\n"
                 "real failures / total envs — empty-input envs excluded")
    ax.set_ylabel("real error rate [%]")
    ax.bar_label(bars, labels=[
        ("n/a" if r["real_error_rate_pct"] is None
         else f"{r['real_error_rate_pct']}%\n({r['real_failures']}/{r['total_environments']})\n"
              f"+{r['degenerate_empty_input']} empty-input")
        for r in rows], padding=3)
    ax.margins(y=0.25)
    fig.tight_layout()
    fig.savefig(args.out_jpg, dpi=150)
    print(f"  wrote {args.out_jpg}")


if __name__ == "__main__":
    main()
