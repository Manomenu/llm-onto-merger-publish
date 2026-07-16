"""Debug visualizations — only called when settings.debug is True.

Files written to settings.save_location:
  debug_pre_merge.html       — all pre-merge environments + leftovers combined
  debug_merge_env_N.html     — individual pre-merge environment N
  debug_post_merge.html      — all merged environments + leftovers combined
  debug_merged_env_N.html    — individual merged environment N

Color themes
────────────
Pre-merge environments use a coherent **greenish** palette so all parts of
the same environment family read as visually related:
  onto_1 interior  #f1f8e9  (lightest green)
  onto_2 interior  #dcedc8  (very light green)
  border1          #c5e1a5  (light green)
  border2          #aed581  (medium green)
  aligned nodes    #33691e  (very dark green — stands out clearly)
  alignment edges  #558b2f  (dark green, dashed)
  onto_1 leftover  #b0bec5  (blue-grey)
  onto_2 leftover  #78909c  (darker blue-grey)

Post-merge environments each get a unique colour from a rotating 12-colour
palette; leftovers keep the same blue-grey tones as above.
"""

from pathlib import Path

from pyvis.network import Network
from rdflib import Graph, URIRef

from ..extract_environments.merge_environment import MergeEnvironment
from ..logger import get_logger
from ..ontology import local_name

log = get_logger(__name__)



# ── pre-merge palette ────────────────────────────────────────────────────────
# onto_1 → blue family, onto_2 → orange family, aligned → red, edges → purple
_PRE_ONTO1 = "#003b65"  # pale blue        — onto_1 interior nodes
_PRE_ONTO2 = "#ae6b00"  # pale orange      — onto_2 interior nodes
_PRE_BORDER1 = "#6aa1e0"  # strong blue      — border1 nodes
_PRE_BORDER2 = "#ebb191"  # strong orange    — border2 nodes
_PRE_ALIGNED = "#c62828"  # strong red       — aligned (seed) nodes
_PRE_ALIGN_EDGE = "#6a1b9a"  # purple dashed    — alignment edges

# ── post-merge: high-contrast cycling palette ────────────────────────────────
# All 12 colours are distinct from each other and from the two leftover colours.
_POST_PALETTE = [
    "#e53935",  # red
    "#8e24aa",  # purple
    "#1e88e5",  # blue
    "#00897b",  # teal
    "#f4511e",  # deep orange
    "#3949ab",  # indigo
    "#00acc1",  # cyan
    "#43a047",  # green
    "#fdd835",  # yellow
    "#fb8c00",  # amber
    "#6d4c41",  # brown
    "#f06292",  # pink
]

# ── leftovers ─────────────────────────────────────────────────────────────────
_LEFTOVER1 = "#cfd8dc"  # light blue-grey  — onto_1 leftovers
_LEFTOVER2 = "#455a64"  # dark slate       — onto_2 leftovers

_DIFF_EDGE = "#ff1493"  # deep pink — added/deleted edges


# ── helpers ───────────────────────────────────────────────────────────────────


def _new_network() -> Network:
    network = Network(
        height="900px",
        width="100%",
        directed=True,
        notebook=False,
        bgcolor="#ffffff",
        font_color="#222222",
    )
    network.barnes_hut(gravity=-5000, central_gravity=0.3, spring_length=120)
    return network


def _add_graph_nodes(net: Network, graph: Graph, color: str, seen: set[str]) -> None:
    for s, _, o in graph:
        for node in (s, o):
            uri = str(node)
            if isinstance(node, URIRef) and uri not in seen:
                net.add_node(uri, label=local_name(uri), color=color, title=uri)
                seen.add(uri)


def _add_graph_edges(net: Network, graph: Graph) -> None:
    for s, p, o in graph:
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            net.add_edge(
                str(s),
                str(o),
                label=local_name(p),
                title=str(p),
                color="#aaaaaa",
                arrows="to",
            )


def _name_edges(graph: Graph) -> dict[tuple[str, str, str], tuple[str, str, str]]:
    """Map (local_s, local_p, local_o) → (uri_s, uri_p, uri_o).

    Compares triples by local name so a different namespace prefix for the same
    concept still matches correctly.  On local-name collision the last URI wins.
    """
    result: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for s, p, o in graph:
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            key = (local_name(str(s)), local_name(str(p)), local_name(str(o)))
            result[key] = (str(s), str(p), str(o))
    return result


def _draw_diff_edges(
    net: Network,
    edges: set[tuple[str, str, str]],
    seen: set[str],
) -> None:
    """Draw a set of edges in pink. Adds missing endpoint nodes in neutral grey."""
    for s, p, o in edges:
        for uri in (s, o):
            if uri not in seen:
                net.add_node(uri, label=local_name(uri), color="#dddddd", title=uri)
                seen.add(uri)
        net.add_edge(
            s,
            o,
            label=local_name(p),
            title=p,
            color=_DIFF_EDGE,
            width=2,
            arrows="to",
            dashes=True,
        )


