#!/usr/bin/env python3
"""Build a full merged ontology by applying Boomer's accepted equivalences to the source ontologies.

Boomer's raw output (after OFN→RDF/XML conversion via owltools) contains only:
  - class declarations for every entity in either source ontology
  - owl:equivalentClass triples for the mappings Boomer accepted
  - (optionally) rdfs:subClassOf for accepted subclass mappings

It does NOT carry source-ontology axioms (properties, comments, type assertions, …),
so it scores ~0% on triple_preservation_ratio and 0% on annotation_coverage_ratio
as a standalone artifact — unfair vs LLM merge.

This script makes Boomer's output comparable: treats each owl:equivalentClass
in the Boomer output as an alignment (measure=1.0, relation="="), then calls
collapse_alignments_to_merged_ns — each accepted pair is collapsed into a new
merged# entity carrying triples from both source entities.  Non-aligned entities
keep their original namespaces.

Accepted subClassOf axioms from Boomer are added on top (with URIs remapped to merged#).

Usage:
    uv run python apply_boomer.py \\
        --onto1 path/to/onto1.owl \\
        --onto2 path/to/onto2.owl \\
        --boomer-raw path/to/boomer_raw.owl \\
        --output path/to/merged_ontology.owl
"""

import argparse
import json
import sys
from pathlib import Path

from rdflib import RDFS, Graph, URIRef
from rdflib.namespace import OWL

from llm_onto_merger.alignment.alignment import Alignment
from llm_onto_merger.ontology import collapse_alignments_to_merged_ns
from llm_onto_merger.ontology.uri import local_name
from llm_onto_merger.ontology.merge import _MERGED_NS


def _extract_equiv_pairs(g: Graph) -> list[tuple[str, str]]:
    return [
        (str(s), str(o))
        for s, _, o in g.triples((None, OWL.equivalentClass, None))
        if isinstance(s, URIRef) and isinstance(o, URIRef)
    ]


def _extract_subclass_triples(g: Graph) -> list[tuple[URIRef, URIRef]]:
    return [
        (s, o)
        for s, _, o in g.triples((None, RDFS.subClassOf, None))
        if isinstance(s, URIRef) and isinstance(o, URIRef)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onto1", required=True, type=Path)
    parser.add_argument("--onto2", required=True, type=Path)
    parser.add_argument(
        "--boomer-raw",
        required=True,
        type=Path,
        help="Boomer's OWL output already converted to RDF/XML by owltools.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    for f in (args.onto1, args.onto2, args.boomer_raw):
        if not f.exists():
            sys.exit(f"Not found: {f}")

    print(f"[apply_boomer] loading source ontologies …")
    onto1 = Graph()
    onto1.parse(str(args.onto1))
    onto2 = Graph()
    onto2.parse(str(args.onto2))
    print(f"  onto1: {len(onto1)} triples")
    print(f"  onto2: {len(onto2)} triples")

    boomer_raw = Graph()
    boomer_raw.parse(str(args.boomer_raw))
    print(f"  boomer_raw: {len(boomer_raw)} triples")

    equiv_pairs = _extract_equiv_pairs(boomer_raw)
    print(f"[apply_boomer] extracted {len(equiv_pairs)} equivalentClass pairs")

    alignments = [
        Alignment(entity1=e1, entity2=e2, measure=1.0, relation="=")
        for e1, e2 in equiv_pairs
    ]
    result, provenance = collapse_alignments_to_merged_ns(onto1, onto2, alignments)
    print(f"  after collapse_alignments_to_merged_ns: {len(result)} triples")

    # canon maps both e1 and e2 to their merged# URI for subClassOf rewriting
    canon: dict[URIRef, URIRef] = {}
    for e1_str, e2_str in equiv_pairs:
        e1 = URIRef(e1_str)
        new_uri = URIRef(f"{_MERGED_NS}{local_name(e1)}")
        canon[e1] = new_uri
        canon[URIRef(e2_str)] = new_uri

    subclass_triples = _extract_subclass_triples(boomer_raw)
    added_sub = 0
    for s, o in subclass_triples:
        s_canon = canon.get(s, s)
        o_canon = canon.get(o, o)
        triple = (s_canon, RDFS.subClassOf, o_canon)
        if triple not in result:
            result.add(triple)
            added_sub += 1
    if added_sub:
        print(f"  added {added_sub} Boomer-accepted subClassOf axioms")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.serialize(destination=str(args.output), format="xml")
    print(f"[apply_boomer] saved → {args.output} ({len(result)} triples)")

    stats_path = args.output.parent / "boomer_stats.json"
    stats_path.write_text(
        json.dumps(
            {
                "accepted_equiv_count": len(equiv_pairs),
                "accepted_subclass_count": len(subclass_triples),
                "code_provenance": provenance,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[apply_boomer] sidecar  → {stats_path}")


if __name__ == "__main__":
    main()
