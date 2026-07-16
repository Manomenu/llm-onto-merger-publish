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


def extract(dataset: str, metric: str) -> dict[str, str]:
    csv_path = SCENARIO_OUT / dataset / f"m_i_raport_{dataset}.csv"
    if not csv_path.exists():
        sys.exit(f"missing: {csv_path}")
    row_values: dict[str, str] = {}
    with csv_path.open() as fh:
        lines = [ln for ln in fh if not ln.lstrip().lstrip('"').startswith('#')]
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
    args = parser.parse_args()

    with args.output.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["dataset", *METHOD_ORDER])
        for ds in args.datasets:
            vals = extract(ds, args.metric)
            writer.writerow([ds, *(vals.get(m, "") for m in METHOD_ORDER)])

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
