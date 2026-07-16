#!/usr/bin/env python3
"""Aggregate per-metric raw CSVs into a single %-change table vs Naive Union.

Input: one raw CSV per metric (rows = datasets, cols = methods incl. Naive Union).
Output: one CSV with rows = methods (excluding Naive Union), cols = metrics,
values = avg %-change vs Naive Union across datasets.

Per-dataset %-change formula: (method_value - naive_union_value) / naive_union_value * 100.
"""

import argparse
import csv
from pathlib import Path

def read_raw(path: Path) -> tuple[list[str], dict[str, dict[str, float]]]:
    with path.open() as fh:
        reader = csv.reader(fh)
        header = next(reader)
        methods = header[1:]
        data: dict[str, dict[str, float]] = {}
        for row in reader:
            ds = row[0]
            data[ds] = {m: float(v) if v else float("nan") for m, v in zip(methods, row[1:])}
    return methods, data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metric",
        action="append",
        required=True,
        nargs=2,
        metavar=("NAME", "CSV"),
        help="metric label + path to raw CSV (repeatable)",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="dataset name to skip in averaging (repeatable)",
    )
    parser.add_argument(
        "--baseline",
        default="Naive Union",
        help="method to use as baseline for %% change (default: Naive Union)",
    )
    parser.add_argument(
        "--exclude-method",
        action="append",
        default=[],
        help="method name to skip in output rows (repeatable)",
    )
    args = parser.parse_args()
    baseline = args.baseline
    exclude_methods = set(args.exclude_method)

    metric_names = [m for m, _ in args.metric]
    exclude = set(args.exclude)
    # method order from first input
    methods_first, _ = read_raw(Path(args.metric[0][1]))
    methods = [m for m in methods_first if m not in exclude_methods]

    pct_avg: dict[str, dict[str, float]] = {m: {} for m in methods}

    for metric_label, csv_path in args.metric:
        _, raw = read_raw(Path(csv_path))
        for method in methods:
            pcts: list[float] = []
            for ds, vals in raw.items():
                if ds in exclude:
                    continue
                bv = vals.get(baseline, float("nan"))
                mv = vals.get(method, float("nan"))
                if bv and bv == bv and mv == mv:
                    pcts.append((mv - bv) / bv * 100.0)
            pct_avg[method][metric_label] = sum(pcts) / len(pcts) if pcts else float("nan")

    with args.output.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["method", *metric_names])
        for method in methods:
            row = [method]
            for m in metric_names:
                v = pct_avg[method][m]
                row.append(f"{v:.2f}" if v == v else "")
            writer.writerow(row)

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
