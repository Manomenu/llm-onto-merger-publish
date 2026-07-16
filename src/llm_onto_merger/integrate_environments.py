from rdflib import Graph, URIRef

from .ontology.kg2code import build_alias_map


def integrate_environments(
    merged_graphs: list[Graph],
    leftover_1: Graph,
    leftover_2: Graph,
    code_to_ns: dict[str, str],
) -> Graph:
    """Combine all merged environment graphs and leftovers into one Graph.

    Alias triples produced by the LLM (predicate http://merged#alias) are used
    to build a substitution map: any triple whose subject, predicate or object
    is a known old URI is rewritten to the canonical merged URI before being
    added.  The predicate position matters for merged *properties* — their
    usage triples elsewhere still reference the old property URI.
    """
    alias_map = build_alias_map(merged_graphs, code_to_ns)

    # Resolve alias chains (A→B, B→C ⇒ A→C) so a single substitution pass
    # suffices; the seen-set guards against accidental alias cycles.
    for old in list(alias_map):
        target = alias_map[old]
        seen = {old}
        while target in alias_map and target not in seen:
            seen.add(target)
            target = alias_map[target]
        alias_map[old] = target

    def _sub(uri: str) -> str:
        return alias_map.get(uri, uri)

    merged_onto = Graph()
    for graph in (*merged_graphs, leftover_1, leftover_2):
        for s, p, o in graph:
            s2 = URIRef(_sub(str(s))) if isinstance(s, URIRef) else s
            p2 = URIRef(_sub(str(p))) if isinstance(p, URIRef) else p
            o2 = URIRef(_sub(str(o))) if isinstance(o, URIRef) else o
            merged_onto.add((s2, p2, o2))
    return merged_onto
