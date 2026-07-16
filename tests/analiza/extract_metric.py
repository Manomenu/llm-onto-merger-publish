#!/usr/bin/env python3
"""Extract a single metric across datasets × methods into a CSV table.

Reads tests/scenarios/outputs/<dataset>/m_i_raport_<dataset>.csv (section=metrics)
and pivots to: rows = datasets, columns = methods.
"""

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENARIO_OUT = REPO / "tests" / "scenarios" / "outputs"

GRAPH_TO_METHOD = {
    "union_input":         "Naive Union",
    "applied_alignments":  "Applied Alignments",
    "arom_ontology":       "AROM",
    "comerger_ontology":   "CoMerger",
    "boomer_ontology":     "Boomer",
    "merged_ontology":     "Our Solution",
}
METHOD_ORDER = [
    "Naive Union", "Applied Alignments", "AROM",
    "CoMerger", "Boomer", "Our Solution",
]


def extract(
    dataset: str, metric: str, outputs_root: Path = SCENARIO_OUT, skip_missing: bool = False
) -> dict[str, str]:
    csv_path = outputs_root / dataset / f"m_i_raport_{dataset}.csv"
    if not csv_path.exists():
        if skip_missing:
            # A turn's run for this dataset may still be unfinished (e.g. a
            # repeated-run backfill in progress). Warn and return no values
            # instead of aborting the whole extraction — downstream
            # aggregation (aggregate_mean.py / aggregate_pct.py) already
            # treats a missing value as NaN and drops it from that cell's
            # aggregate.
            print(f"  WARNING: missing {csv_path} — '{dataset}' left blank for this turn.", file=sys.stderr)
            return {}
        sys.exit(f"missing: {csv_path}")
    row_values: dict[str, str] = {}
    with csv_path.open() as fh:
        # Comment lines ('#'-prefixed) may or may not be CSV-quoted — e.g. the
        # "# section: ..." banner is written as '"# section: ..."' but the
        # CoMerger-timeout NOTE is written as a bare '# NOTE: ...' line.  A
        # bare comment line that isn't filtered out gets fed to csv.DictReader
        # as the header row, silently misaligning every subsequent row (the
        # real header and all data end up under one bogus column) so every
        # metric lookup below returns nothing for that dataset.
        lines = [ln for ln in fh if not ln.lstrip().lstrip('"').startswith("#")]
    for row in csv.DictReader(lines):
        if row.get("section") != "metrics":
            continue
        if row.get("metric") != metric:
            continue
        method = GRAPH_TO_METHOD.get(row.get("graph", ""))
        if method:
            row_values[method] = row.get("value", "")
    return row_values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--datasets", nargs="+", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--outputs-root", type=Path, default=SCENARIO_OUT,
        help="root under which <dataset>/m_i_raport_<dataset>.csv lives "
             "(default: tests/scenarios/outputs; pass e.g. .../outputs/turn1 "
             "for a labelled repeated run).",
    )
    parser.add_argument(
        "--skip-missing", action="store_true",
        help="if a dataset's m_i_raport CSV is missing, warn and leave that "
             "dataset's row blank instead of aborting (default: fail fast).",
    )
    args = parser.parse_args()

    with args.output.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["dataset", *METHOD_ORDER])
        for ds in args.datasets:
            vals = extract(ds, args.metric, args.outputs_root, skip_missing=args.skip_missing)
            writer.writerow([ds, *(vals.get(m, "") for m in METHOD_ORDER)])

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
