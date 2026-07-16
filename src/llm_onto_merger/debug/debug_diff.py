from pathlib import Path

from rdflib import Graph, URIRef

from ..extract_environments.merge_environment import MergeEnvironment
from ..logger import get_logger
from ..ontology import local_name

log = get_logger(__name__)


def _write_diff(
    env: MergeEnvironment,
    merged: Graph,
    path: Path,
) -> None:
    def _names(graph: Graph) -> set[tuple[str, str, str]]:
        return {
            (local_name(str(s)), local_name(str(p)), local_name(str(o)))
            for s, p, o in graph
            if isinstance(s, URIRef) and isinstance(o, URIRef)
        }

    pre_triple_names  = _names(env.onto_1) | _names(env.onto_2)
    post_triple_names = _names(merged)

    deleted = sorted(pre_triple_names - post_triple_names)
    added   = sorted(post_triple_names - pre_triple_names)

    with path.open("w") as f:
        f.write("[Deleted]\n")
        for s, p, o in deleted:
            f.write(f"  ({s}, {p}, {o})\n")
        f.write("[Added]\n")
        for s, p, o in added:
            f.write(f"  ({s}, {p}, {o})\n")

    log.info("[debug] %s  deleted: %d  added: %d", path.name, len(deleted), len(added))


def save_diff_debug(
    merge_environments: list[MergeEnvironment],
    merged_graphs: list[Graph],
    out_dir: Path,
) -> None:
    """Write env_diff_N.txt for each environment.

    Triples are compared by local name (URI-agnostic).
    Blank nodes and non-URIRef triples are excluded.
    """
    for i, (env, merged) in enumerate(zip(merge_environments, merged_graphs)):
        _write_diff(env, merged, out_dir / f"env_diff_{i}.txt")
