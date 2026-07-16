#!/usr/bin/env python3
"""Compute the "Proposed deepseek-v4-flash" row for the two OAEI-rejection
measures (Domain Coherence), and combine it with the existing
adjusted_oaei_rejection.csv (gpt-oss-20b, all methods) into one table + chart.

Invokes oaei_rejection.py's own CLI (unchanged) pointed at scenario_5 (AML-input,
S2_DIR-equivalent) and scenario_6 (reference-input, S3_DIR-equivalent) run dirs
for the deepseek-v4-flash run — it recomputes ALL methods fresh the same way
domain_coherence/analyze.sh already does for gpt-oss-20b, just against a
different pair of already-existing run directories.  Only the "Proposed" row
is kept from that recompute (renamed); AROM/CoMerger/Boomer are deterministic
baselines unrelated to which LLM merged, so the existing (already computed)
rows for them are reused as-is, avoiding duplicate/near-duplicate baseline rows.
"""

import csv
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
GPT_OSS_LABEL = "Proposed gpt-oss-20b"
DEEPSEEK_LABEL = "Proposed deepseek-v4-flash"

# display dataset -> (tests/inputs folder, s5 label, s6 label)
DATASETS = {
    "conference": ("conference", "cmt-edas", "cmt-edas"),
    "human-mouse": ("human-mouse", "human-mouse", "human-mouse"),
    "confOf-ekaw": ("confOf-ekaw", "confOf-ekaw", "confOf-ekaw"),
}


def _find_run_dir(base: Path, label: str) -> Path | None:
    if not base.exists():
        return None
    dirs = sorted(base.glob(f"{label}_*"))
    return dirs[0] if dirs else None


def main() -> None:
    existing_path = HERE / "adjusted_oaei_rejection.csv"
    with existing_path.open() as fh:
        existing_rows = list(csv.DictReader(fh))
    for r in existing_rows:
        if r["method"] == "Proposed":
            r["method"] = GPT_OSS_LABEL

    dataset_args: list[str] = []
    for name, (ds_input, s5_label, s6_label) in DATASETS.items():
        input_dir = REPO / "tests" / "inputs" / ds_input
        ref_path = input_dir / "reference.rdf"
        if not ref_path.exists():
            print(f"  [{name}] no reference.rdf — skipping")
            continue
        s5_dir = _find_run_dir(REPO / "tests" / "scenarios" / "outputs" / "s5" / s5_label, s5_label)
        s6_dir = _find_run_dir(REPO / "tests" / "scenarios" / "outputs" / "s6" / s6_label, s6_label)
        if s5_dir is None or s6_dir is None:
            print(f"  [{name}] missing s5/s6 run dir — skipping")
            continue
        dataset_args += ["--dataset", name, str(ref_path), str(s5_dir), str(s6_dir), str(input_dir)]

    if not dataset_args:
        sys.exit("no datasets with both s5 and s6 deepseek runs available")

    raw_csv = HERE / "_oaei_rejection_deepseek_raw.csv"
    raw_jpg = HERE / "_oaei_rejection_deepseek_raw.jpg"
    subprocess.run(
        [sys.executable, str(HERE / "oaei_rejection.py"),
         *dataset_args, "--no-flag",
         "--out-csv", str(raw_csv), "--out-jpg", str(raw_jpg)],
        check=True, cwd=REPO,
    )

    with raw_csv.open() as fh:
        deepseek_rows = [r for r in csv.DictReader(fh) if r["method"] == "Proposed"]
    for r in deepseek_rows:
        r["method"] = DEEPSEEK_LABEL
    raw_csv.unlink(missing_ok=True)
    raw_jpg.unlink(missing_ok=True)

    rows = existing_rows + deepseek_rows
    out_csv = HERE / "adjusted_oaei_rejection_by_model.csv"
    fieldnames = ["method", "dataset", "reference_total", "aml_total", "rejected_correct", "accepted_aml_fp"]
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_csv} ({len(rows)} rows)")

    # ── chart: same layout as oaei_rejection.py — one row per dataset, two
    # measure columns, all methods (incl. both Proposed variants) as bars.
    methods: list[str] = []
    for r in rows:
        if r["method"] not in methods:
            methods.append(r["method"])
    datasets: list[str] = []
    for r in rows:
        if r["dataset"] not in datasets:
            datasets.append(r["dataset"])
    lookup = {(r["method"], r["dataset"]): r for r in rows}

    BAR_COLOR = "#4472C4"
    PROPOSED_COLOR = {GPT_OSS_LABEL: "#4472C4", DEEPSEEK_LABEL: "#2e8b57"}
    measures = [
        ("rejected_correct", "Rejected correct alignments\n(reference input; lower = better)"),
        ("accepted_aml_fp", "Accepted AML false-positives\n(AML input; lower = better)"),
    ]

    fig, axes = plt.subplots(len(datasets), 2, figsize=(12, 5 * len(datasets)), squeeze=False)
    for di, ds in enumerate(datasets):
        for mi, (metric, title) in enumerate(measures):
            ax = axes[di][mi]
            vals = [lookup.get((m, ds), {}).get(metric) for m in methods]
            colors = [PROPOSED_COLOR.get(m, BAR_COLOR) for m in methods]
            plot_vals = [int(v) if v not in (None, "") else 0 for v in vals]
            bars = ax.bar(methods, plot_vals, color=colors, edgecolor="black", linewidth=0.5)
            labels = ["n/a" if v in (None, "") else str(v) for v in vals]
            ax.bar_label(bars, labels=labels, padding=3)
            ax.axhline(0, color="black", linewidth=0.6)
            ax.set_title(f"{ds} — {title}")
            ax.set_ylabel("count")
            ax.tick_params(axis="x", rotation=20)
            ax.margins(y=0.2)

    fig.suptitle("OAEI reference-alignment validation (Domain Coherence) — by model")
    fig.tight_layout()
    out_jpg = HERE / "adjusted_oaei_rejection_by_model.jpg"
    fig.savefig(out_jpg, dpi=150)
    print(f"wrote {out_jpg}")


if __name__ == "__main__":
    main()
