#!/usr/bin/env python3
"""Generate Boomer input files (combined.owl, prefixes.yaml, ptable.tsv) from
two source OWL ontologies.

Three matchers supported (mutually exclusive):
  --use-aml      run AML via AmlAlignmentModule, use AML measure as p_equiv
  --use-logmap   run LogMap via LogmapAlignmentModule, use LogMap measure as p_equiv
  (default)      lexical: local-name match across both ontologies, fixed p_equiv=0.70

Outputs in --artifacts-dir:
  combined.owl   — axiom union of both inputs (rdflib union, RDF/XML).
  prefixes.yaml  — every unique namespace gets a short prefix.  Well-known
                   namespaces (rdf, rdfs, owl, xsd, ...) get canonical names.
  ptable.tsv     — Boomer format (no header):
                       subject  object  p_sub  p_super  p_equiv  p_other
                   p_sub = p_super = 0 (AML/LogMap don't predict subClassOf).
                   p_equiv = matcher measure  (or 0.70 in lexical mode).
                   p_other = 1 - p_equiv.

Usage:
    uv run python generate_inputs.py \\
        --onto1 path/to/onto1.owl \\
        --onto2 path/to/onto2.owl \\
        --artifacts-dir thirdparty/boomer/artifacts \\
        [--use-aml | --use-logmap]
"""

import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, URIRef


def _namespace(uri: str) -> str:
    idx_hash = uri.rfind("#")
    idx_slash = uri.rfind("/")
    cut = max(idx_hash, idx_slash)
    return uri[: cut + 1] if cut >= 0 else uri


def _local(uri: str) -> str:
    ns = _namespace(uri)
    return uri[len(ns):]


_KNOWN_PREFIXES: dict[str, str] = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "RDF",
    "http://www.w3.org/2000/01/rdf-schema#": "RDFS",
    "http://www.w3.org/2002/07/owl#": "OWL",
    "http://www.w3.org/2001/XMLSchema#": "XSD",
    "http://www.w3.org/2004/02/skos/core#": "SKOS",
    "http://purl.org/dc/elements/1.1/": "DC",
    "http://purl.org/dc/terms/": "DCTERMS",
    "http://xmlns.com/foaf/0.1/": "FOAF",
}


def _derive_prefix(ns: str) -> str:
    if ns in _KNOWN_PREFIXES:
        return _KNOWN_PREFIXES[ns]
    trimmed = ns.rstrip("#/")
    last = re.split(r"[#/]", trimmed)[-1] or "NS"
    cleaned = re.sub(r"[^A-Za-z0-9]", "", last).upper()
    if cleaned and cleaned[0].isdigit():
        cleaned = "NS" + cleaned
    return cleaned or "NS"


def _collect_namespaces(graphs: list[Graph]) -> set[str]:
    namespaces: set[str] = set()
    for g in graphs:
        for s, p, o in g:
            for term in (s, p, o):
                if isinstance(term, URIRef):
                    ns = _namespace(str(term))
                    if ns:
                        namespaces.add(ns)
    return namespaces


def _filter_substring_namespaces(namespaces: set[str]) -> set[str]:
    """Remove namespaces until no one is a lexical substring of another.

    Boomer requires this strictly (not just prefix-free).  Two resolution rules:
    - Prefix case  (B starts with A, A shorter): drop A — B is more specific.
    - Embedded case (A appears inside B but B doesn't start with A): drop B —
      it's a malformed/intermediate URI that happens to embed a real namespace.
    Iterates until stable (handles chains).
    """
    result = set(namespaces)
    changed = True
    while changed:
        changed = False
        current = sorted(result, key=len)
        for a in current:
            if a not in result:
                continue
            for b in current:
                if a is b or b not in result or a == b:
                    continue
                if a in b:
                    if b.startswith(a):
                        result.discard(a)  # prefix case: a is too short, drop it
                    else:
                        result.discard(b)  # embedded case: b is malformed, drop it
                    changed = True
                    break
            if changed:
                break
    return result


def _build_prefix_map(namespaces: set[str]) -> dict[str, str]:
    filtered = _filter_substring_namespaces(namespaces)
    dropped = namespaces - filtered
    if dropped:
        print(
            f"  → dropped {len(dropped)} substring-namespace(s) "
            f"(Boomer constraint): {sorted(dropped)}"
        )
    result: dict[str, str] = {}
    used: set[str] = set()
    for ns in sorted(filtered):
        base = _derive_prefix(ns)
        prefix = base
        suffix = 2
        while prefix in used:
            prefix = f"{base}{suffix}"
            suffix += 1
        used.add(prefix)
        result[prefix] = ns
    return result


