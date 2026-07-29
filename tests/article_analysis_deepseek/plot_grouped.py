#!/usr/bin/env python3
"""Grouped bar chart: one figure per metric, x = method, one coloured series
per DATASET (no averaging over datasets), min/max whiskers across turns.

Inputs are combine_turns.py wide CSVs — ONE per dataset — passed as

    --dataset <label> <combine_turns_wide.csv>   (repeatable)

Each wide CSV has:
    method,<m1>,<m1>_min,<m1>_max,<m2>,...
(medians in the bare metric columns; *_min/*_max give the whisker extents,
i.e. the min/max across turns for THAT dataset).

For every metric one subplot is drawn; within it each method gets one bar per
dataset (grouped, distinct colour), with asymmetric min–max error bars.  This
is the article-friendly layout: one image = one metric = all methods across all
datasets, so datasets are compared without averaging them away.

Shares flags (--ylabel-for / --bar-fmt / --bar-fmt-for / --log-for / --n-turns)
and the '#'-comment skipping with plot_turns.py.
"""

import argparse
import csv
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Qualitative, print- and (mostly) colour-blind-friendly series palette.
_PALETTE = ["#4472C4", "#ED7D31", "#70AD47", "#9B59B6", "#E1C233", "#4BA3C3"]
_ERR_KW = dict(ecolor="#222222", capsize=3, elinewidth=1.0, capthick=1.0)


def _pretty(name: str) -> str:
    if name.isupper():
        return name
    return " ".join(w.capitalize() for w in name.split("_"))


