#!/usr/bin/env python3
"""Aggregate per-turn cost/work/<turn>/raw_cost.csv files across turns and
render the per-dataset cost bar chart.

Aggregation is MEAN + min/max — NOT median, unlike every other dimension in
this folder (combine_turns.py/plot_grouped.py) — because the author
explicitly wants the average spend here rather than the typical-run figure.

Unlike the other dimensions there is also no method axis: only the proposed
LLM method has a recorded cost, so rows are simply datasets.

Inputs: one raw_cost.csv per turn (extract_cost.py output), columns
    dataset,total_cost_usd,call_count,input_tokens_total,output_tokens_total
Blank cells (extract_cost.py's NaN-skip convention for a missing/unreadable
cost_stats.json) are ignored when averaging — a dataset present in some turns
but not others still gets a mean over however many turns had data.

Outputs:
  --pm-output   thesis table: dataset,total_cost_usd,call_count,
                input_tokens_total,output_tokens_total (each "mean [min; max]"),
                with a leading '# ...' comment documenting N turns and the
                AML-input-only / reference-excluded scope.
  --jpg-output  bar chart: x = dataset, y = cost (USD), one bar per dataset
                (mean) with min/max whiskers and a value label — same
                palette/error-bar style as plot_grouped.py.
"""

import argparse
import csv
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Same qualitative palette / error-bar style as plot_grouped.py, for visual
# consistency across every dimension's chart.
_PALETTE = ["#4472C4", "#ED7D31", "#70AD47", "#9B59B6", "#E1C233", "#4BA3C3"]
_ERR_KW = dict(ecolor="#222222", capsize=3, elinewidth=1.0, capthick=1.0)

_FIELDS = ["total_cost_usd", "call_count", "input_tokens_total", "output_tokens_total"]


def _read(path: Path) -> tuple[list[str], dict[str, dict[str, float]]]:
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    datasets = [r["dataset"] for r in rows]
    data: dict[str, dict[str, float]] = {}
    for r in rows:
        data[r["dataset"]] = {
            f: (float(r[f]) if r.get(f, "") not in ("", None) else float("nan"))
            for f in _FIELDS
        }
    return datasets, data


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", action="append", required=True, type=Path,
                    metavar="TURN_CSV", help="per-turn raw_cost.csv (repeatable)")
    ap.add_argument("--pm-output", required=True, type=Path)
    ap.add_argument("--jpg-output", required=True, type=Path)
    ap.add_argument("--decimals", type=int, default=6)
    args = ap.parse_args()

    if not args.input:
        ap.error("need at least one --input")

    per_turn = [_read(p) for p in args.input]
    datasets: list[str] = []
    for ds_list, _ in per_turn:
        for ds in ds_list:
            if ds not in datasets:
                datasets.append(ds)

    stacks: dict[tuple[str, str], list[float]] = {}
    for _, data in per_turn:
        for ds in datasets:
            row = data.get(ds)
            if row is None:
                continue
            for f in _FIELDS:
                v = row[f]
                if v == v:  # not NaN
                    stacks.setdefault((ds, f), []).append(v)

    mean: dict[tuple[str, str], float] = {}
    vmin: dict[tuple[str, str], float] = {}
    vmax: dict[tuple[str, str], float] = {}
    for key, vals in stacks.items():
        mean[key] = statistics.mean(vals)
        vmin[key] = min(vals)
        vmax[key] = max(vals)

    n_turns = len(args.input)

    all_costs = [v for ds in datasets for v in stacks.get((ds, "total_cost_usd"), [])]
    zero_note = ""
    if all_costs and all(v == 0.0 for v in all_costs):
        zero_note = ("costs were zero/unrecorded for every turn and dataset "
                      "(no OpenRouter price for this model, or a local backend was used)")

    # ── pm table ──
    args.pm_output.parent.mkdir(parents=True, exist_ok=True)
    with args.pm_output.open("w", newline="") as fh:
        fh.write(f"# mean [min; max] across {n_turns} turn(s); costs cover the "
                  "AML-input (s5) merge only — reference-input (s6) runs are "
                  "excluded from this table.\n")
        if zero_note:
            fh.write(f"# NOTE: {zero_note}\n")
        w = csv.writer(fh)
        w.writerow(["dataset", *_FIELDS])
        for ds in datasets:
            row = [ds]
            for f in _FIELDS:
                key = (ds, f)
                if key not in mean:
                    row.append("")
                    continue
                m, lo, hi = mean[key], vmin[key], vmax[key]
                dec = args.decimals if f == "total_cost_usd" else 0
                row.append(f"{m:.{dec}f} [{lo:.{dec}f}; {hi:.{dec}f}]")
            w.writerow(row)
    print(f"wrote {args.pm_output}")

    # ── bar chart: x = dataset, y = cost (USD), mean bar + min/max whiskers ──
    fig, ax = plt.subplots(figsize=(max(6.5, 1.6 * len(datasets) + 3.0), 4.4))
    xs = list(range(len(datasets)))
    vals = [mean.get((ds, "total_cost_usd"), float("nan")) for ds in datasets]
    los = [vmin.get((ds, "total_cost_usd"), float("nan")) for ds in datasets]
    his = [vmax.get((ds, "total_cost_usd"), float("nan")) for ds in datasets]
    plot_vals = [v if v == v else 0.0 for v in vals]
    err_lo = [max(v - lo, 0.0) if v == v and lo == lo else 0.0 for v, lo in zip(vals, los)]
    err_hi = [max(hi - v, 0.0) if v == v and hi == hi else 0.0 for v, hi in zip(vals, his)]
    ax.bar(xs, plot_vals, width=0.55, yerr=[err_lo, err_hi],
           color=_PALETTE[0], edgecolor="black", linewidth=0.4, error_kw=_ERR_KW)
    for i, (x, v) in enumerate(zip(xs, vals)):
        if v != v:
            continue
        top = v + err_hi[i]
        ax.annotate(f"${v:.4f}", xy=(x, top), xytext=(0, 3),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels(datasets, rotation=20, ha="right")
    ax.set_ylabel("Cost (USD)")
    ax.grid(axis="y", alpha=0.3)
    finite_idx = [i for i, v in enumerate(vals) if v == v]
    if finite_idx:
        top = max(his[i] if his[i] == his[i] else vals[i] for i in finite_idx)
        ax.set_ylim(0, top * 1.25 if top > 0 else 1.0)

    ax.set_title(f"LLM merge cost per dataset — mean (min–max) over "
                 f"{n_turns} run(s), AML-input only", fontsize=11, wrap=True)

    bottom_rect = 0.0
    if zero_note:
        fig.text(0.5, 0.01, "Note: " + zero_note, ha="center", va="bottom",
                  fontsize=8, color="#8a5000", wrap=True)
        bottom_rect = 0.08
    plt.tight_layout(rect=(0, bottom_rect, 1, 1))

    args.jpg_output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.jpg_output, dpi=150, format="jpg")
    print(f"wrote {args.jpg_output}")


if __name__ == "__main__":
    main()
