#!/usr/bin/env python3
"""Dump the individual triples counted by NCRC and NIRC.

`tests/metrics_def.py` reports Knowledge Completeness as two *counts*
(new_cross_onto_relations_count / new_intra_onto_relations_count).  This script
re-runs the very same predicates and writes out the underlying triples, so the
relations behind the numbers can be inspected and judged one by one.

The selection logic below is copied verbatim from
`metrics_def._compute_self_metrics` (the `new_cross_rel` / `new_intra_rel`
comprehensions and every helper they close over).  It imports the private
helpers rather than reimplementing them, and asserts that the number of
extracted triples equals the count `_compute_self_metrics` returns for the same
inputs — so a future divergence fails loudly instead of silently producing a
different population.

Run with PYTHONHASHSEED=0: `_build_alias_maps` iterates over sets, and the
reported NCRC/NIRC figures were computed under that seed.

Usage:
    PYTHONHASHSEED=0 uv run python tests/kc_validation/extract_new_relations.py \
        --inputs tests/inputs/confOf-ekaw \
        --merged  .../merged_ontology.owl \
        --dataset confOf-ekaw --model gpt-oss --run turn1 \
        --out tests/kc_validation/data/population.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics_def import (  # noqa: E402
    _build_alias_maps,
    _canon_key,
    _compute_self_metrics,
    _load_graph,
    _local,
    _primary_ns,
)

FIELDS = [
    "dataset",
    "model",
    "run",
    "measure",
    "subject",
    "subject_label",
    "predicate",
    "object",
    "object_label",
    "subject_source",
    "object_source",
    "merged_path",
]


def _label(g: Graph, u: URIRef) -> str:
    """Human-readable name: rdfs:label if present, else the local name."""
    for o in g.objects(u, RDFS.label):
        return str(o)
    return _local(u)


def extract(
    merged: Graph,
    union: Graph,
    onto1_entities: set[URIRef],
    onto2_entities: set[URIRef],
    relabeling_map: dict[str, str] | None,
) -> tuple[list[tuple], list[tuple]]:
    """Return (cross_triples, intra_triples) — the exact triples NCRC/NIRC count."""
    onto1_locals = {_local(e) for e in onto1_entities}
    onto2_locals = {_local(e) for e in onto2_entities}

    _, new_to_source, _ = _build_alias_maps(
        merged, onto1_locals, onto2_locals, arom_provenance=None,
        relabeling_map=relabeling_map,
    )
    onto1_ns = _primary_ns(onto1_entities)
    onto2_ns = _primary_ns(onto2_entities)

    # ── copied from metrics_def._compute_self_metrics ────────────────────────
    def _from_onto1(u) -> bool:
        if not isinstance(u, URIRef):
            return False
        if u in onto1_entities:
            return True
        if u in onto2_entities:
            return False
        s = str(u)
        if onto1_ns and s.startswith(onto1_ns) and not (onto2_ns and s.startswith(onto2_ns)):
            return True
        if onto2_ns and s.startswith(onto2_ns):
            return False
        return new_to_source.get(_local(u)) in ("onto1", "both")

    def _from_onto2(u) -> bool:
        if not isinstance(u, URIRef):
            return False
        if u in onto2_entities:
            return True
        if u in onto1_entities:
            return False
        s = str(u)
        if onto2_ns and s.startswith(onto2_ns) and not (onto1_ns and s.startswith(onto1_ns)):
            return True
        if onto1_ns and s.startswith(onto1_ns):
            return False
        return new_to_source.get(_local(u)) in ("onto2", "both")

    def _is_cross(s, o) -> bool:
        s1, s2 = _from_onto1(s), _from_onto2(s)
        o1, o2 = _from_onto1(o), _from_onto2(o)
        if (s1 and s2) and (o1 and o2):
            return False
        if (s1 and not s2) and (o1 and not o2):
            return False
        if (s2 and not s1) and (o2 and not o1):
            return False
        return (s1 and o2) or (s2 and o1)

    old_to_new, _, uri_to_new_local = _build_alias_maps(
        merged, onto1_locals, onto2_locals, arom_provenance=None,
        relabeling_map=relabeling_map,
    )

    def _norm(local: str) -> str:
        return old_to_new.get(local, local)

    def _norm_uri(u) -> str:
        if isinstance(u, URIRef):
            return uri_to_new_local.get(str(u), _norm(_local(u)))
        return str(u)

    union_keys_norm = {
        _canon_key(p, _norm_uri(s), _norm_uri(p), _norm_uri(o))
        for s, p, o in union
        if isinstance(s, URIRef) and isinstance(o, URIRef)
    }
    union_raw = {
        (_local(s), _local(p), _local(o))
        for s, p, o in union
        if isinstance(s, URIRef) and isinstance(o, URIRef)
    }

    def _raw_key(s, p, o):
        return (_local(s), _local(p), _local(o))

    def _is_both(u) -> bool:
        return isinstance(u, URIRef) and new_to_source.get(_local(u)) == "both"

    def _intra_source(u) -> str | None:
        if not isinstance(u, URIRef):
            return None
        if u in onto1_entities:
            return "onto1"
        if u in onto2_entities:
            return "onto2"
        s = str(u)
        if onto1_ns and s.startswith(onto1_ns) and not (onto2_ns and s.startswith(onto2_ns)):
            return "onto1"
        if onto2_ns and s.startswith(onto2_ns) and not (onto1_ns and s.startswith(onto1_ns)):
            return "onto2"
        loc = _local(u)
        src = new_to_source.get(loc)
        if src in ("onto1", "onto2"):
            return src
        if src == "both":
            if loc in onto1_locals:
                return "onto1"
            if loc in onto2_locals:
                return "onto2"
        return None
    # ── end copy ─────────────────────────────────────────────────────────────

    intra = [
        (s, p, o, _intra_source(s), _intra_source(o))
        for s, p, o in merged
        if isinstance(s, URIRef)
        and isinstance(o, URIRef)
        and not (_is_both(s) and _is_both(o))
        and _intra_source(s) is not None
        and _intra_source(s) == _intra_source(o)
        and _canon_key(p, _local(s), _local(p), _local(o)) not in union_keys_norm
        and _raw_key(s, p, o) not in union_raw
    ]
    cross = [
        (
            s, p, o,
            "onto1" if _from_onto1(s) and not _from_onto2(s) else
            "onto2" if _from_onto2(s) and not _from_onto1(s) else "both",
            "onto1" if _from_onto1(o) and not _from_onto2(o) else
            "onto2" if _from_onto2(o) and not _from_onto1(o) else "both",
        )
        for s, p, o in merged
        if isinstance(s, URIRef) and isinstance(o, URIRef)
        and _is_cross(s, o)
        and _canon_key(p, _local(s), _local(p), _local(o)) not in union_keys_norm
        and _raw_key(s, p, o) not in union_raw
    ]
    return cross, intra


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True, help="dir with exactly 2 source .owl files")
    ap.add_argument("--merged", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True, help="CSV to append to (header written if new)")
    args = ap.parse_args()

    owl_files = sorted(Path(args.inputs).glob("*.owl"))
    if len(owl_files) != 2:
        sys.exit(f"expected 2 .owl in {args.inputs}, found {len(owl_files)}")

    onto1 = _load_graph(str(owl_files[0]))
    onto2 = _load_graph(str(owl_files[1]))
    union = Graph()
    for t in onto1:
        union.add(t)
    for t in onto2:
        union.add(t)
    onto1_entities = {s for s, _, _ in onto1 if isinstance(s, URIRef)}
    onto2_entities = {s for s, _, _ in onto2 if isinstance(s, URIRef)}

    merged_path = Path(args.merged)
    merged = _load_graph(str(merged_path))
    relabeling_path = merged_path.parent / "relabeling_map.json"
    relabeling_map = (
        json.loads(relabeling_path.read_text(encoding="utf-8"))
        if relabeling_path.exists()
        else None
    )

    cross, intra = extract(merged, union, onto1_entities, onto2_entities, relabeling_map)

    # Guard: the extracted populations must have exactly the reported cardinality.
    ref = _compute_self_metrics(
        merged, onto1_entities, onto2_entities, union, relabeling_map=relabeling_map
    )
    assert len(cross) == int(ref["new_cross_onto_relations_count"]), (
        f"NCRC mismatch: extracted {len(cross)} vs reported "
        f"{ref['new_cross_onto_relations_count']}"
    )
    assert len(intra) == int(ref["new_intra_onto_relations_count"]), (
        f"NIRC mismatch: extracted {len(intra)} vs reported "
        f"{ref['new_intra_onto_relations_count']}"
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out.exists()
    with out.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if write_header:
            w.writerow(FIELDS)
        for measure, rows in (("NCRC", cross), ("NIRC", intra)):
            for s, p, o, s_src, o_src in rows:
                w.writerow([
                    args.dataset, args.model, args.run, measure,
                    str(s), _label(merged, s),
                    str(p),
                    str(o), _label(merged, o),
                    s_src, o_src, args.merged,
                ])

    print(
        f"{args.dataset}/{args.model}/{args.run}: "
        f"NCRC={len(cross)} NIRC={len(intra)} → {out}"
    )


if __name__ == "__main__":
    main()