def _parse(path: Path):
    """One combine_turns wide CSV -> (metrics, methods, median, vmin, vmax)."""
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
            lc, hc = f"{metric}_min", f"{metric}_max"
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
    ap.add_argument("--dataset", action="append", required=True, nargs=2,
                    metavar=("LABEL", "CSV"),
                    help="dataset label + its combine_turns wide CSV (repeatable)")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--title", default="")
    ap.add_argument("--ylabel", default=None)
    ap.add_argument("--bar-fmt", default="%.2f")
    ap.add_argument("--ylabel-for", action="append", default=[], nargs=2,
                    metavar=("METRIC", "LABEL"))
    ap.add_argument("--bar-fmt-for", action="append", default=[], nargs=2,
                    metavar=("METRIC", "FMT"))
    ap.add_argument("--log-for", action="append", default=[])
    ap.add_argument("--n-turns", type=int, default=None)
    ap.add_argument("--dpi", type=int, default=150,
                    help="output resolution; 300 for print submissions")
    ap.add_argument("--drop-method", action="append", default=[],
                    help="method row to omit from the plot (repeatable); e.g. a reference "
                         "series that is zero by construction")
    ap.add_argument("--rename-method", action="append", default=[], nargs=2,
                    metavar=("OLD", "NEW"),
                    help="relabel a method on the x axis (repeatable); shorter labels need "
                         "less rotation overhang and make the figure shorter")
    ap.add_argument("--no-panel-title", action="store_true",
                    help="omit the per-panel title (redundant with the y label on "
                         "single-measure charts)")
    ap.add_argument("--panel-height", type=float, default=3.6,
                    help="height in inches of one panel row (default 3.6)")
    ap.add_argument("--legend-figure", action="store_true",
                    help="draw one shared legend above the panels instead of one per panel, "
                         "so it cannot overlap the bars")
    ap.add_argument("--vertical", action="store_true",
                    help="stack subplots in one column (fits a single text "
                         "column in a double-column article)")
    args = ap.parse_args()
    ylabel_for = dict(args.ylabel_for)
    fmt_for = dict(args.bar_fmt_for)
    log_metrics = set(args.log_for)
    dropped = set(args.drop_method)
    renames = dict(args.rename_method)

    datasets = [lbl for lbl, _ in args.dataset]
    parsed = {lbl: _parse(Path(p)) for lbl, p in args.dataset}

    # Methods/metrics = UNION across datasets (a dataset may be missing a method,
    # e.g. swo-acm has no CoMerger after a timeout — it must NOT drop CoMerger
    # from the whole figure).  Order methods by the canonical pipeline order.
    _CANON = ["Naive Union", "Applied Alignments", "AROM", "CoMerger",
              "Boomer", "Our Solution"]
    metrics: list[str] = []
    methods_seen: list[str] = []
    for lbl in datasets:
        mts, meths, _, _, _ = parsed[lbl]
        for mt in mts:
            if mt not in metrics:
                metrics.append(mt)
        for m in meths:
            if m not in methods_seen:
                methods_seen.append(m)
    methods = [m for m in _CANON if m in methods_seen] + \
              [m for m in methods_seen if m not in _CANON]
    methods = [m for m in methods if m not in dropped]

    def _get(lbl, method, metric_name):
        mts, meths, med, lo, hi = parsed[lbl]
        if method not in med or metric_name not in mts:
            return float("nan"), float("nan"), float("nan")
        k = mts.index(metric_name)
        return med[method][k], lo[method][k], hi[method][k]

    n = len(metrics)
    cols = 1 if args.vertical else (2 if n > 1 else 1)
    plot_rows = math.ceil(n / cols)
    fig, axes = plt.subplots(plot_rows, cols,
                             figsize=(6.0 * cols, args.panel_height * plot_rows))
    axes = axes.flatten() if hasattr(axes, "flatten") else [axes]

    n_ds = len(datasets)
    total_w = 0.82
    bw = total_w / n_ds
    xbase = list(range(len(methods)))

    for i, metric in enumerate(metrics):
        ax = axes[i]
        all_finite: list[tuple[float, float, float]] = []
        for j, lbl in enumerate(datasets):
            centers = [x - total_w / 2 + bw * (j + 0.5) for x in xbase]
            vals, los, his = [], [], []
            for method in methods:
                v, lo, hi = _get(lbl, method, metric)
                vals.append(v)
                los.append(lo)
                his.append(hi)
                if v == v:
                    all_finite.append((v, lo, hi))
            plot_vals = [v if v == v else 0.0 for v in vals]
            # A missing (NaN) cell must NOT read as a genuine zero: mark it.
            for c, v in zip(centers, vals):
                if v != v:
                    ax.annotate("n/a", xy=(c, 0), xytext=(0, 3),
                                textcoords="offset points", ha="center",
                                va="bottom", fontsize=6, rotation=90,
                                color="#8a5000")
            err_lo = [max(v - lo, 0.0) if v == v and lo == lo else 0.0 for v, lo in zip(vals, los)]
            err_hi = [max(hi - v, 0.0) if v == v and hi == hi else 0.0 for v, hi in zip(vals, his)]
            ax.bar(centers, plot_vals, width=bw, yerr=[err_lo, err_hi],
                   color=_PALETTE[j % len(_PALETTE)], edgecolor="black",
                   linewidth=0.4, error_kw=_ERR_KW, label=lbl)
            fmt = fmt_for.get(metric, args.bar_fmt)
            for c, v, hi in zip(centers, vals, his):
                if v != v:
                    continue
                top = v + (hi - v if hi == hi and hi > v else 0)
                ax.annotate(fmt % v, xy=(c, top), xytext=(0, 2),
                            textcoords="offset points", ha="center", va="bottom",
                            fontsize=6.5, rotation=90)

        if not args.no_panel_title:
            ax.set_title(_pretty(metric))
        default_y = args.ylabel if args.ylabel else _pretty(metric)
        ax.set_ylabel(ylabel_for.get(metric, default_y))
        ax.axhline(0, color="black", linewidth=0.6)
        ax.set_xticks(xbase)
        ax.set_xticklabels([renames.get(m, m) for m in methods],
                           rotation=30, ha="right")
        ax.grid(axis="y", alpha=0.3)
        if not args.legend_figure:
            ax.legend(fontsize=7, title="dataset", framealpha=0.9)

        if metric in log_metrics:
            ax.set_yscale("symlog", linthresh=1)
            if all_finite:
                # symlog data can be signed (e.g. triple-count change spans
                # −12004…+4172) — the y-limits must cover BOTH signs, not floor
                # at 0, or negative bars vanish.
                hi = max([h if h == h else v for v, lo, h in all_finite] + [0.0])
                lo = min([l if l == l else v for v, l, h in all_finite] + [0.0])
                ax.set_ylim(lo * 3 if lo < 0 else 0.0, hi * 3 if hi > 0 else 1.0)
        elif all_finite:
            lo = min([l if l == l else v for v, l, h in all_finite] + [0.0])
            hi = max([h if h == h else v for v, l, h in all_finite] + [0.0])
            span = hi - lo or abs(hi) or 1.0
            pad = span * 0.28
            ax.set_ylim(lo - pad, hi + pad)

    for j in range(n, len(axes)):
        axes[j].axis("off")

    if args.legend_figure:
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", ncol=max(1, len(labels)),
                   fontsize=8, frameon=False,
                   bbox_to_anchor=(0.5, 0.955 if args.title or args.n_turns else 0.99))

    subtitle = args.title
    if args.n_turns is not None:
        tag = f"median (min–max) over {args.n_turns} runs, per dataset"
        subtitle = f"{args.title}  ({tag})" if args.title else tag
    if subtitle:
        fig.suptitle(subtitle, fontsize=12, wrap=True)

    # CoMerger timeout footnote (analyze-all.sh exports COMERGER_TIMEOUT_NOTE):
    # a dataset with no CoMerger bar simply hit the 3-min cap.
    timeout_note = os.environ.get("COMERGER_TIMEOUT_NOTE", "").strip()
    bottom_rect = 0.0
    if timeout_note:
        fig.text(0.5, 0.01, f"Note: {timeout_note}", ha="center", va="bottom",
                 fontsize=8, color="#8a5000", wrap=True)
        bottom_rect = 0.05

    top_rect = (0.90 if args.legend_figure else 0.94) if subtitle else (0.94 if args.legend_figure else 1.0)
    plt.tight_layout(rect=(0, bottom_rect, 1, top_rect))
    plt.savefig(args.output, dpi=args.dpi,
                format="jpg" if args.output.suffix == ".jpg" else None)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