def _curie(uri: str, ns_to_prefix: dict[str, str]) -> str | None:
    ns = _namespace(uri)
    prefix = ns_to_prefix.get(ns)
    local = uri[len(ns):]
    if not prefix or not local:
        return None
    return f"{prefix}:{local}"


def _entity_subjects(g: Graph) -> set[URIRef]:
    return {s for s in g.subjects() if isinstance(s, URIRef)}


def _write_combined(onto1: Path, onto2: Path, out: Path) -> tuple[Graph, Graph]:
    g1 = Graph()
    g1.parse(str(onto1))
    g2 = Graph()
    g2.parse(str(onto2))
    combined = Graph()
    for t in g1:
        combined.add(t)
    for t in g2:
        combined.add(t)
    combined.serialize(destination=str(out), format="xml")
    return g1, g2


def _write_prefixes(prefix_to_ns: dict[str, str], out: Path) -> None:
    lines = [f"{prefix}: {ns}" for prefix, ns in sorted(prefix_to_ns.items())]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── ptable generation ─────────────────────────────────────────────────────────


def _format_ptable_row(c1: str, c2: str, p_equiv: float) -> str:
    """AML/LogMap predict equivalence only — p_sub=p_super=0, p_other=1-p_equiv."""
    p_equiv = max(0.0, min(1.0, p_equiv))
    p_other = round(1.0 - p_equiv, 6)
    return f"{c1}\t{c2}\t0\t0\t{p_equiv}\t{p_other}\n"


def _build_ptable_lexical(
    g1: Graph,
    g2: Graph,
    ns_to_prefix: dict[str, str],
    out: Path,
) -> int:
    """Local-name baseline: fixed p_equiv=0.70 for every name collision."""
    P_EQUIV_LEXICAL = 0.70

    by_local_o1: dict[str, list[URIRef]] = defaultdict(list)
    by_local_o2: dict[str, list[URIRef]] = defaultdict(list)
    for s in _entity_subjects(g1):
        by_local_o1[_local(str(s))].append(s)
    for s in _entity_subjects(g2):
        by_local_o2[_local(str(s))].append(s)

    count = 0
    with out.open("w", encoding="utf-8") as f:
        for local, e1_list in by_local_o1.items():
            if not local:
                continue
            for e2 in by_local_o2.get(local, []):
                for e1 in e1_list:
                    if str(e1) == str(e2):
                        continue
                    c1 = _curie(str(e1), ns_to_prefix)
                    c2 = _curie(str(e2), ns_to_prefix)
                    if not c1 or not c2:
                        continue
                    f.write(_format_ptable_row(c1, c2, P_EQUIV_LEXICAL))
                    count += 1
    return count


def _build_ptable_from_matcher(
    matcher_name: str,
    onto1: Path,
    onto2: Path,
    ns_to_prefix: dict[str, str],
    out: Path,
) -> int:
    """Run AML or LogMap, use their per-pair measure as p_equiv."""
    from llm_onto_merger.alignment import alignment_modules_dict

    if matcher_name not in alignment_modules_dict:
        sys.exit(
            f"Unknown matcher '{matcher_name}'. "
            f"Available: {list(alignment_modules_dict)}"
        )
    module = alignment_modules_dict[matcher_name]()
    print(f"  → running {matcher_name} via {module.__class__.__name__}")
    alignments = asyncio.run(module.create_alignment(onto1, onto2))
    print(f"  → matcher returned {len(alignments)} alignment cells")

    count = 0
    skipped = 0
    with out.open("w", encoding="utf-8") as f:
        for a in alignments:
            c1 = _curie(a.entity1, ns_to_prefix)
            c2 = _curie(a.entity2, ns_to_prefix)
            if not c1 or not c2:
                skipped += 1
                continue
            f.write(_format_ptable_row(c1, c2, a.measure))
            count += 1
    if skipped:
        print(
            f"  → skipped {skipped} alignment(s) — entity URIs not in any known namespace "
            "(rerun with broader prefixes.yaml or check matcher output)"
        )
    return count


