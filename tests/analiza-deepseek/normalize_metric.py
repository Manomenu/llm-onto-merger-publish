#!/usr/bin/env python3
"""Per-cell ratio of two raw metric CSVs (numerator / denominator).

Both inputs must have the same shape (rows = datasets, cols = methods).
Cells where denominator is 0 or empty are written as empty.
"""

import argparse
import csv
from pathlib import Path


def read(path: Path) -> tuple[list[str], list[str], list[list[str]]]:
    with path.open() as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    datasets = [r[0] for r in rows[1:]]
    body = [r[1:] for r in rows[1:]]
    return header, datasets, body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--numerator", required=True, type=Path)
    parser.add_argument("--denominator", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    h1, ds1, n = read(args.numerator)
    h2, ds2, d = read(args.denominator)
    assert h1 == h2 and ds1 == ds2, "shape mismatch"

    with args.output.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(h1)
        for ds, n_row, d_row in zip(ds1, n, d):
            out: list[str] = [ds]
            for nv, dv in zip(n_row, d_row):
                try:
                    fn = float(nv) if nv else None
                    fd = float(dv) if dv else None
                except ValueError:
                    fn = fd = None
                if fn is None or fd is None or fd == 0:
                    out.append("")
                else:
                    out.append(f"{fn / fd:.6f}")
            writer.writerow(out)

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
