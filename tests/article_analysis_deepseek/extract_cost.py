#!/usr/bin/env python3
"""Extract per-dataset LLM cost for one turn from s5 (AML-input) run dirs.

Reads cost_stats.json written by src/llm_onto_merger/merger.py (via
CostTracker.to_json_dict()) from each dataset's s5 run directory and writes
one row per dataset: dataset, total_cost_usd, call_count, input_tokens_total,
output_tokens_total. The token totals are summed from the per_call entries
(each has input_tokens/output_tokens), so per-call costs remain reconstructable
post-hoc even though only the totals are carried forward into this table.

Only the s5 (AML-input) run is read — s6 (reference-input) runs are excluded
per the author's decision (the caller only ever points --s5-root at .../s5).

A dataset whose cost_stats.json is missing or unreadable gets a blank row and
a warning — the same NaN-skip convention combine_turns.py/plot_grouped.py use
elsewhere in this folder (blank cells are ignored downstream when averaging).
"""

import argparse
import csv
import json
import sys
from pathlib import Path

_FIELDS = ["total_cost_usd", "call_count", "input_tokens_total", "output_tokens_total"]


def _read_cost(run_dir: Path) -> dict | None:
    path = run_dir / "cost_stats.json"
    if not path.exists():
        print(f"  WARNING: missing {path} — dataset row will be NaN", file=sys.stderr)
        return None
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        print(f"  WARNING: could not parse {path} ({exc.__class__.__name__}: {exc}) "
              "— dataset row will be NaN", file=sys.stderr)
        return None
    per_call = data.get("per_call") or []
    input_tokens_total = sum(c.get("input_tokens", 0) or 0 for c in per_call)
    output_tokens_total = sum(c.get("output_tokens", 0) or 0 for c in per_call)
    return {
        "total_cost_usd": data.get("total_cost_usd", 0.0) or 0.0,
        "call_count": data.get("call_count", 0) or 0,
        "input_tokens_total": input_tokens_total,
        "output_tokens_total": output_tokens_total,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--s5-root", required=True, type=Path,
                    help="turn's s5 output root, e.g. outputs/<turn>/s5")
    ap.add_argument("--tag", required=True,
                    help="output-dir tag as computed by s5.sh, e.g. "
                         "aml_15000c_p1000_deepseek_deepseek-v4-flash")
    ap.add_argument("--datasets", nargs="+", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", *_FIELDS])
        for ds in args.datasets:
            run_dir = args.s5_root / ds / f"{ds}_{args.tag}"
            row = _read_cost(run_dir)
            if row is None:
                w.writerow([ds, "", "", "", ""])
            else:
                w.writerow([ds, *(row[f] for f in _FIELDS)])

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
