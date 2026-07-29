#!/usr/bin/env python3
"""Classify every relation counted by NCRC/NIRC into a rule-based category.

NCRC and NIRC are volume measures: they count triples that are new with respect
to the union input.  Being new is not the same as being domain knowledge, so
this script partitions the whole population (no sampling) into categories that
can be decided mechanically, leaving one residual category — `relational` /
`taxonomic` — whose members are genuine concept-to-concept assertions and can
only be judged by a domain reader.

Categories, first match wins:

  vacuous_selfloop     subject == object; carries no information
  provenance           framework housekeeping predicate (merged#alias)
  nonconcept_endpoint  an endpoint is not a concept: an OBO annotation holder
                       (…#genidNNN), a placeholder minted for an anonymous class
                       expression, or annotation text serialized as an IRI
  owl_vocabulary       an endpoint is owl:Thing (or the merged copy of it)
  prompt_leakage       an endpoint is a class the model minted out of the
                       prompt's own structure rather than the domain (the
                       KG2Code environment is rendered with [Border_1] /
                       [Border_2] sections; `BorderEntity` is that header
                       reified as a class)
  annotation           annotation property (synonym / definition / label /
                       comment / definition-source): metadata, not a relation
  class_as_predicate   the predicate is not a property at all — a class or an
                       annotation holder used in predicate position
  nonstandard_predicate
                       a relation whose meaning is fine but whose IRI was
                       invented inside a reserved namespace (e.g. rdfs:partOf,
                       oboInOwl:partOf, rdf:subClassOf)
  equivalence          equivalentClass / sameAs / exactMatch: restates the
                       alignment rather than adding to it
  schema_axiom         rdfs:domain / rdfs:range / rdfs:subPropertyOf / rdf:type
  taxonomic            rdfs:subClassOf between two concepts
  relational           any other object property between two concepts

`taxonomic` rows additionally get `redundant_shortcut=1` when the merged
ontology already derives the same subsumption through a different path, i.e.
the edge is entailed by the rest of the graph and adds no new subsumption.

Usage:
    uv run python tests/kc_validation/classify_relations.py \
        --population tests/kc_validation/data/population.csv \
        --out        tests/kc_validation/data/population_classified.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

from rdflib import URIRef

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics_def import _load_graph  # noqa: E402

RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
OWL_NS = "http://www.w3.org/2002/07/owl#"
OBO_IN_OWL_NS = "http://www.geneontology.org/formats/oboInOwl#"
SUBCLASSOF = RDFS_NS + "subClassOf"

# Real terms of the reserved vocabularies.  Anything else minted inside these
# namespaces is an invented term (the model writing e.g. rdfs:partOf).
RDFS_TERMS = {
    "subClassOf", "subPropertyOf", "domain", "range", "label", "comment",
    "seeAlso", "isDefinedBy", "member", "Class", "Literal", "Datatype",
    "Resource", "Container", "ContainerMembershipProperty",
}
RDF_TERMS = {
    "type", "first", "rest", "value", "subject", "predicate", "object",
    "Property", "Statement", "Bag", "Seq", "Alt", "List", "nil", "langString",
}
OWL_TERMS = {
    "sameAs", "differentFrom", "equivalentClass", "equivalentProperty",
    "disjointWith", "inverseOf", "onProperty", "someValuesFrom",
    "allValuesFrom", "hasValue", "cardinality", "minCardinality",
    "maxCardinality", "intersectionOf", "unionOf", "complementOf", "oneOf",
    "imports", "versionInfo", "Thing", "Nothing", "Class", "Restriction",
    "ObjectProperty", "DatatypeProperty", "AnnotationProperty", "Ontology",
    "TransitiveProperty", "SymmetricProperty", "FunctionalProperty",
    "InverseFunctionalProperty", "topObjectProperty", "annotatedSource",
}
OBO_IN_OWL_TERMS = {
    "hasRelatedSynonym", "hasExactSynonym", "hasNarrowSynonym",
    "hasBroadSynonym", "hasSynonym", "hasDefinition", "hasDbXref",
    "hasOBONamespace", "id", "inSubset", "Synonym", "SynonymType",
}

# Annotation properties: metadata about a concept, not a relation between two.
ANNOTATION_LOCALS = {
    "hasRelatedSynonym", "hasExactSynonym", "hasNarrowSynonym",
    "hasBroadSynonym", "hasSynonym", "hasDefinedSyonym", "has-relatedSynonym",
    "hasRelevantSynonym", "hasDefinition", "hasMeaning", "hasDbXref",
    "label", "comment", "seeAlso", "isDefinedBy",
    "IAO_0000115", "IAO_0000119", "IAO_0100001",  # definition, def. source, replaced_by
}
EQUIVALENCE_LOCALS = {
    "equivalentClass", "equivalentProperty", "equivalentTo", "sameAs",
    "exactMatch", "closeMatch", "correspondsTo",
}
SCHEMA_LOCALS = {"domain", "range", "subPropertyOf", "type"}
PROVENANCE_LOCALS = {"alias", "isAliasFor"}

_GENID = re.compile(r"#genid\d+$")
_PLACEHOLDER = re.compile(r"#N[0-9a-f]{32}$")
_OWL_THING = {OWL_NS + "Thing", "http://merged#Thing", OWL_NS + "Nothing"}
# Opaque identifiers (SWO_0000131, IAO_0000115, NCI_C12345, RO_0002131): a
# capitalised local name here is an identifier scheme, not a class name.
_OPAQUE_ID = re.compile(r"^[A-Za-z]{2,}[_:]\d+$")
# Classes the model minted from the prompt's own section headers, not the domain.
_PROMPT_VOCABULARY = {"BorderEntity"}


def _local(uri: str) -> str:
    return uri.split("#")[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


def _ns(uri: str) -> str:
    return uri[: uri.rindex("#") + 1] if "#" in uri else uri[: uri.rindex("/") + 1]


def _is_text_as_iri(uri: str) -> bool:
    """An annotation value (definition, synonym text) serialized as an IRI.

    The merged serializer turns some literal objects into IRIs inside a source
    namespace; the result is a whole sentence in the local name.  Detected by
    length plus sentence shape (many words, or terminal punctuation).
    """
    loc = _local(uri)
    if len(loc) < 40:
        return False
    words = loc.count("_") + loc.count("%20") + loc.count(" ")
    return words >= 5 or loc.rstrip().endswith((".", ";", ",", ":"))


def _nonconcept(uri: str) -> bool:
    return bool(_GENID.search(uri) or _PLACEHOLDER.search(uri)) or _is_text_as_iri(uri)


def _nonstandard_predicate(pred: str) -> bool:
    """A term invented inside a namespace whose vocabulary is fixed."""
    loc, ns = _local(pred), _ns(pred)
    if ns == RDFS_NS:
        return loc not in RDFS_TERMS
    if ns == RDF_NS:
        return loc not in RDF_TERMS
    if ns == OWL_NS:
        return loc not in OWL_TERMS
    if ns == OBO_IN_OWL_NS:
        return loc not in OBO_IN_OWL_TERMS
    return False


def _class_as_predicate(pred: str) -> bool:
    """The predicate slot holds something that is not a property."""
    if _GENID.search(pred) or _PLACEHOLDER.search(pred):
        return True
    loc = _local(pred)
    if _OPAQUE_ID.match(loc):  # SWO_0000131 and friends are real properties
        return False
    return bool(loc[:1].isupper()) or loc == "owl"


def classify(row: dict) -> str:
    s, p, o = row["subject"], row["predicate"], row["object"]
    ploc = _local(p)

    if s == o:
        return "vacuous_selfloop"
    if ploc in PROVENANCE_LOCALS:
        return "provenance"
    if _nonconcept(s) or _nonconcept(o):
        return "nonconcept_endpoint"
    if s in _OWL_THING or o in _OWL_THING:
        return "owl_vocabulary"
    if _local(s) in _PROMPT_VOCABULARY or _local(o) in _PROMPT_VOCABULARY:
        return "prompt_leakage"
    if ploc in ANNOTATION_LOCALS:
        return "annotation"
    if _class_as_predicate(p):
        return "class_as_predicate"
    if _nonstandard_predicate(p):
        return "nonstandard_predicate"
    if ploc in EQUIVALENCE_LOCALS:
        return "equivalence"
    if ploc in SCHEMA_LOCALS:
        return "schema_axiom"
    if p == SUBCLASSOF:
        return "taxonomic"
    return "relational"


def redundant_shortcuts(merged_path: str, edges: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """Which of `edges` (s ⊑ o) are already derivable without themselves.

    Reachability from s to o over rdfs:subClassOf in the merged graph, with the
    edge under test removed.  A hit means the assertion adds no subsumption the
    ontology did not already entail — a shortcut, not new knowledge.
    """
    g = _load_graph(merged_path)
    parents: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, URIRef(SUBCLASSOF), None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            parents[str(s)].add(str(o))

    out: set[tuple[str, str]] = set()
    for s, o in set(edges):
        seen = {s}
        dq = deque(x for x in parents.get(s, ()) if x != o)  # drop the edge itself
        found = False
        while dq:
            cur = dq.popleft()
            if cur == o:
                found = True
                break
            if cur in seen:
                continue
            seen.add(cur)
            dq.extend(parents.get(cur, ()))
        if found:
            out.add((s, o))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.population, encoding="utf-8")))
    for r in rows:
        r["category"] = classify(r)
        r["redundant_shortcut"] = ""

    by_run: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["category"] == "taxonomic":
            by_run[r["merged_path"]].append(r)

    for path, taxo in by_run.items():
        red = redundant_shortcuts(path, [(r["subject"], r["object"]) for r in taxo])
        for r in taxo:
            r["redundant_shortcut"] = "1" if (r["subject"], r["object"]) in red else "0"
        print(f"  {Path(path).parent.name}: {len(red)}/{len(taxo)} taxonomic edges redundant")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nclassified → {out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
