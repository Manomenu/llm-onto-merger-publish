from rdflib import OWL, Graph, URIRef

from ..alignment.alignment import Alignment
from .uri import local_name

_MERGED_NS = "http://merged#"


def apply_alignments(onto_1: Graph, onto_2: Graph, alignments: list[Alignment]) -> Graph:
    """Naive alignment-based merge: union of both ontologies with owl:equivalentClass
    links for each aligned pair.  Both namespaces are preserved so cross-ontology
    metrics can be computed correctly.
    """
    result = Graph()
    for t in onto_1:
        result.add(t)
    for t in onto_2:
        result.add(t)
    for al in alignments:
        e1 = URIRef(al.entity1)
        e2 = URIRef(al.entity2)
        if e1 != e2:
            result.add((e1, OWL.equivalentClass, e2))
    return result


def collapse_alignments_to_merged_ns(
    onto_1: Graph,
    onto_2: Graph,
    alignments: list[Alignment],
) -> tuple[Graph, dict[str, dict[str, str]]]:
    """Union of both ontologies with each aligned pair collapsed into a merged# URI.

    Unlike collapse_alignments (which keeps entity1 URI), creates a new entity in the
    http://merged# namespace for each aligned pair.  Non-aligned entities keep their
    original namespace.

    Returns:
        (graph, provenance) where provenance = {merged_uri: {"1": e1_local, "2": e2_local}}.
        provenance is compatible with _build_alias_maps Format 2 (arom_provenance).
    """
    result = Graph()
    for t in onto_1:
        result.add(t)
    for t in onto_2:
        result.add(t)
    provenance: dict[str, dict[str, str]] = {}
    for al in alignments:
        e1 = URIRef(al.entity1)
        e2 = URIRef(al.entity2)
        if e1 == e2:
            continue
        new_uri = URIRef(f"{_MERGED_NS}{local_name(e1)}")
        for src in (e1, e2):
            for _, p, o in list(result.triples((src, None, None))):
                result.remove((src, p, o))
                result.add((new_uri, p, o))
            for s, p, _ in list(result.triples((None, None, src))):
                result.remove((s, p, src))
                result.add((s, p, new_uri))
        provenance[str(new_uri)] = {
            "1": local_name(e1), "2": local_name(e2),
            "1_uri": str(e1), "2_uri": str(e2),
        }
    return result, provenance


def collapse_alignments(onto_1: Graph, onto_2: Graph, alignments: list[Alignment]) -> Graph:
    """Union of both ontologies with each aligned entity2 URI replaced by entity1.

    Used as a deterministic fallback when the LLM response cannot be parsed —
    guarantees a valid graph at the cost of losing onto2 namespace identity.
    """
    result = Graph()
    for t in onto_1:
        result.add(t)
    for t in onto_2:
        result.add(t)
    for al in alignments:
        e1 = URIRef(al.entity1)
        e2 = URIRef(al.entity2)
        if e1 == e2:
            continue
        for _, p, o in list(result.triples((e2, None, None))):
            result.remove((e2, p, o))
            result.add((e1, p, o))
        for s, p, _ in list(result.triples((None, None, e2))):
            result.remove((s, p, e2))
            result.add((s, p, e1))
    return result
