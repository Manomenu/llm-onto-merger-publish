#!/usr/bin/env python3
"""Generate a grouped bar chart from a %-change CSV (output of aggregate_pct.py).

Input CSV format: row 0 = header (method, metric1, metric2, ...);
remaining rows = methods (excluding Naive Union).
Produces one figure with subplots — one subplot per metric, bars per method,
labels on bars showing %.
"""

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt

_BAR_COLOR = "#4472C4"  # uniform muted blue for all methods (thesis-friendly)
METHOD_COLOR: dict[str, str] = {}


def _pretty(name: str) -> str:
    if name.isupper():
        return name
    return " ".join(w.capitalize() for w in name.split("_"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="")
    parser.add_argument("--baseline-label", default="Naive Union",
                        help="baseline name shown in y-axis label")
    parser.add_argument("--ylabel", default=None,
                        help="override the default '% change vs ...' y-axis label")
    parser.add_argument("--bar-fmt", default="%+.1f%%",
                        help="format string for bar value labels (default: %%+.1f%%%%)")
    parser.add_argument("--ylabel-for", action="append", default=[], nargs=2,
                        metavar=("METRIC", "LABEL"),
                        help="per-metric y-axis label override (repeatable)")
    parser.add_argument("--bar-fmt-for", action="append", default=[], nargs=2,
                        metavar=("METRIC", "FMT"),
                        help="per-metric bar-label format override (repeatable)")
    parser.add_argument("--log-for", action="append", default=[],
                        help="metric name(s) to render on symlog y-axis (repeatable)")
    args = parser.parse_args()
    ylabel_for = dict(args.ylabel_for)
    fmt_for = dict(args.bar_fmt_for)
    log_metrics = set(args.log_for)

    with args.input.open() as fh:
        rows = list(csv.reader(fh))
    metrics = rows[0][1:]
    methods: list[str] = []
    values: dict[str, list[float]] = {}
    for r in rows[1:]:
        methods.append(r[0])
        values[r[0]] = [float(v) if v else float("nan") for v in r[1:]]

    n = len(metrics)
    cols = 2 if n > 1 else 1
    plot_rows = math.ceil(n / cols)
    fig, axes = plt.subplots(plot_rows, cols, figsize=(6.5 * cols, 4.0 * plot_rows))
    axes = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for i, metric in enumerate(metrics):
        ax = axes[i]
        vals = [values[m][i] for m in methods]
        colors = [METHOD_COLOR.get(m, _BAR_COLOR) for m in methods]
        bars = ax.bar(methods, vals, color=colors, edgecolor="black", linewidth=0.5)
        ax.set_title(_pretty(metric))
        default_y = args.ylabel if args.ylabel else f"% change vs {args.baseline_label}"
        ax.set_ylabel(ylabel_for.get(metric, default_y))
        ax.axhline(0, color="black", linewidth=0.6)
        ax.set_xticks(range(len(methods)))
        ax.set_xticklabels(methods, rotation=30, ha="right")
        ax.bar_label(bars, fmt=fmt_for.get(metric, args.bar_fmt), padding=3, fontsize=9)
        ax.grid(axis="y", alpha=0.3)

        # Headroom for bar labels so they don't clip the axis edge.
        finite = [v for v in vals if v == v]
        if metric in log_metrics:
            ax.set_yscale("symlog", linthresh=1)
            if finite:
                hi = max(finite + [1.0])
                ax.set_ylim(0, hi * 3)
        elif finite:
            lo, hi = min(finite + [0.0]), max(finite + [0.0])
            span = hi - lo or abs(hi) or 1.0
            pad = span * 0.18
            ax.set_ylim(lo - pad, hi + pad)

    for j in range(n, len(axes)):
        axes[j].axis("off")

    if args.title:
        fig.suptitle(args.title, fontsize=12, wrap=True)
    plt.tight_layout(rect=(0, 0, 1, 0.94) if args.title else None)
    plt.savefig(args.output, dpi=150, format="jpg" if args.output.suffix == ".jpg" else None)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
