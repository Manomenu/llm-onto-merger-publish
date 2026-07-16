#!/usr/bin/env python3
"""Horizontal merge of aggregator outputs (rows = methods, cols = metrics).

All inputs must share the same method order in column 0.
Output columns = union of all metric columns from inputs.
"""

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    header: list[str] = ["method"]
    method_order: list[str] = []
    rows_by_method: dict[str, list[str]] = {}

    for i, path in enumerate(args.input):
        with path.open() as fh:
            # Skip '#'-prefixed comment lines (e.g. the CoMerger-timeout NOTE
            # combine_turns.py prepends) so they are never mistaken for the
            # header — matches plot_turns.py / extract_metric.py behaviour.
            rows = [r for r in csv.reader(fh)
                    if r and not r[0].lstrip().startswith("#")]
            h = rows[0]
            metrics = h[1:]
            header.extend(metrics)
            for row in rows[1:]:
                m = row[0]
                if m not in rows_by_method:
                    rows_by_method[m] = []
                    method_order.append(m)
                rows_by_method[m].extend(row[1:])

    with args.output.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for m in method_order:
            w.writerow([m, *rows_by_method[m]])

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
