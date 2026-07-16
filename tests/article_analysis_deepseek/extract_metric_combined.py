#!/usr/bin/env python3
"""Extract a single metric across datasets into a combined two-backend CSV.

Rows = datasets, columns = methods.  The baseline columns and the gpt-oss
"Proposed" value come from the gpt-oss report tree (article_analysis_gptoss's
per-turn work/source/<turn>/ view, where the merged_ontology graph IS the
gpt-oss run); the extra "Proposed: deepseek-v4-flash" column is the
merged_ontology value read from the deepseek report tree
(tests/article_scenarios/outputs/<turn>/s5).  Both trees use the same
display-label naming: <root>/<dataset>/m_i_raport_<dataset>.csv.
"""

import argparse
import csv
import sys
from pathlib import Path

GPT_OSS_GRAPH_TO_METHOD = {
    "union_input":         "Naive Union",
    "applied_alignments":  "Applied Alignments",
    "arom_ontology":       "AROM",
    "comerger_ontology":   "CoMerger",
    "boomer_ontology":     "Boomer",
    "merged_ontology":     "Proposed: gpt-oss",
}
DEEPSEEK_METHOD = "Proposed: deepseek-v4-flash"
METHOD_ORDER = [
    "Naive Union", "Applied Alignments", "AROM",
    "CoMerger", "Boomer", "Proposed: gpt-oss", DEEPSEEK_METHOD,
]


def _metric_by_graph(csv_path: Path, metric: str) -> dict[str, str]:
    """Return {graph: value} for one metric from an m_i_raport CSV."""
    if not csv_path.exists():
        sys.exit(f"missing: {csv_path}")
    with csv_path.open() as fh:
        lines = [ln for ln in fh if not ln.lstrip().lstrip('"').startswith('#')]
    out: dict[str, str] = {}
    for row in csv.DictReader(lines):
        if row.get("section") == "metrics" and row.get("metric") == metric:
            out[row.get("graph", "")] = row.get("value", "")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gptoss-root", required=True, type=Path,
                        help="per-turn gpt-oss view (article_analysis_gptoss/work/source/<turn>)")
    parser.add_argument("--deepseek-root", required=True, type=Path,
                        help="per-turn deepseek tree (tests/article_scenarios/outputs/<turn>/s5)")
    parser.add_argument("--metric", required=True)
    parser.add_argument("--datasets", nargs="+", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.output.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["dataset", *METHOD_ORDER])
        for ds in args.datasets:
            gpt = _metric_by_graph(args.gptoss_root / ds / f"m_i_raport_{ds}.csv",
                                   args.metric)
            dseek = _metric_by_graph(args.deepseek_root / ds / f"m_i_raport_{ds}.csv",
                                     args.metric)
            vals = {m: gpt.get(g, "") for g, m in GPT_OSS_GRAPH_TO_METHOD.items()}
            vals[DEEPSEEK_METHOD] = dseek.get("merged_ontology", "")
            writer.writerow([ds, *(vals.get(m, "") for m in METHOD_ORDER)])

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
