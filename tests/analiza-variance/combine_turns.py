#!/usr/bin/env python3
"""Combine N per-turn aggregate CSVs into one mean±std table across turns.

Each input CSV is the output of aggregate_mean.py / aggregate_pct.py for ONE
turn (one repeated run / seed): rows = methods, columns = metric labels, e.g.

    method,Triple Preservation Ratio
    Applied Alignments,0.9997
    AROM,0.9578
    ...

All inputs must share the same method rows and metric columns (they will, since
each turn runs the identical aggregation).  This script stacks them and, per
(method, metric), computes the mean and sample standard deviation across turns
— the seed-variance signal that answers "is this a single-seed anecdote?".

Two outputs are written:
  --output <plot.csv>   wide, plot-friendly:
        method,<m1>,<m1>_std,<m2>,<m2>_std,...
        (means in the bare metric columns so plot_variance.py / plot_pct.py can
         read header[1:] as metrics; *_std columns carry the error-bar sizes.)
  --pm-output <table.csv>  thesis-friendly "mean ± std" strings:
        method,<m1>,<m2>,...
        Applied Alignments,0.9997 ± 0.0001,...
        (n turns and the per-turn raw values are recorded in a trailing comment.)
"""

import argparse
import csv
import statistics
from pathlib import Path


def _read(path: Path) -> tuple[list[str], list[str], dict[str, dict[str, float]]]:
    """Return (methods_in_order, metrics_in_order, {method: {metric: value}})."""
    with path.open() as fh:
        rows = list(csv.reader(fh))
    metrics = rows[0][1:]
    methods: list[str] = []
    data: dict[str, dict[str, float]] = {}
    for r in rows[1:]:
        if not r:
            continue
        method = r[0]
        methods.append(method)
        data[method] = {
            metric: (float(v) if v not in ("", None) else float("nan"))
            for metric, v in zip(metrics, r[1:])
        }
    return methods, metrics, data


def _fmt(x: float, decimals: int) -> str:
    return "" if x != x else f"{x:.{decimals}f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", action="append", required=True, type=Path,
                    metavar="TURN_CSV", help="per-turn aggregate CSV (repeatable)")
    ap.add_argument("--output", required=True, type=Path,
                    help="wide mean+std CSV for plot_variance.py")
    ap.add_argument("--pm-output", type=Path, default=None,
                    help="optional 'mean ± std' string table for thesis")
    ap.add_argument("--decimals", type=int, default=4)
    args = ap.parse_args()

    if not args.input:
        ap.error("need at least one --input")

    per_turn = [_read(p) for p in args.input]
    methods, metrics, _ = per_turn[0]

    # Guard: all turns must agree on shape (skip missing gracefully → NaN).
    for p, (m, mt, _) in zip(args.input, per_turn):
        if m != methods or mt != metrics:
            print(f"  WARNING: {p} has different methods/metrics than the first "
                  f"input — values will be matched by name where possible.")

    # Collect the stack of per-turn values for each (method, metric).
    stacks: dict[tuple[str, str], list[float]] = {}
    for _, _, data in per_turn:
        for method in methods:
            for metric in metrics:
                v = data.get(method, {}).get(metric, float("nan"))
                if v == v:  # not NaN
                    stacks.setdefault((method, metric), []).append(v)

    mean: dict[tuple[str, str], float] = {}
    std: dict[tuple[str, str], float] = {}
    for key, vals in stacks.items():
        mean[key] = statistics.fmean(vals)
        std[key] = statistics.stdev(vals) if len(vals) >= 2 else 0.0

    n_turns = len(args.input)

    # ── wide plot CSV: method, m1, m1_std, m2, m2_std, ... ──
    with args.output.open("w", newline="") as fh:
        w = csv.writer(fh)
        header = ["method"]
        for metric in metrics:
            header += [metric, f"{metric}_std"]
        w.writerow(header)
        for method in methods:
            row = [method]
            for metric in metrics:
                key = (method, metric)
                row += [_fmt(mean.get(key, float("nan")), args.decimals),
                        _fmt(std.get(key, float("nan")), args.decimals)]
            w.writerow(row)
    print(f"wrote {args.output}")

    # ── plus-minus table CSV (thesis) ──
    if args.pm_output is not None:
        with args.pm_output.open("w", newline="") as fh:
            fh.write(f"# mean ± sample-std across {n_turns} turn(s); "
                     f"per-turn CSVs: {', '.join(str(p) for p in args.input)}\n")
            w = csv.writer(fh)
            w.writerow(["method", *metrics])
            for method in methods:
                row = [method]
                for metric in metrics:
                    key = (method, metric)
                    if key not in mean:
                        row.append("")
                        continue
                    m, s = mean[key], std[key]
                    row.append(f"{m:.{args.decimals}f} ± {s:.{args.decimals}f}")
                w.writerow(row)
        print(f"wrote {args.pm_output}")


if __name__ == "__main__":
    main()
