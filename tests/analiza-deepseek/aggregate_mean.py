#!/usr/bin/env python3
"""Mean per-method across datasets — for already-normalised metrics
(no baseline comparison, just average the raw values).

Input format identical to aggregate_pct.py inputs.  Output format identical
to its output, so plot_pct.py can render it the same way.
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
    parser.add_argument("--metric", action="append", required=True, nargs=2, metavar=("NAME", "CSV"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--exclude-method", action="append", default=[])
    args = parser.parse_args()

    exclude_ds = set(args.exclude)
    exclude_methods = set(args.exclude_method)

    methods_first, _ = read_raw(Path(args.metric[0][1]))
    methods = [m for m in methods_first if m not in exclude_methods]

    means: dict[str, dict[str, float]] = {m: {} for m in methods}
    metric_names = [m for m, _ in args.metric]
    for label, csv_path in args.metric:
        _, raw = read_raw(Path(csv_path))
        for method in methods:
            vals = [
                v[method] for ds, v in raw.items()
                if ds not in exclude_ds and v.get(method, float("nan")) == v.get(method, float("nan"))
            ]
            means[method][label] = sum(vals) / len(vals) if vals else float("nan")

    with args.output.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["method", *metric_names])
        for m in methods:
            row = [m] + [f"{means[m][lab]:.4f}" if means[m][lab] == means[m][lab] else "" for lab in metric_names]
            w.writerow(row)

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
