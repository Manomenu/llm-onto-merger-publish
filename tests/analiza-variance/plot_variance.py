#!/usr/bin/env python3
"""Grouped bar chart WITH error bars, from a combine_turns.py wide CSV.

Input CSV (output of combine_turns.py --output):
    method,<m1>,<m1>_std,<m2>,<m2>_std,...
    Applied Alignments,0.9997,0.0001,...
Bare metric columns are the across-turn means (bar heights); the paired
`<metric>_std` columns are the sample standard deviations (error-bar half-height,
symmetric).  One subplot per metric, one bar per method, error bars = ±std.
Bar labels show "mean" and, underneath, "±std" so the spread is legible in print.

Mirrors tests/analiza/plot_pct.py (same layout/flags) so the variance charts are
visually consistent with the single-run thesis figures.
"""

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt

_BAR_COLOR = "#4472C4"
_ERR_KW = dict(ecolor="#222222", capsize=4, elinewidth=1.1, capthick=1.1)


def _pretty(name: str) -> str:
    if name.isupper():
        return name
    return " ".join(w.capitalize() for w in name.split("_"))


def _parse(path: Path):
    with path.open() as fh:
        rows = [r for r in csv.reader(fh) if r and not r[0].lstrip().startswith("#")]
    header = rows[0]
    cols = header[1:]
    metrics = [c for c in cols if not c.endswith("_std")]
    col_idx = {c: i + 1 for i, c in enumerate(cols)}  # +1 for the 'method' col
    methods: list[str] = []
    mean: dict[str, list[float]] = {}
    std: dict[str, list[float]] = {}
    for r in rows[1:]:
        method = r[0]
        methods.append(method)
        mvals, svals = [], []
        for metric in metrics:
            mv = r[col_idx[metric]] if col_idx[metric] < len(r) else ""
            sc = f"{metric}_std"
            sv = r[col_idx[sc]] if sc in col_idx and col_idx[sc] < len(r) else ""
            mvals.append(float(mv) if mv else float("nan"))
            svals.append(float(sv) if sv else 0.0)
        mean[method] = mvals
        std[method] = svals
    return metrics, methods, mean, std


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--title", default="")
    ap.add_argument("--ylabel", default=None)
    ap.add_argument("--bar-fmt", default="%.2f")
    ap.add_argument("--ylabel-for", action="append", default=[], nargs=2,
                    metavar=("METRIC", "LABEL"))
    ap.add_argument("--bar-fmt-for", action="append", default=[], nargs=2,
                    metavar=("METRIC", "FMT"))
    ap.add_argument("--log-for", action="append", default=[])
    ap.add_argument("--n-turns", type=int, default=None,
                    help="number of turns, shown in the figure subtitle")
    args = ap.parse_args()
    ylabel_for = dict(args.ylabel_for)
    fmt_for = dict(args.bar_fmt_for)
    log_metrics = set(args.log_for)

    metrics, methods, mean, std = _parse(args.input)

    n = len(metrics)
    cols = 2 if n > 1 else 1
    plot_rows = math.ceil(n / cols)
    fig, axes = plt.subplots(plot_rows, cols, figsize=(6.5 * cols, 4.0 * plot_rows))
    axes = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for i, metric in enumerate(metrics):
        ax = axes[i]
        vals = [mean[m][i] for m in methods]
        errs = [std[m][i] for m in methods]
        bars = ax.bar(methods, vals, yerr=errs, color=_BAR_COLOR,
                      edgecolor="black", linewidth=0.5, error_kw=_ERR_KW)
        ax.set_title(_pretty(metric))
        default_y = args.ylabel if args.ylabel else _pretty(metric)
        ax.set_ylabel(ylabel_for.get(metric, default_y))
        ax.axhline(0, color="black", linewidth=0.6)
        ax.set_xticks(range(len(methods)))
        ax.set_xticklabels(methods, rotation=30, ha="right")

        fmt = fmt_for.get(metric, args.bar_fmt)
        for bar, v, e in zip(bars, vals, errs):
            if v != v:
                continue
            top = bar.get_height() + (e if e == e else 0)
            label = fmt % v
            if e and e == e and e > 0:
                label += f"\n±{fmt % e}".replace("%", "")  # ±std under the mean
            ax.annotate(label, xy=(bar.get_x() + bar.get_width() / 2, top),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8)
        ax.grid(axis="y", alpha=0.3)

        finite = [(v, e) for v, e in zip(vals, errs) if v == v]
        if metric in log_metrics:
            ax.set_yscale("symlog", linthresh=1)
            if finite:
                hi = max([v + (e or 0) for v, e in finite] + [1.0])
                ax.set_ylim(0, hi * 3)
        elif finite:
            lo = min([v - (e or 0) for v, e in finite] + [0.0])
            hi = max([v + (e or 0) for v, e in finite] + [0.0])
            span = hi - lo or abs(hi) or 1.0
            pad = span * 0.22
            ax.set_ylim(lo - pad, hi + pad)

    for j in range(n, len(axes)):
        axes[j].axis("off")

    subtitle = args.title
    if args.n_turns is not None:
        tag = f"mean ± std over {args.n_turns} runs"
        subtitle = f"{args.title}  ({tag})" if args.title else tag
    if subtitle:
        fig.suptitle(subtitle, fontsize=12, wrap=True)
    plt.tight_layout(rect=(0, 0, 1, 0.94) if subtitle else None)
    plt.savefig(args.output, dpi=150,
                format="jpg" if args.output.suffix == ".jpg" else None)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
