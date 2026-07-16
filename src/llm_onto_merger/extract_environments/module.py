from collections import deque
from typing import Callable

from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..logger import get_logger
from ..ontology import local_name, move_entity_triples, namespace_of
from .merge_environment import (
    MergeEnvironment,
    MergeEnvironmentConfig,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Alignment pool
# ---------------------------------------------------------------------------

class _AlignmentPool:
    """Sorted pool of alignment pairs. pop() always yields the highest-measure pair."""

    def __init__(self, alignments: list[Alignment]) -> None:
        self._sorted: list[Alignment] = sorted(alignments, key=lambda a: a.measure)

    def pop(self) -> Alignment:
        return self._sorted.pop()

    def is_empty(self) -> bool:
        return not self._sorted


# ---------------------------------------------------------------------------
# Environment builder
# ---------------------------------------------------------------------------

def _build_merge_environment(
    source_1: Graph,
    source_2: Graph,
    seed_al: Alignment,
    config: MergeEnvironmentConfig,
    env_idx: int,
    ns_to_code: dict[str, str],
    code_to_ns: dict[str, str],
    well_known_codes: frozenset[str],
) -> MergeEnvironment:
    is_wk = lambda u: ns_to_code.get(namespace_of(str(u))) in well_known_codes  # noqa: E731

    seed1 = URIRef(seed_al.entity1)
    seed2 = URIRef(seed_al.entity2)

    log.info(
        "env #%d  seed: %s (onto1) ↔ %s (onto2)  measure=%.3f",
        env_idx, local_name(seed_al.entity1), local_name(seed_al.entity2), seed_al.measure,
    )

    sub1, sub2 = Graph(), Graph()
    seeds: set[URIRef] = {seed1, seed2}
    border_set1: set[URIRef] = set()
    border_set2: set[URIRef] = set()

    # Move direct triples of each seed into the environment sub-graph.
    for node, source, sub, border_set in (
        (seed1, source_1, sub1, border_set1),
        (seed2, source_2, sub2, border_set2),
    ):
        triples = move_entity_triples(node, source, sub)
        for s, _, o in triples:
            for neighbor in (s, o):
                if isinstance(neighbor, URIRef) and neighbor not in seeds and not is_wk(neighbor):
                    border_set.add(neighbor)

    # Copy (not move) triples of border nodes from source into border graphs.
    # Note: triples that connected a border node directly to a seed were already
    # moved by move_entity_triples above, so they will NOT appear here.
    border1_graph, border2_graph = Graph(), Graph()
    for node in border_set1:
        for triple in source_1.triples((node, None, None)):
            border1_graph.add(triple)
    for node in border_set2:
        for triple in source_2.triples((node, None, None)):
            border2_graph.add(triple)

    log.info(
        "env #%d  done  |  onto1: %d triples  onto2: %d triples"
        "  |  border1: %d  border2: %d",
        env_idx, len(sub1), len(sub2), len(border_set1), len(border_set2),
    )

    env = MergeEnvironment(
        onto_1=sub1,
        onto_2=sub2,
        alignments=[seed_al],
        border1=deque(border_set1),
        border2=deque(border_set2),
        border1_graph=border1_graph,
        border2_graph=border2_graph,
        ns_to_code=ns_to_code,
        code_to_ns=code_to_ns,
        max_chars=config.max_chars,
    )
    env.expanded_nodes_1.add(seed1)
    env.expanded_nodes_2.add(seed2)
    return env


# ---------------------------------------------------------------------------
# Expansion helper
# ---------------------------------------------------------------------------

def _expand_one(
    border: deque[URIRef],
    border_queued: set[URIRef],
    border_graph: Graph,
    interior: Graph,
    expanded_nodes: set[URIRef],
    source: Graph,
    global_frozen: set[URIRef],
    is_wk: Callable[[URIRef], bool],
) -> URIRef | None:
    """Pop the next expandable node from *border*, move its triples into *interior*.

    A node is not expandable if it is in global_frozen (already interior
    somewhere) or is well-known.  Such nodes are silently discarded from the
    deque — frozen is monotone, so they will never become expandable again.

    New neighbours discovered via the moved triples are appended to *border*
    (if not already queued / frozen / well-known) and their source triples are
    copied into *border_graph* for context.

    Returns the expanded node, or None if the border is exhausted.
    """
    while border:
        node = border.popleft()
        if node in global_frozen or is_wk(node):
            continue

        triples = move_entity_triples(node, source, interior)
        global_frozen.add(node)
        expanded_nodes.add(node)

        # The node has moved to interior — remove its outgoing triples from
        # border_graph (they are now redundant; incoming edges from other border
        # nodes are left untouched because they still provide useful context).
        for triple in list(border_graph.triples((node, None, None))):
            border_graph.remove(triple)

        # Discover new neighbours and queue them as border candidates.
        for s, p, o in triples:
            for neighbour in (s, o):
                if not isinstance(neighbour, URIRef) or is_wk(neighbour) or neighbour in border_queued:
                    continue
                border_queued.add(neighbour)
                if neighbour in global_frozen:
                    # Already interior elsewhere — cannot expand, but surface as border context.
                    # Only add the triple when the frozen node is the subject so it appears
                    # as a border_graph subject and gets rendered by _render_border.
                    if neighbour == s:
                        border_graph.add((s, p, o))
                else:
                    border.append(neighbour)
                    for triple in source.triples((neighbour, None, None)):
                        border_graph.add(triple)

        return node
    return None


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class ExtractEnvironmentsModule:
    def __init__(self, config: MergeEnvironmentConfig) -> None:
        self.config = config

    def extract(
        self,
        onto_1: Graph,
        onto_2: Graph,
        alignments: list[Alignment],
        code_to_ns: dict[str, str],
        ns_to_code: dict[str, str],
        well_known_codes: frozenset[str],
    ) -> tuple[list[MergeEnvironment], Graph, Graph]:
        """Extract one MergeEnvironment per alignment pair.

        Each environment contains the direct triples of the two seed nodes plus
        their neighbourhood as border context (triples copied from source).
        Border nodes may appear in multiple environments — their triples are
        never consumed from source, only copied.

        Returns:
            (environments, leftover_1, leftover_2)
        """
        source_1 = Graph()
        source_2 = Graph()
        for triple in onto_1:
            source_1.add(triple)
        for triple in onto_2:
            source_2.add(triple)

        pool = _AlignmentPool(alignments)
        environments: list[MergeEnvironment] = []

        log.info(
            "Starting extraction: %d alignment pairs  (max border size: %d chars)",
            len(alignments), self.config.max_chars,
        )

        idx = 0
        while not pool.is_empty():
            env = _build_merge_environment(
                source_1, source_2, pool.pop(), self.config, idx,
                ns_to_code, code_to_ns, well_known_codes,
            )
            environments.append(env)
            idx += 1

        log.info(
            "Extraction done: %d environments"
            "  |  onto1=%d triples  onto2=%d triples remaining (no alignment → pass-through)",
            len(environments), len(source_1), len(source_2),
        )
        return environments, source_1, source_2

    def expand_extracted(
        self,
        environments: list[MergeEnvironment],
        source_1: Graph,
        source_2: Graph,
        ns_to_code: dict[str, str],
        well_known_codes: frozenset[str],
    ) -> None:
        """Phase 2: round-robin border expansion into environment interiors.

        For each active environment, one border node from onto_1 side and one
        from onto_2 side are expanded per round: their triples are moved from
        source into the environment interior and their direct neighbours are
        queued as new border candidates.

        Environments are removed from the rotation when they exceed max_chars
        or have no more expandable border nodes.  The loop terminates when no
        environment can expand further.

        global_frozen tracks every node that has entered any environment
        interior — such nodes can no longer be promoted to an interior
        elsewhere (they may still appear in border_graph as context).

        Modifies *environments*, *source_1*, and *source_2* in-place.
        """
        def is_wk(u: URIRef) -> bool:
            return ns_to_code.get(namespace_of(str(u))) in well_known_codes

        def _env_label(i: int) -> str:
            al = environments[i].alignments[0]
            return f"env #{i} ({local_name(al.entity1)} ↔ {local_name(al.entity2)})"

        # Only actual seed nodes start frozen — not every subject found in the interior
        # graphs.  move_entity_triples pulls in triples where the seed is the *object*
        # too (e.g. (Author, subClassOf, Person)), so border nodes can appear as
        # subjects inside onto_1/onto_2 without having been explicitly expanded.
        global_frozen: set[URIRef] = {
            URIRef(uri)
            for env in environments
            for al in env.alignments
            for uri in (al.entity1, al.entity2)
        }

        # Snapshot state before any expansion for the final summary.
        initial: dict[int, tuple[int, int, int, int]] = {
            i: (len(env.onto_1), len(env.onto_2), len(env.border1), len(env.border2))
            for i, env in enumerate(environments)
        }

        active = list(range(len(environments)))
        log.info(
            "Starting border expansion: %d environments  |  global_frozen=%d nodes",
            len(active), len(global_frozen),
        )

        round_num = 0
        stop_reason = "all environments left rotation"
        while active:
            round_num += 1
            next_active: list[int] = []
            any_expanded = False

            for idx in active:
                env = environments[idx]

                expanded_1 = _expand_one(
                    env.border1, env._border1_queued, env.border1_graph,
                    env.onto_1, env.expanded_nodes_1, source_1, global_frozen, is_wk,
                )
                expanded_2 = _expand_one(
                    env.border2, env._border2_queued, env.border2_graph,
                    env.onto_2, env.expanded_nodes_2, source_2, global_frozen, is_wk,
                )

                if expanded_1 is not None or expanded_2 is not None:
                    any_expanded = True
                    n1 = local_name(str(expanded_1)) if expanded_1 is not None else "-"
                    n2 = local_name(str(expanded_2)) if expanded_2 is not None else "-"
                    log.info(
                        "%s  round %d  |  onto_1 <- %s  |  onto_2 <- %s",
                        _env_label(idx), round_num, n1, n2,
                    )

                still_has_border = bool(env.border1) or bool(env.border2)
                within_limit = env.interior_char_estimate() < self.config.max_chars

                if still_has_border and within_limit:
                    next_active.append(idx)
                else:
                    reasons: list[str] = []
                    if not within_limit:
                        reasons.append("char limit reached")
                    if not still_has_border:
                        reasons.append("border exhausted (all nodes frozen or no triples left in source)")
                    log.info(
                        "%s  leaving rotation after round %d  |  reason: %s",
                        _env_label(idx), round_num, ", ".join(reasons),
                    )

            active = next_active

            if not any_expanded:
                stop_reason = "no expansion in round — all border nodes frozen or source exhausted"
                break

        log.info("Expansion done after %d rounds  |  reason: %s", round_num, stop_reason)
        log.info(
            "source after expansion  |  source_1=%d triples  source_2=%d triples",
            len(source_1), len(source_2),
        )

        # Per-environment growth summary.
        # Border count = subjects in border_graph minus explicitly expanded nodes
        # (same definition used by _render_border).
        for i, env in enumerate(environments):
            i1_before, i2_before, b1_before, b2_before = initial[i]
            b1_after = len(
                {s for s, _, _ in env.border1_graph if isinstance(s, URIRef)} - env.expanded_nodes_1
            )
            b2_after = len(
                {s for s, _, _ in env.border2_graph if isinstance(s, URIRef)} - env.expanded_nodes_2
            )
            log.info(
                "%s  summary  |"
                "  onto_1: %d->%d triples  onto_2: %d->%d triples"
                "  |  border1: %d->%d nodes  border2: %d->%d nodes",
                _env_label(i),
                i1_before, len(env.onto_1),
                i2_before, len(env.onto_2),
                b1_before, b1_after,
                b2_before, b2_after,
            )
