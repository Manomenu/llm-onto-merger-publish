#!/usr/bin/env python3
"""Combine the existing (gpt-oss-20b, logs/app.log-derived) error_rate.csv with
a deepseek-v4-flash variant computed from scenario_5's per-dataset run.log
files (AML-input, same scope as the original: conference + human-mouse).

Reuses error_rate.py's parse_log/classify functions unchanged — pure log
parsing, no LLM/tool re-invocation.
"""

import csv
import importlib.util
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]

spec = importlib.util.spec_from_file_location("error_rate", HERE / "error_rate.py")
error_rate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(error_rate)  # type: ignore[union-attr]

# display dataset -> scenario_5 folder label
S5_LABEL = {"conference": "cmt-edas", "human-mouse": "human-mouse"}


def _s5_run_log(label: str) -> Path | None:
    base = REPO / "tests" / "scenarios" / "outputs" / "s5" / label
    dirs = sorted(base.glob(f"{label}_*")) if base.exists() else []
    return (dirs[0] / "run.log") if dirs and (dirs[0] / "run.log").exists() else None


def main() -> None:
    gptoss_csv = HERE / "error_rate.csv"
    with gptoss_csv.open() as fh:
        gptoss_rows = list(csv.DictReader(fh))
    for r in gptoss_rows:
        r["model"] = "gpt-oss-20b"

    deepseek_rows = []
    logs = [p for ds in S5_LABEL.values() if (p := _s5_run_log(ds)) is not None]
    if not logs:
        print("  WARNING: no scenario_5 run.log files found — deepseek rows will be empty")
    else:
        tmp_log = HERE / "_s5_combined.log"
        with tmp_log.open("w", encoding="utf-8") as out:
            for p in logs:
                out.write(p.read_text(encoding="utf-8", errors="replace"))
        runs = error_rate.parse_log(tmp_log)
        tmp_log.unlink()
        for ds in S5_LABEL:
            info = runs.get(ds)
            if info is None:
                print(f"  WARNING: no run found for '{ds}' in scenario_5 logs")
                continue
            c = error_rate.classify(info)
            deepseek_rows.append({"dataset": ds, "model": "deepseek-v4-flash", **c})
            print(f"  [{ds}] deepseek: {c['real_failures']}/{c['total_environments']} "
                  f"REAL failures -> {c['real_error_rate_pct']}%")

    fieldnames = ["dataset", "model", "total_environments", "real_failures",
                  "degenerate_empty_input", "parse_fail", "empty_graph_total",
                  "other_error", "real_error_rate_pct"]
    out_csv = HERE / "error_rate_by_model.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(gptoss_rows + deepseek_rows)
    print(f"wrote {out_csv}")

    rows = gptoss_rows + deepseek_rows
    datasets = list(dict.fromkeys(r["dataset"] for r in rows))
    models = list(dict.fromkeys(r["model"] for r in rows))
    lookup = {(r["dataset"], r["model"]): r for r in rows}

    fig, ax = plt.subplots(figsize=(8, 5))
    width = 0.35
    x = range(len(datasets))
    colors = {"gpt-oss-20b": "#4472C4", "deepseek-v4-flash": "#2e8b57"}
    for i, model in enumerate(models):
        vals = [float(lookup.get((ds, model), {}).get("real_error_rate_pct") or 0) for ds in datasets]
        offset = (i - (len(models) - 1) / 2) * width
        bars = ax.bar([xi + offset for xi in x], vals, width, label=model, color=colors.get(model, "#888"))
        ax.bar_label(bars, fmt="%.1f%%", padding=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(datasets)
    ax.set_title("LLM merge REAL error rate per dataset, by model\nreal failures / total envs")
    ax.set_ylabel("real error rate [%]")
    ax.legend()
    ax.margins(y=0.2)
    fig.tight_layout()
    out_jpg = HERE / "error_rate_by_model.jpg"
    fig.savefig(out_jpg, dpi=150)
    print(f"wrote {out_jpg}")


if __name__ == "__main__":
    main()
