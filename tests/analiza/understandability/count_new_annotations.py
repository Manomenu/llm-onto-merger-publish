#!/usr/bin/env python3
"""Count rdfs:label and rdfs:comment annotations newly introduced by Our Solution.

For each entity E in merged_ontology.owl that carries an rdfs:label/comment,
resolve the corresponding source entity via the LLM relabeling_map (reverse
lookup: new_local → old_local).  If the source entity has NO label / NO comment
in the union, the annotation is genuinely added by the LLM.

Output: CSV with rows = datasets, columns = (new_labels, new_comments,
total_labels_os, total_comments_os).
"""

import csv
import json
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

REPO = Path(__file__).resolve().parents[3]
DATASETS = {
    "conference-s2":   ("conference",  "cmt.owl",   "edas.owl"),
    "human-mouse-s2":  ("human-mouse", "human.owl", "mouse.owl"),
    "acm-union-s2":    ("acm-union",   "acm.owl",   "union.owl"),
    "swo-union-s2":    ("swo-union",   "swo.owl",   "union.owl"),
}


def _local(u: URIRef) -> str:
    s = str(u)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def count_for(dataset: str) -> dict[str, int]:
    ds_input, f1, f2 = DATASETS[dataset]
    inputs = REPO / "tests" / "inputs" / ds_input
    out_dir = REPO / "tests" / "scenarios" / "outputs" / dataset / f"{dataset}_aml_15k_p24"

    union = Graph()
    union.parse(str(inputs / f1))
    union.parse(str(inputs / f2))

    g = Graph()
    g.parse(str(out_dir / "merged_ontology.owl"))

    rel_path = out_dir / "relabeling_map.json"
    relabeling = json.loads(rel_path.read_text()) if rel_path.exists() else {}
    # Reverse: new_local → old_local (for resolving OS entity to source coded name)
    reverse_rel = {v: k for k, v in relabeling.items()}

    # Build source annotation index by local name (covers renamed entities)
    union_label_locals: set[str] = set()
    union_comment_locals: set[str] = set()
    for s, p, _ in union.triples((None, RDFS.label, None)):
        if isinstance(s, URIRef):
            union_label_locals.add(_local(s))
    for s, p, _ in union.triples((None, RDFS.comment, None)):
        if isinstance(s, URIRef):
            union_comment_locals.add(_local(s))

    def had_label(os_local: str) -> bool:
        if os_local in union_label_locals:
            return True
        old = reverse_rel.get(os_local)
        return old in union_label_locals if old else False

    def had_comment(os_local: str) -> bool:
        if os_local in union_comment_locals:
            return True
        old = reverse_rel.get(os_local)
        return old in union_comment_locals if old else False

    new_labels = 0
    new_comments = 0
    total_labels = 0
    total_comments = 0
    seen_label = set()
    seen_comment = set()

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
        "new_labels":     new_labels,
        "new_comments":   new_comments,
        "total_labels":   total_labels,
        "total_comments": total_comments,
    }


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("new_annotations_os.csv")
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "new_labels", "new_comments", "total_labels_os", "total_comments_os"])
        for ds in DATASETS:
            r = count_for(ds)
            w.writerow([ds, r["new_labels"], r["new_comments"], r["total_labels"], r["total_comments"]])
            print(f"  {ds}: new_labels={r['new_labels']}, new_comments={r['new_comments']}, "
                  f"total_labels={r['total_labels']}, total_comments={r['total_comments']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
