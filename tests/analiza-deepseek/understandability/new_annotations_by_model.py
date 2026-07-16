#!/usr/bin/env python3
"""Count new rdfs:label/rdfs:comment annotations, by model.

Reuses count_new_annotations.py's per-entity annotation-provenance logic (an
entity's label/comment counts as "new" if the corresponding source entity, via
reverse relabeling_map lookup, had none), run against BOTH:
  - the original scenario_2 (-s2) outputs — gpt-oss-20b via vLLM
  - scenario_5's (s5) outputs for the same 4 datasets — deepseek-v4-flash via OpenRouter

Output: long-format CSV (dataset, model, new_labels, new_comments,
total_labels, total_comments) — one row per (dataset, model). Pure read of
already-computed merged_ontology.owl / relabeling_map.json — no recomputation.
"""

import csv
import json
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

REPO = Path(__file__).resolve().parents[3]

# display dataset -> (tests/inputs folder, owl1, owl2)
DATASETS = {
    "conference-s2": ("conference", "cmt.owl", "edas.owl"),
    "human-mouse-s2": ("human-mouse", "human.owl", "mouse.owl"),
    "acm-union-s2": ("acm-union", "acm.owl", "union.owl"),
    "swo-union-s2": ("swo-union", "swo.owl", "union.owl"),
}

# display dataset -> scenario_5 folder label
S5_LABEL = {
    "conference-s2": "cmt-edas",
    "human-mouse-s2": "human-mouse",
    "acm-union-s2": "acm-union",
    "swo-union-s2": "swo-union",
}


def _local(u: URIRef) -> str:
    s = str(u)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _count(union_dir: Path, f1: str, f2: str, out_dir: Path) -> dict[str, int] | None:
    merged_owl = out_dir / "merged_ontology.owl"
    if not merged_owl.exists():
        return None

    union = Graph()
    union.parse(str(union_dir / f1))
    union.parse(str(union_dir / f2))

    g = Graph()
    g.parse(str(merged_owl))

    rel_path = out_dir / "relabeling_map.json"
    relabeling = json.loads(rel_path.read_text()) if rel_path.exists() else {}
    reverse_rel = {v: k for k, v in relabeling.items()}

    union_label_locals = {
        _local(s) for s, _, _ in union.triples((None, RDFS.label, None)) if isinstance(s, URIRef)
    }
    union_comment_locals = {
        _local(s) for s, _, _ in union.triples((None, RDFS.comment, None)) if isinstance(s, URIRef)
    }

    def had_label(loc: str) -> bool:
        return loc in union_label_locals or reverse_rel.get(loc) in union_label_locals

    def had_comment(loc: str) -> bool:
        return loc in union_comment_locals or reverse_rel.get(loc) in union_comment_locals

    new_labels = new_comments = total_labels = total_comments = 0
    seen_label: set[str] = set()
    seen_comment: set[str] = set()

    for s, _, _ in g.triples((None, RDFS.label, None)):
        if not isinstance(s, URIRef):
            continue
        loc = _local(s)
        if loc in seen_label:
            continue
        seen_label.add(loc)
        total_labels += 1
        if not had_label(loc):
            new_labels += 1

    for s, _, _ in g.triples((None, RDFS.comment, None)):
        if not isinstance(s, URIRef):
            continue
        loc = _local(s)
        if loc in seen_comment:
            continue
        seen_comment.add(loc)
        total_comments += 1
        if not had_comment(loc):
            new_comments += 1

    return {
        "new_labels": new_labels,
        "new_comments": new_comments,
        "total_labels": total_labels,
        "total_comments": total_comments,
    }


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("new_annotations_by_model.csv")
    rows = []
    for ds, (ds_input, f1, f2) in DATASETS.items():
        inputs = REPO / "tests" / "inputs" / ds_input

        gptoss_dir = REPO / "tests" / "scenarios" / "outputs" / ds / f"{ds}_aml_15k_p24"
        r = _count(inputs, f1, f2, gptoss_dir)
        if r:
            rows.append({"dataset": ds, "model": "gpt-oss-20b", **r})
        else:
            print(f"  WARNING: {gptoss_dir}/merged_ontology.owl missing — skipping gpt-oss-20b/{ds}")

        s5_label = S5_LABEL[ds]
        s5_base = REPO / "tests" / "scenarios" / "outputs" / "s5" / s5_label
        s5_dirs = sorted(s5_base.glob(f"{s5_label}_*")) if s5_base.exists() else []
        if not s5_dirs:
            print(f"  WARNING: no s5 run dir found for {s5_label} — skipping deepseek-v4-flash/{ds}")
            continue
        r = _count(inputs, f1, f2, s5_dirs[0])
        if r:
            rows.append({"dataset": ds, "model": "deepseek-v4-flash", **r})
        else:
            print(f"  WARNING: {s5_dirs[0]}/merged_ontology.owl missing — skipping deepseek-v4-flash/{ds}")

    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "model", "new_labels", "new_comments", "total_labels", "total_comments"])
        for r in rows:
            w.writerow([r["dataset"], r["model"], r["new_labels"], r["new_comments"],
                        r["total_labels"], r["total_comments"]])
            print(f"  {r['dataset']}/{r['model']}: new_labels={r['new_labels']}, "
                  f"new_comments={r['new_comments']}, total_labels={r['total_labels']}, "
                  f"total_comments={r['total_comments']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
