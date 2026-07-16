#!/usr/bin/env python3
"""Adapt one turn's oaei_rejection.py long-format CSV into the aggregate-style
per-dataset table (rows = method, cols = metric) that combine_turns.py /
plot_grouped.py expect — the same _grouped house style used by every other
grouped dimension (e.g. NCRC/NIRC in knowledge_completeness).

Input (oaei_rejection.py / merge_oaei_runs.py output, all datasets/methods):
    method,dataset,reference_total,aml_total,rejected_correct,accepted_aml_fp
Output (restricted to --dataset):
    method,Rejected Correct,Accepted AML FP
    AROM,0,1
    ...

"Proposed" (oaei_rejection.py's own label for the gpt-oss-only run) is renamed
to "Our Solution" to match extract_metric.py's GRAPH_TO_METHOD convention used
by every other dimension; "Proposed: gpt-oss" / "Proposed: deepseek-v4-flash"
(merge_oaei_runs.py's combined-run labels, article_analysis_deepseek only) are
already final display labels and pass through unchanged.

reference_total / aml_total are deterministic given the dataset (same value
every turn) — not real per-turn "metrics", so they are NOT emitted as CSV
columns (that would draw a flat, uninformative subplot for a constant).
Instead, if --totals-output is given, a single '# NOTE: ...' comment line
documenting them is written there for the caller to prepend to the final pm
CSV (combine_turns.py already prepends a similar '# NOTE:' comment for the
CoMerger-timeout case, so this mirrors an existing convention).

If --input does not exist (that turn had no OAEI data at all), or has no rows
for --dataset, an empty (header-only) output is written — combine_turns.py's
NaN-skip already treats a missing per-turn cell as "no data for that turn",
so a partial turn does not drop the dataset's other turns.
"""

import argparse
import csv
import sys
from pathlib import Path

_MEASURES = [("rejected_correct", "Rejected Correct"), ("accepted_aml_fp", "Accepted AML FP")]
_METHOD_ORDER = ["AROM", "CoMerger", "Boomer", "Proposed",
                 "Proposed: gpt-oss", "Proposed: deepseek-v4-flash"]
_RENAME = {"Proposed": "Our Solution"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path,
                    help="per-turn oaei_rejection.py / merge_oaei_runs.py CSV")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--totals-output", type=Path, default=None,
                    help="optional path for a '# NOTE: reference_total=…' comment line")
    args = ap.parse_args()

    by_method: dict[str, dict[str, str]] = {}
    if args.input.exists():
        with args.input.open() as fh:
            for row in csv.DictReader(fh):
                if row.get("dataset") == args.dataset:
                    by_method[row["method"]] = row
    else:
        print(f"  WARNING: {args.input} missing — no OAEI data for '{args.dataset}' this turn.",
              file=sys.stderr)

    methods = [m for m in _METHOD_ORDER if m in by_method] + \
              [m for m in by_method if m not in _METHOD_ORDER]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["method", *(label for _, label in _MEASURES)])
        for m in methods:
            row = by_method[m]
            w.writerow([_RENAME.get(m, m),
                        *(row.get(key, "") for key, _ in _MEASURES)])
    print(f"wrote {args.output}")

    if args.totals_output is not None and by_method:
        first = next(iter(by_method.values()))
        ref, aml = first.get("reference_total", ""), first.get("aml_total", "")
        args.totals_output.write_text(
            f"# NOTE: {args.dataset} reference_total={ref}, aml_total={aml} "
            f"(deterministic given the input ontologies; same across turns/methods)\n"
        )


if __name__ == "__main__":
    main()
