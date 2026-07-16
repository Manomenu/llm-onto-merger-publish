#!/usr/bin/env python3
"""Grouped bar chart WITH min/max error bars, from a combine_turns.py wide CSV.

Input CSV (output of combine_turns.py --output):
    method,<m1>,<m1>_min,<m1>_max,<m2>,<m2>_min,<m2>_max,...
    Applied Alignments,0.9573,0.9401,0.9688,...
Bare metric columns are the across-turn medians (bar heights); the paired
`<metric>_min` / `<metric>_max` columns give the whisker extents (asymmetric
error bars from median down to min and up to max).  One subplot per metric,
one bar per method.
Bar labels show "median" and, underneath, "min–max" so the spread is legible
in print.

Mirrors tests/analiza/plot_pct.py (same layout/flags) so the repeated-runs
charts are visually consistent with the single-run thesis figures.
"""

import argparse
import csv
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
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
    metrics = [c for c in cols if not c.endswith("_min") and not c.endswith("_max")]
    col_idx = {c: i + 1 for i, c in enumerate(cols)}  # +1 for the 'method' col
    methods: list[str] = []
    median: dict[str, list[float]] = {}
    vmin: dict[str, list[float]] = {}
    vmax: dict[str, list[float]] = {}
    for r in rows[1:]:
        method = r[0]
        methods.append(method)
        mvals, lovals, hivals = [], [], []
        for metric in metrics:
            mv = r[col_idx[metric]] if col_idx[metric] < len(r) else ""
            lc = f"{metric}_min"
            hc = f"{metric}_max"
            lv = r[col_idx[lc]] if lc in col_idx and col_idx[lc] < len(r) else ""
            hv = r[col_idx[hc]] if hc in col_idx and col_idx[hc] < len(r) else ""
            mvals.append(float(mv) if mv else float("nan"))
            lovals.append(float(lv) if lv else float("nan"))
            hivals.append(float(hv) if hv else float("nan"))
        median[method] = mvals
        vmin[method] = lovals
        vmax[method] = hivals
    return metrics, methods, median, vmin, vmax


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

    metrics, methods, median, vmin, vmax = _parse(args.input)

    n = len(metrics)
    cols = 2 if n > 1 else 1
    plot_rows = math.ceil(n / cols)
    fig, axes = plt.subplots(plot_rows, cols, figsize=(6.5 * cols, 4.0 * plot_rows))
    axes = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for i, metric in enumerate(metrics):
        ax = axes[i]
        vals = [median[m][i] for m in methods]
        los = [vmin[m][i] for m in methods]
        his = [vmax[m][i] for m in methods]
        err_lo = [max(v - lo, 0.0) if v == v and lo == lo else 0.0 for v, lo in zip(vals, los)]
        err_hi = [max(hi - v, 0.0) if v == v and hi == hi else 0.0 for v, hi in zip(vals, his)]
        bars = ax.bar(methods, vals, yerr=[err_lo, err_hi], color=_BAR_COLOR,
                      edgecolor="black", linewidth=0.5, error_kw=_ERR_KW)
        ax.set_title(_pretty(metric))
        default_y = args.ylabel if args.ylabel else _pretty(metric)
        ax.set_ylabel(ylabel_for.get(metric, default_y))
        ax.axhline(0, color="black", linewidth=0.6)
        ax.set_xticks(range(len(methods)))
        ax.set_xticklabels(methods, rotation=30, ha="right")

        fmt = fmt_for.get(metric, args.bar_fmt)
        for bar, v, lo, hi in zip(bars, vals, los, his):
            if v != v:
                continue
            top = bar.get_height() + (hi - v if hi == hi and hi > v else 0)
            label = fmt % v
            if lo == lo and hi == hi and hi > lo:
                label += f"\n{fmt % lo}–{fmt % hi}".replace("%", "")  # min–max under the median
            ax.annotate(label, xy=(bar.get_x() + bar.get_width() / 2, top),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8)
        ax.grid(axis="y", alpha=0.3)

        finite = [(v, lo, hi) for v, lo, hi in zip(vals, los, his) if v == v]
        if metric in log_metrics:
            ax.set_yscale("symlog", linthresh=1)
            if finite:
                hi = max([hi if hi == hi else v for v, lo, hi in finite] + [1.0])
                ax.set_ylim(0, hi * 3)
        elif finite:
            lo = min([lo if lo == lo else v for v, lo, hi in finite] + [0.0])
            hi = max([hi if hi == hi else v for v, lo, hi in finite] + [0.0])
            span = hi - lo or abs(hi) or 1.0
            pad = span * 0.22
            ax.set_ylim(lo - pad, hi + pad)

    for j in range(n, len(axes)):
        axes[j].axis("off")

    subtitle = args.title
    if args.n_turns is not None:
        tag = f"median (min–max) over {args.n_turns} runs"
        subtitle = f"{args.title}  ({tag})" if args.title else tag
    if subtitle:
        fig.suptitle(subtitle, fontsize=12, wrap=True)

    # CoMerger timeout footnote: analyze-all.sh exports COMERGER_TIMEOUT_NOTE
    # when a dataset's CoMerger run hit the 3-min cap.  Any CoMerger bar shown
    # here is a mean over the *remaining* datasets, so flag that explicitly.
    timeout_note = os.environ.get("COMERGER_TIMEOUT_NOTE", "").strip()
    bottom_rect = 0.0
    if timeout_note:
        # Plain-text prefix (no emoji): DejaVu Sans lacks the stopwatch glyph.
        fig.text(0.5, 0.01, f"Note: {timeout_note}", ha="center", va="bottom",
                 fontsize=8, color="#8a5000", wrap=True)
        bottom_rect = 0.05

    top_rect = 0.94 if subtitle else 1.0
    plt.tight_layout(rect=(0, bottom_rect, 1, top_rect))
    plt.savefig(args.output, dpi=150,
                format="jpg" if args.output.suffix == ".jpg" else None)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
