#!/usr/bin/env python3
"""Draw the stratified sample of relations to be judged by a domain reader.

The automatic classification (classify_relations.py) decides every category
that can be decided mechanically.  What it cannot decide is whether a genuine
concept-to-concept assertion is *true of the domain* — that needs a reader.
This script draws the sample for that step and attaches the evidence needed to
judge each row without opening the ontologies.

Sampling frame: the `judgeable` categories — taxonomic, relational and
nonstandard_predicate (a relation whose IRI landed in the wrong namespace is
still a claim about the domain).  Strata: dataset x measure, six in total,
pooled over the five runs and both models, so a relation's chance of being
drawn is proportional to how often the framework actually produces it.

Evidence columns carry the *source* ontologies' own definitions where they
exist (NCI definitions in human.owl, SWO/ACM annotations), never the merged
ontology's comments — those were written by the model under test and judging
its relations against its own prose would be circular.

Usage:
    uv run python tests/kc_validation/sample_for_review.py \
        --classified tests/kc_validation/data/population_classified.csv \
        --per-stratum 30 --seed 20260728 \
        --out tests/kc_validation/data/sample_to_judge.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics_def import _load_graph  # noqa: E402

JUDGEABLE = {"taxonomic", "relational", "nonstandard_predicate"}

INPUTS = {
    "confOf-ekaw": "tests/inputs/confOf-ekaw",
    "human-mouse": "tests/inputs/human-mouse",
    "swo-acm": "tests/inputs/swo-acm",
}

# Annotation properties carrying a human-readable definition in the sources.
DEF_PREDS = [
    URIRef("http://www.w3.org/2000/01/rdf-schema#comment"),
    URIRef("http://purl.obolibrary.org/obo/IAO_0000115"),
    URIRef("http://www.geneontology.org/formats/oboInOwl#hasDefinition"),
    RDFS.label,
]


def source_index(inputs_dir: str) -> tuple[Graph, dict[str, str]]:
    """Union of the two source ontologies + IRI -> best available definition."""
    g = Graph()
    for owl in sorted(Path(inputs_dir).glob("*.owl")):
        for t in _load_graph(str(owl)):
            g.add(t)
    defs: dict[str, str] = {}
    for pred in DEF_PREDS:
        for s, o in g.subject_objects(pred):
            if isinstance(s, URIRef) and str(s) not in defs:
                text = str(o).strip()
                if len(text) > 3:
                    defs[str(s)] = text[:400]
    return g, defs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classified", required=True)
    ap.add_argument("--per-stratum", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = [
        r for r in csv.DictReader(open(args.classified, encoding="utf-8"))
        if r["category"] in JUDGEABLE
    ]

    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        strata[(r["dataset"], r["measure"])].append(r)

    rng = random.Random(args.seed)
    sample: list[dict] = []
    for key in sorted(strata):
        pool = sorted(
            strata[key],
            key=lambda r: (r["model"], r["run"], r["subject"], r["predicate"], r["object"]),
        )
        n = min(args.per_stratum, len(pool))
        drawn = rng.sample(pool, n)
        print(f"  {key[0]:12s} {key[1]}  pool={len(pool):5d}  drawn={n}")
        sample.extend(drawn)

    defs_by_ds: dict[str, dict[str, str]] = {}
    for ds, path in INPUTS.items():
        if any(r["dataset"] == ds for r in sample):
            print(f"  indexing sources: {ds}")
            _, defs_by_ds[ds] = source_index(path)

    out_fields = [
        "id", "dataset", "model", "run", "measure", "category",
        "redundant_shortcut",
        "subject_label", "predicate_local", "object_label",
        "subject", "predicate", "object",
        "subject_source_definition", "object_source_definition",
        "verdict", "reason", "author_verdict",
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields)
        w.writeheader()
        for i, r in enumerate(sample, 1):
            defs = defs_by_ds.get(r["dataset"], {})
            pl = r["predicate"]
            w.writerow({
                "id": i,
                "dataset": r["dataset"], "model": r["model"], "run": r["run"],
                "measure": r["measure"], "category": r["category"],
                "redundant_shortcut": r["redundant_shortcut"],
                "subject_label": r["subject_label"],
                "predicate_local": pl.split("#")[-1] if "#" in pl else pl.rsplit("/", 1)[-1],
                "object_label": r["object_label"],
                "subject": r["subject"], "predicate": pl, "object": r["object"],
                "subject_source_definition": defs.get(r["subject"], ""),
                "object_source_definition": defs.get(r["object"], ""),
                "verdict": "", "reason": "", "author_verdict": "",
            })
    print(f"\nsample → {out} ({len(sample)} rows)")


if __name__ == "__main__":
    main()
