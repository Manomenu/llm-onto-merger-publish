#!/usr/bin/env python3
"""Combine N per-turn OAEI-rejection CSVs into a mean±std table + chart.

Each input CSV is the output of tests/analiza/domain_coherence/oaei_rejection.py
for ONE turn (one repeated run / seed):

    method,dataset,reference_total,aml_total,rejected_correct,accepted_aml_fp
    AROM,conference,13,9,0,1
    ...

`reference_total` / `aml_total` are deterministic given the input ontologies
(same reference alignment, same AML run) so they are carried through as-is
(first non-empty value seen for that dataset); `rejected_correct` and
`accepted_aml_fp` are the seed-varying measures — for each (method, dataset)
this script stacks the per-turn values and reports the mean and sample
standard deviation across turns.  A method/dataset cell that is missing in a
turn (empty string — e.g. no scenario_3 output for that turn) is simply
skipped for that turn rather than treated as zero.

Two outputs:
  --pm-output <table.csv>   thesis-friendly table:
        method,dataset,reference_total,aml_total,rejected_correct (mean±std),accepted_aml_fp (mean±std)
  --jpg-output <chart.jpg>  grouped bar chart mirroring oaei_rejection.py's
        layout (rows = datasets, cols = the two measures, bars = methods) with
        ±std error bars across turns.
"""

import argparse
import csv
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

_BAR_COLOR = "#4472C4"
_ERR_KW = dict(ecolor="#222222", capsize=4, elinewidth=1.1, capthick=1.1)

_MEASURES = [
    ("rejected_correct", "Rejected correct alignments\n(reference input; lower = better)"),
    ("accepted_aml_fp", "Accepted AML false-positives\n(AML input; lower = better)"),
]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", action="append", required=True, type=Path,
                    metavar="TURN_CSV", help="per-turn oaei_rejection.py CSV (repeatable)")
    ap.add_argument("--pm-output", required=True, type=Path,
                    help="'mean ± std' thesis table CSV")
    ap.add_argument("--jpg-output", required=True, type=Path,
                    help="grouped bar chart with ±std error bars")
    ap.add_argument("--title",
                    default="Adjusted OAEI reference-alignment validation (Domain Coherence)",
                    help="figure suptitle")
    ap.add_argument("--decimals", type=int, default=2)
    ap.add_argument("--n-turns", type=int, default=None,
                    help="number of turns, shown in the figure subtitle")
    args = ap.parse_args()

    if not args.input:
        ap.error("need at least one --input")

    # method_order / dataset_order preserve first-seen order (mirrors oaei_rejection.py).
    method_order: list[str] = []
    dataset_order: list[str] = []
    totals: dict[tuple[str, str], tuple[str, str]] = {}  # (method,dataset) -> (reference_total, aml_total)
    stacks: dict[tuple[str, str, str], list[float]] = {}  # (method,dataset,measure) -> values across turns

    for path in args.input:
        for row in _read(path):
            method, dataset = row["method"], row["dataset"]
            if method not in method_order:
                method_order.append(method)
            if dataset not in dataset_order:
                dataset_order.append(dataset)
            key = (method, dataset)
            if key not in totals:
                totals[key] = (row.get("reference_total", ""), row.get("aml_total", ""))
            for measure, _ in _MEASURES:
                v = row.get(measure, "")
                if v == "" or v is None:
                    continue
                stacks.setdefault((method, dataset, measure), []).append(float(v))

    mean: dict[tuple[str, str, str], float] = {}
    std: dict[tuple[str, str, str], float] = {}
    for key, vals in stacks.items():
        mean[key] = statistics.fmean(vals)
        std[key] = statistics.stdev(vals) if len(vals) >= 2 else 0.0

    n_turns = args.n_turns if args.n_turns is not None else len(args.input)

    # ── thesis "mean ± std" table ──
    args.pm_output.parent.mkdir(parents=True, exist_ok=True)
    with args.pm_output.open("w", newline="") as fh:
        fh.write(f"# mean ± sample-std across {n_turns} turn(s); "
                 f"per-turn CSVs: {', '.join(str(p) for p in args.input)}\n")
        w = csv.writer(fh)
        w.writerow(["method", "dataset", "reference_total", "aml_total",
                    "rejected_correct (mean±std)", "accepted_aml_fp (mean±std)"])
        for dataset in dataset_order:
            for method in method_order:
                key = (method, dataset)
                if key not in totals:
                    continue
                ref_total, aml_total = totals[key]
                row = [method, dataset, ref_total, aml_total]
                for measure, _ in _MEASURES:
                    mkey = (method, dataset, measure)
                    if mkey not in mean:
                        row.append("n/a")
                        continue
                    m, s = mean[mkey], std[mkey]
                    row.append(f"{m:.{args.decimals}f} ± {s:.{args.decimals}f}")
                w.writerow(row)
    print(f"wrote {args.pm_output}")

    # ── grouped bar chart with error bars (rows=datasets, cols=measures) ──
    args.jpg_output.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(len(dataset_order), 2,
                             figsize=(12, 5 * len(dataset_order)), squeeze=False)
    for di, dataset in enumerate(dataset_order):
        for mi, (measure, title) in enumerate(_MEASURES):
            ax = axes[di][mi]
            vals, errs = [], []
            for method in method_order:
                key = (method, dataset, measure)
                vals.append(mean.get(key, float("nan")))
                errs.append(std.get(key, 0.0))
            plot_vals = [v if v == v else 0.0 for v in vals]
            bars = ax.bar(method_order, plot_vals, yerr=errs, color=_BAR_COLOR,
                          edgecolor="black", linewidth=0.5, error_kw=_ERR_KW)
            labels = []
            for v, e in zip(vals, errs):
                if v != v:
                    labels.append("n/a")
                elif e > 0:
                    labels.append(f"{v:.{args.decimals}f}\n±{e:.{args.decimals}f}")
                else:
                    labels.append(f"{v:.{args.decimals}f}")
            ax.bar_label(bars, labels=labels, padding=3, fontsize=8)
            ax.axhline(0, color="black", linewidth=0.6)
            ax.set_title(f"{dataset} — {title}")
            ax.set_ylabel("count")
            ax.tick_params(axis="x", rotation=20)
            ax.margins(y=0.25)

    subtitle = f"{args.title}  (mean ± std over {n_turns} runs)"
    fig.suptitle(subtitle, fontsize=12, wrap=True)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(args.jpg_output, dpi=150,
                format="jpg" if args.jpg_output.suffix == ".jpg" else None)
    print(f"wrote {args.jpg_output}")


if __name__ == "__main__":
    main()
