#!/usr/bin/env python3
"""Combine N per-turn aggregate CSVs into one median/min/max table across turns.

Each input CSV is the output of aggregate_mean.py / aggregate_pct.py for ONE
turn (one repeated run / seed): rows = methods, columns = metric labels, e.g.

    method,Triple Preservation Ratio
    Applied Alignments,0.9997
    AROM,0.9578
    ...

All inputs must share the same method rows and metric columns (they will, since
each turn runs the identical aggregation).  This script stacks them and, per
(method, metric), computes the median, min, and max across turns — the
seed-variance signal that answers "is this a single-seed anecdote?".

Two outputs are written:
  --output <plot.csv>   wide, plot-friendly:
        method,<m1>,<m1>_min,<m1>_max,<m2>,<m2>_min,<m2>_max,...
        (medians in the bare metric columns so plot_turns.py can read
         header[1:] as metrics; *_min/*_max columns carry the whisker extents.)
  --pm-output <table.csv>  thesis-friendly "median [min; max]" strings:
        method,<m1>,<m2>,...
        Applied Alignments,0.9573 [0.9401; 0.9688],...
        (n turns and the per-turn raw values are recorded in a trailing comment.)
"""

import argparse
import csv
import os
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
                    help="wide median/min/max CSV for plot_turns.py")
    ap.add_argument("--pm-output", type=Path, default=None,
                    help="optional 'median [min; max]' string table for thesis")
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

    median: dict[tuple[str, str], float] = {}
    vmin: dict[tuple[str, str], float] = {}
    vmax: dict[tuple[str, str], float] = {}
    for key, vals in stacks.items():
        median[key] = statistics.median(vals)
        vmin[key] = min(vals)
        vmax[key] = max(vals)

    n_turns = len(args.input)

    # CoMerger timeout note (set by analyze-all.sh when a dataset hit the 3-min
    # cap): recorded as a leading '#' comment so the tables document that any
    # CoMerger row is a mean over the remaining datasets.  Readers (plot_turns)
    # skip '#'-prefixed lines.
    timeout_note = os.environ.get("COMERGER_TIMEOUT_NOTE", "").strip()

    # ── wide plot CSV: method, m1, m1_min, m1_max, m2, m2_min, m2_max, ... ──
    with args.output.open("w", newline="") as fh:
        if timeout_note:
            fh.write(f"# NOTE: {timeout_note}\n")
        w = csv.writer(fh)
        header = ["method"]
        for metric in metrics:
            header += [metric, f"{metric}_min", f"{metric}_max"]
        w.writerow(header)
        for method in methods:
            row = [method]
            for metric in metrics:
                key = (method, metric)
                row += [_fmt(median.get(key, float("nan")), args.decimals),
                        _fmt(vmin.get(key, float("nan")), args.decimals),
                        _fmt(vmax.get(key, float("nan")), args.decimals)]
            w.writerow(row)
    print(f"wrote {args.output}")

    # ── plus-minus table CSV (thesis) ──
    if args.pm_output is not None:
        with args.pm_output.open("w", newline="") as fh:
            if timeout_note:
                fh.write(f"# NOTE: {timeout_note}\n")
            fh.write(f"# median [min; max] across {n_turns} turn(s); "
                     f"per-turn CSVs: {', '.join(str(p) for p in args.input)}\n")
            w = csv.writer(fh)
            w.writerow(["method", *metrics])
            for method in methods:
                row = [method]
                for metric in metrics:
                    key = (method, metric)
                    if key not in median:
                        row.append("")
                        continue
                    md, lo, hi = median[key], vmin[key], vmax[key]
                    row.append(f"{md:.{args.decimals}f} [{lo:.{args.decimals}f}; {hi:.{args.decimals}f}]")
                w.writerow(row)
        print(f"wrote {args.pm_output}")


if __name__ == "__main__":
    main()
