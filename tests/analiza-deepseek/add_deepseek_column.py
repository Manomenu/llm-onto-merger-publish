#!/usr/bin/env python3
"""Augment an existing tests/analiza raw per-metric CSV (rows=dataset-s2,
cols=method) with a second "Proposed" column for the DeepSeek run.

Renames the existing "Our Solution" column to "Proposed gpt-oss-20b" (the
model that produced tests/analiza's original data, per .env's VLLM_MODEL) and
appends "Proposed deepseek-v4-flash", read from scenario_5's already-computed
m_i_raport_<label>.csv (graph=merged_ontology) — no recomputation, pure read.
"""

import argparse
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCEN_OUT = REPO / "tests" / "scenarios" / "outputs"

# dataset-s2 label (as used in tests/analiza raw CSVs) -> scenario_5 folder label
S5_LABEL = {
    "conference-s2": "cmt-edas",
    "human-mouse-s2": "human-mouse",
    "acm-union-s2": "acm-union",
    "swo-union-s2": "swo-union",
}

GPT_OSS_COL = "Our Solution"
GPT_OSS_LABEL = "Proposed gpt-oss-20b"
DEEPSEEK_LABEL = "Proposed deepseek-v4-flash"


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open() as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def deepseek_value(metric: str, label: str) -> str:
    p = SCEN_OUT / "s5" / label / f"m_i_raport_{label}.csv"
    if not p.exists():
        return ""
    with p.open() as fh:
        lines = [ln for ln in fh if not ln.lstrip().lstrip('"').startswith('#')]
    for row in csv.DictReader(lines):
        if (
            row.get("section") == "metrics"
            and row.get("metric") == metric
            and row.get("graph") == "merged_ontology"
        ):
            return row.get("value", "")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metric", required=True,
        help="metric name as it appears in m_i_raport (e.g. triple_preservation_ratio)",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    header, rows = read_csv(args.input)
    header = [(GPT_OSS_LABEL if h == GPT_OSS_COL else h) for h in header]
    header.append(DEEPSEEK_LABEL)

    out_rows = []
    for row in rows:
        ds = row[0]
        label = S5_LABEL.get(ds)
        val = deepseek_value(args.metric, label) if label else ""
        out_rows.append(row + [val])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(out_rows)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
