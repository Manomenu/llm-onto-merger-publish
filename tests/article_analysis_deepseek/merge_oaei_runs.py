#!/usr/bin/env python3
"""Merge one turn's gpt-oss and deepseek oaei_rejection.py CSVs into one.

Input CSVs have rows: method,dataset,reference_total,aml_total,
rejected_correct,accepted_aml_fp.  The merged output keeps every gpt-oss row
(its "Proposed" method renamed to "Proposed: gpt-oss" — the baselines AROM/
CoMerger/Boomer are identical in both runs, so they are taken from the
gpt-oss side only) and appends, per dataset, the deepseek run's "Proposed"
row renamed to "Proposed: deepseek-v4-flash".
"""

import argparse
import csv
from pathlib import Path

GPT_OSS_LABEL = "Proposed: gpt-oss"
DEEPSEEK_LABEL = "Proposed: deepseek-v4-flash"
FIELDS = ["method", "dataset", "reference_total", "aml_total",
          "rejected_correct", "accepted_aml_fp"]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gptoss", required=True, type=Path,
                        help="oaei_rejection.py CSV from the gpt-oss (s2/s3) runs")
    parser.add_argument("--deepseek", required=True, type=Path,
                        help="oaei_rejection.py CSV from the deepseek (s5/s6) runs")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    deepseek_proposed = {
        row["dataset"]: row
        for row in _read(args.deepseek) if row["method"] == "Proposed"
    }

    out_rows: list[dict[str, str]] = []
    seen_datasets: list[str] = []
    for row in _read(args.gptoss):
        if row["method"] == "Proposed":
            row = {**row, "method": GPT_OSS_LABEL}
        out_rows.append(row)
        if row["dataset"] not in seen_datasets:
            seen_datasets.append(row["dataset"])
    for ds in seen_datasets:
        if ds in deepseek_proposed:
            out_rows.append({**deepseek_proposed[ds], "method": DEEPSEEK_LABEL})
        else:
            print(f"  WARNING: deepseek OAEI CSV has no Proposed row for '{ds}'")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in FIELDS} for r in out_rows)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