def _build_ptable_from_alignment_file(
    alignment_path: Path,
    ns_to_prefix: dict[str, str],
    out: Path,
) -> int:
    """Build ptable from a pre-computed OAEI alignment file (e.g. the reference
    alignment), using each cell's measure as p_equiv.  Same row format as the
    matcher path — only the source of pairs differs (no matcher is run).

    A gold-standard reference lists every cell at measure=1.0.  Feeding Boomer
    hard 1.0 probabilities leaves its probabilistic solver no slack to drop
    conflicting pairs, which can trigger 'No possible resolution of perplexity'.
    We therefore CAP p_equiv at BOOMER_REF_P_EQUIV (default 0.99) so the solver
    keeps a small margin.  Set BOOMER_REF_P_EQUIV=1.0 to disable the cap."""
    from llm_onto_merger.alignment.alignment import parse_oaei_alignment

    cap = float(os.environ.get("BOOMER_REF_P_EQUIV", "0.99"))
    alignments = parse_oaei_alignment(alignment_path)
    print(f"  → loaded {len(alignments)} alignment cells from {alignment_path} "
          f"(p_equiv capped at {cap})")

    count = 0
    skipped = 0
    with out.open("w", encoding="utf-8") as f:
        for a in alignments:
            c1 = _curie(a.entity1, ns_to_prefix)
            c2 = _curie(a.entity2, ns_to_prefix)
            if not c1 or not c2:
                skipped += 1
                continue
            f.write(_format_ptable_row(c1, c2, min(a.measure, cap)))
            count += 1
    if skipped:
        print(
            f"  → skipped {skipped} alignment(s) — entity URIs not in any known namespace"
        )
    return count


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onto1", required=True, type=Path)
    parser.add_argument("--onto2", required=True, type=Path)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    matcher_group = parser.add_mutually_exclusive_group()
    matcher_group.add_argument(
        "--use-aml",
        action="store_true",
        help="Run AML and use its measure as p_equiv per row.",
    )
    matcher_group.add_argument(
        "--use-logmap",
        action="store_true",
        help="Run LogMap and use its measure as p_equiv per row.",
    )
    matcher_group.add_argument(
        "--alignment-file",
        type=Path,
        default=None,
        help="Use a pre-computed OAEI alignment file (RDF/XML) for the ptable, "
             "skipping the matcher (e.g. the OAEI reference alignment).",
    )
    args = parser.parse_args()

    if not args.onto1.exists():
        sys.exit(f"onto1 not found: {args.onto1}")
    if not args.onto2.exists():
        sys.exit(f"onto2 not found: {args.onto2}")
    args.artifacts_dir.mkdir(parents=True, exist_ok=True)

    combined_path = args.artifacts_dir / "combined.owl"
    prefixes_path = args.artifacts_dir / "prefixes.yaml"
    ptable_path = args.artifacts_dir / "ptable.tsv"

    print(f"[generate_inputs] loading + uniting axioms → {combined_path}")
    g1, g2 = _write_combined(args.onto1, args.onto2, combined_path)
    print(f"  onto1: {len(g1)} triples")
    print(f"  onto2: {len(g2)} triples")

    print("[generate_inputs] collecting namespaces …")
    namespaces = _collect_namespaces([g1, g2])
    prefix_to_ns = _build_prefix_map(namespaces)
    ns_to_prefix = {ns: pfx for pfx, ns in prefix_to_ns.items()}
    _write_prefixes(prefix_to_ns, prefixes_path)
    print(f"  {len(prefix_to_ns)} prefixes → {prefixes_path}")

    if args.alignment_file is not None:
        if not args.alignment_file.exists():
            sys.exit(f"alignment file not found: {args.alignment_file}")
        print(f"[generate_inputs] building ptable from alignment file {args.alignment_file} …")
        n_pairs = _build_ptable_from_alignment_file(
            args.alignment_file, ns_to_prefix, ptable_path
        )
    elif args.use_aml:
        print("[generate_inputs] building ptable from AML alignments …")
        n_pairs = _build_ptable_from_matcher(
            "aml", args.onto1, args.onto2, ns_to_prefix, ptable_path
        )
    elif args.use_logmap:
        print("[generate_inputs] building ptable from LogMap alignments …")
        n_pairs = _build_ptable_from_matcher(
            "logmap", args.onto1, args.onto2, ns_to_prefix, ptable_path
        )
    else:
        print("[generate_inputs] building ptable by lexical local-name match …")
        n_pairs = _build_ptable_lexical(g1, g2, ns_to_prefix, ptable_path)

    print(f"  {n_pairs} pairs → {ptable_path}")


if __name__ == "__main__":
    main()