def _add_env(net: Network, env: MergeEnvironment, seen: set[str]) -> None:
    border1 = {str(u) for u in env.border1}
    border2 = {str(u) for u in env.border2}
    aligned = {a.entity1 for a in env.alignments} | {a.entity2 for a in env.alignments}

    def _nodes(onto: Graph, base: str, border_col: str) -> None:
        for s, _, o in onto:
            for node in (s, o):
                uri = str(node)
                if not isinstance(node, URIRef) or uri in seen:
                    continue
                seen.add(uri)
                if uri in aligned:
                    color, bw = _PRE_ALIGNED, 3
                elif uri in border1:
                    color, bw = _PRE_BORDER1, 2
                elif uri in border2:
                    color, bw = _PRE_BORDER2, 2
                else:
                    color, bw = base, 1
                net.add_node(
                    uri, label=local_name(uri), color=color, borderWidth=bw, title=uri
                )

    _nodes(env.onto_1, _PRE_ONTO1, _PRE_BORDER1)
    _nodes(env.onto_2, _PRE_ONTO2, _PRE_BORDER2)
    _add_graph_edges(net, env.onto_1)
    _add_graph_edges(net, env.onto_2)
    for al in env.alignments:
        for uri in (al.entity1, al.entity2):
            if uri not in seen:
                net.add_node(uri, label=local_name(uri), color=_PRE_ALIGNED, title=uri)
                seen.add(uri)
        net.add_edge(
            al.entity1,
            al.entity2,
            label=f"{al.measure:.2f}",
            title=f"alignment: {al.measure:.4f}",
            color=_PRE_ALIGN_EDGE,
            dashes=True,
            width=2,
        )


def _save(net: Network, path: Path) -> None:
    net.save_graph(str(path))
    log.info("[debug] saved %s", path.name)


# ── public API ────────────────────────────────────────────────────────────────


def save_pre_merge_debug(
    merge_environments: list[MergeEnvironment],
    leftover_1: Graph,
    leftover_2: Graph,
    out_dir: Path,
    merged_graphs: list[Graph] | None = None,
) -> None:
    """Write debug_pre_merge.html, debug_merge_env_N.html,
    onto_1_leftover.html, and onto_2_leftover.html.
    """
    combined = _new_network()
    combined_seen: set[str] = set()

    for i, env in enumerate(merge_environments):
        deleted_edges: set[tuple[str, str, str]] = set()
        if merged_graphs and i < len(merged_graphs):
            pre_map = _name_edges(env.onto_1) | _name_edges(env.onto_2)
            post_names = set(_name_edges(merged_graphs[i]).keys())
            deleted_edges = {pre_map[k] for k in pre_map.keys() - post_names}

        _add_env(combined, env, combined_seen)
        _draw_diff_edges(combined, deleted_edges, combined_seen)

        single = _new_network()
        single_seen: set[str] = set()
        _add_env(single, env, single_seen)
        _draw_diff_edges(single, deleted_edges, single_seen)
        _save(single, out_dir / f"debug_merge_env_{i}.html")

    _add_graph_nodes(combined, leftover_1, _LEFTOVER1, combined_seen)
    _add_graph_nodes(combined, leftover_2, _LEFTOVER2, combined_seen)
    _add_graph_edges(combined, leftover_1)
    _add_graph_edges(combined, leftover_2)
    _save(combined, out_dir / "debug_pre_merge.html")

    leftover1_net = _new_network()
    leftover1_seen: set[str] = set()
    _add_graph_nodes(leftover1_net, leftover_1, _LEFTOVER1, leftover1_seen)
    _add_graph_edges(leftover1_net, leftover_1)
    _save(leftover1_net, out_dir / "onto_1_leftover.html")

    leftover2_net = _new_network()
    leftover2_seen: set[str] = set()
    _add_graph_nodes(leftover2_net, leftover_2, _LEFTOVER2, leftover2_seen)
    _add_graph_edges(leftover2_net, leftover_2)
    _save(leftover2_net, out_dir / "onto_2_leftover.html")


def save_post_merge_debug(
    merged_environments: list[Graph],
    leftover_1: Graph,
    leftover_2: Graph,
    out_dir: Path,
    merge_environments: list[MergeEnvironment] | None = None,
) -> None:
    """Write debug_post_merge.html and debug_merged_env_N.html.

    The combined view includes all merged environments plus leftover_1 and
    leftover_2 nodes rendered in their distinct blue-grey colours.
    """
    global_border: set[str] = set()
    if merge_environments:
        for env in merge_environments:
            global_border.update(str(u) for u in env.border1)
            global_border.update(str(u) for u in env.border2)

    def _add_nodes_with_border(
        net: Network, graph: Graph, color: str, seen: set[str]
    ) -> None:
        for s, _, o in graph:
            for node in (s, o):
                uri = str(node)
                if not isinstance(node, URIRef) or uri in seen:
                    continue
                seen.add(uri)
                node_color = "#000000" if uri in global_border else color
                net.add_node(uri, label=local_name(uri), color=node_color, title=uri)

    combined = _new_network()
    combined_seen: set[str] = set()

    for i, graph in enumerate(merged_environments):
        pre_env = merge_environments[i] if merge_environments and i < len(merge_environments) else None
        color = _POST_PALETTE[i % len(_POST_PALETTE)]

        _add_nodes_with_border(combined, graph, color, combined_seen)
        _add_graph_edges(combined, graph)

        added_edges: set[tuple[str, str, str]] = set()
        if pre_env is not None:
            pre_names = set((_name_edges(pre_env.onto_1) | _name_edges(pre_env.onto_2)).keys())
            post_map = _name_edges(graph)
            added_edges = {post_map[k] for k in post_map.keys() - pre_names}
        _draw_diff_edges(combined, added_edges, combined_seen)

        single = _new_network()
        single_seen: set[str] = set()
        _add_nodes_with_border(single, graph, color, single_seen)
        _add_graph_edges(single, graph)
        _draw_diff_edges(single, added_edges, single_seen)
        _save(single, out_dir / f"debug_merged_env_{i}.html")

    _add_graph_nodes(combined, leftover_1, _LEFTOVER1, combined_seen)
    _add_graph_nodes(combined, leftover_2, _LEFTOVER2, combined_seen)
    _add_graph_edges(combined, leftover_1)
    _add_graph_edges(combined, leftover_2)
    _save(combined, out_dir / "debug_post_merge.html")
