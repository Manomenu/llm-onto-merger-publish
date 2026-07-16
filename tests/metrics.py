#!/usr/bin/env python3
"""
Compute ontology quality metrics for a given test case.

Usage:
    python tests/metrics.py <folder_name>

Reads:
    tests/inputs/<folder_name>/*.owl   — two input ontologies
    tests/outputs/<folder_name>/merged_ontology.owl

Writes:
    tests/outputs/<folder_name>/metrics.csv
    Columns: graf, metryka, wartosc

Schema metrics (per graph):
    num_classes, num_object_properties, num_datatype_properties, num_triples
    avg_depth, max_depth, avg_breadth, max_breadth, ARC, ALC

Knowledge-base metrics (per graph):
    understandability_labels    — fraction of classes with rdfs:label
    understandability_comments  — fraction of classes with rdfs:comment
    cohesion_prop_domain_range  — fraction of properties with both domain AND range
    conciseness_used_classes    — fraction of classes referenced by at least one property

Accuracy metrics (merged_ontology only, relative to unia_input):
    accuracy_classes            — fraction of union class local-names in merged
    accuracy_properties         — fraction of union property local-names in merged
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef

# ── Namespace shortcuts ───────────────────────────────────────────────────────

_OWL_THING  = OWL.Thing
_OWL_CLASS  = OWL.Class
_OWL_OBJ    = OWL.ObjectProperty
_OWL_DATA   = OWL.DatatypeProperty
_OWL_ANN    = OWL.AnnotationProperty
_OWL_FP     = OWL.FunctionalProperty
_OWL_IFP    = OWL.InverseFunctionalProperty
_SUB        = RDFS.subClassOf
_LABEL      = RDFS.label
_COMMENT    = RDFS.comment
_DOMAIN     = RDFS.domain
_RANGE      = RDFS.range

_PROP_TYPES = (_OWL_OBJ, _OWL_DATA, _OWL_ANN, _OWL_FP, _OWL_IFP)


def _local(uri: URIRef) -> str:
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


# ── Entity extraction ─────────────────────────────────────────────────────────

def _classes(g: Graph) -> set[URIRef]:
    """OWL classes declared or used in subClassOf (excluding owl:Thing itself)."""
    result: set[URIRef] = set()
    for s in g.subjects(RDF.type, _OWL_CLASS):
        if isinstance(s, URIRef) and s != _OWL_THING:
            result.add(s)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and s != _OWL_THING:
            result.add(s)
        if isinstance(o, URIRef) and o != _OWL_THING:
            result.add(o)
    return result


def _properties(g: Graph) -> set[URIRef]:
    """All named property instances (object, datatype, annotation, functional…)."""
    result: set[URIRef] = set()
    for ptype in _PROP_TYPES:
        for s in g.subjects(RDF.type, ptype):
            if isinstance(s, URIRef):
                result.add(s)
    return result


# ── Hierarchy analysis ────────────────────────────────────────────────────────

def _hierarchy(g: Graph, classes: set[URIRef]) -> tuple[dict, dict]:
    """Return (parents, children) — owl:Thing excluded as explicit node."""
    parents:  dict[URIRef, set[URIRef]] = defaultdict(set)
    children: dict[URIRef, set[URIRef]] = defaultdict(set)
    for s, _, o in g.triples((None, _SUB, None)):
        if (
            isinstance(s, URIRef) and isinstance(o, URIRef)
            and s in classes and o in classes
        ):
            parents[s].add(o)
            children[o].add(s)
    return parents, children


def _depths(classes: set[URIRef], parents: dict) -> dict[URIRef, int]:
    """Depth = length of longest path from any root (0 for root classes).
    Handles multiple-inheritance DAGs and cycles (cycles → depth 0).
    """
    memo: dict[URIRef, int] = {}
    in_progress: set[URIRef] = set()

    def depth(c: URIRef) -> int:
        if c in memo:
            return memo[c]
        if c in in_progress:
            return 0  # cycle guard
        in_progress.add(c)
        p_set = parents.get(c) or set()
        d = (1 + max(depth(p) for p in p_set)) if p_set else 0
        in_progress.discard(c)
        memo[c] = d
        return d

    for c in classes:
        depth(c)
    return memo


# ── Metric computation ────────────────────────────────────────────────────────

def _schema_metrics(g: Graph) -> dict[str, float]:
    cls  = _classes(g)
    prop = _properties(g)
    obj  = {p for p in prop if (p, RDF.type, _OWL_OBJ)  in g}
    dat  = {p for p in prop if (p, RDF.type, _OWL_DATA) in g}

    # subClassOf triples between named classes (excluding owl:Thing as parent)
    subclassof_n = sum(
        1 for _, _, o in g.triples((None, _SUB, None))
        if isinstance(o, URIRef) and o != _OWL_THING
    )

    par, chi = _hierarchy(g, cls)
    dep      = _depths(cls, par)

    depth_vals   = list(dep.values())
    child_counts = [len(chi[c]) for c in cls if chi.get(c)]

    avg_depth   = sum(depth_vals)   / len(depth_vals)   if depth_vals   else 0.0
    max_depth   = max(depth_vals)                        if depth_vals   else 0
    avg_breadth = sum(child_counts) / len(child_counts) if child_counts else 0.0
    max_breadth = max(child_counts)                      if child_counts else 0

    arc = sum(1 for c in cls if not par.get(c))   # no named parent → root
    alc = sum(1 for c in cls if not chi.get(c))   # no children → leaf

    n_cls = len(cls)
    n_obj = len(obj)
    n_dat = len(dat)

    # OntoQA metrics (Tartir et al.)
    # Relationship Richness: object properties / (object properties + subClassOf)
    rr = n_obj / (n_obj + subclassof_n) if (n_obj + subclassof_n) > 0 else 0.0
    # Inheritance Richness: subClassOf triples / classes
    ir = subclassof_n / n_cls if n_cls > 0 else 0.0
    # Attribute Richness: data properties / classes
    ar = n_dat / n_cls if n_cls > 0 else 0.0

    return {
        "num_classes":              float(n_cls),
        "num_object_properties":    float(n_obj),
        "num_datatype_properties":  float(n_dat),
        "num_triples":              float(len(g)),
        "avg_depth":                round(avg_depth,   4),
        "max_depth":                float(max_depth),
        "avg_breadth":              round(avg_breadth, 4),
        "max_breadth":              float(max_breadth),
        "ARC":                      float(arc),
        "ALC":                      float(alc),
        "relationship_richness":    round(rr, 4),
        "inheritance_richness":     round(ir, 4),
        "attribute_richness":       round(ar, 4),
    }


def _kb_metrics(
    g: Graph,
    union: Graph | None = None,
    union_classes:  set[URIRef] | None = None,
    union_props:    set[URIRef] | None = None,
) -> dict[str, float]:
    cls  = _classes(g)
    prop = _properties(g)
    n_c  = len(cls)
    n_p  = len(prop)

    # Understandability
    labelled  = sum(1 for c in cls if any(True for _ in g.objects(c, _LABEL)))
    commented = sum(1 for c in cls if any(True for _ in g.objects(c, _COMMENT)))
    u_labels   = labelled  / n_c if n_c else 0.0
    u_comments = commented / n_c if n_c else 0.0

    # Cohesion: fraction of properties with both domain AND range defined
    with_domain = {p for p in prop if any(True for _ in g.objects(p, _DOMAIN))}
    with_range  = {p for p in prop if any(True for _ in g.objects(p, _RANGE))}
    cohesion = len(with_domain & with_range) / n_p if n_p else 0.0

    # Conciseness proxy: fraction of classes referenced by ≥1 property domain/range
    domains = {o for p in prop for o in g.objects(p, _DOMAIN) if isinstance(o, URIRef)}
    ranges  = {o for p in prop for o in g.objects(p, _RANGE)  if isinstance(o, URIRef)}
    used_cls   = (domains | ranges) & cls
    conciseness = len(used_cls) / n_c if n_c else 0.0

    result: dict[str, float] = {
        "understandability_labels":    round(u_labels,    4),
        "understandability_comments":  round(u_comments,  4),
        "cohesion_prop_domain_range":  round(cohesion,    4),
        "conciseness_used_classes":    round(conciseness, 4),
    }

    # Accuracy relative to union (only for merged graph)
    if union_classes is not None and union_props is not None:
        union_cls_names  = {_local(c) for c in union_classes}
        union_prop_names = {_local(p) for p in union_props}
        merged_cls_names  = {_local(c) for c in cls}
        merged_prop_names = {_local(p) for p in prop}

        acc_c = (
            len(merged_cls_names  & union_cls_names)  / len(union_cls_names)
            if union_cls_names  else 0.0
        )
        acc_p = (
            len(merged_prop_names & union_prop_names) / len(union_prop_names)
            if union_prop_names else 0.0
        )
        result["accuracy_classes"]    = round(acc_c, 4)
        result["accuracy_properties"] = round(acc_p, 4)

    return result


def _all_metrics(
    g: Graph,
    union: Graph | None = None,
    union_classes: set[URIRef] | None = None,
    union_props:   set[URIRef] | None = None,
) -> dict[str, float]:
    return {
        **_schema_metrics(g),
        **_kb_metrics(g, union, union_classes, union_props),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <folder_name>", file=sys.stderr)
        sys.exit(1)

    folder     = sys.argv[1]
    repo_root  = Path(__file__).parent.parent
    input_dir  = repo_root / "tests" / "inputs"  / folder
    output_dir = repo_root / "tests" / "outputs" / folder
    out_csv    = output_dir / "metrics.csv"

    if not input_dir.exists():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    input_files = sorted(input_dir.glob("*.owl"))
    if len(input_files) != 2:
        print(
            f"Expected exactly 2 .owl files in {input_dir}, found {len(input_files)}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading {input_files[0].name} …")
    onto1 = Graph(); onto1.parse(str(input_files[0]))
    print(f"  {len(onto1)} triples")

    print(f"Loading {input_files[1].name} …")
    onto2 = Graph(); onto2.parse(str(input_files[1]))
    print(f"  {len(onto2)} triples")

    union = Graph()
    for t in onto1: union.add(t)
    for t in onto2: union.add(t)
    print(f"Union: {len(union)} triples")

    merged_path = output_dir / "merged_ontology.owl"
    if not merged_path.exists():
        print(f"merged_ontology.owl not found in {output_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading merged_ontology.owl …")
    merged = Graph(); merged.parse(str(merged_path))
    print(f"  {len(merged)} triples")

    u_cls  = _classes(union)
    u_prop = _properties(union)

    graphs = [
        ("unia_input",      union,  None,   None,   None),
        ("merged_ontology", merged, union,  u_cls,  u_prop),
    ]

    rows: list[dict] = []
    for graf_name, g, ref_union, ref_cls, ref_prop in graphs:
        metrics = _all_metrics(g, ref_union, ref_cls, ref_prop)
        for metric, value in metrics.items():
            rows.append({"graf": graf_name, "metryka": metric, "wartosc": value})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["graf", "metryka", "wartosc"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nMetrics written to {out_csv}\n")

    # ── Console summary ───────────────────────────────────────────────────────
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_metric[r["metryka"]][r["graf"]] = r["wartosc"]

    col = max(len(m) for m in by_metric)
    print(f"{'metryka':<{col}}  {'unia_input':>15}  {'merged_ontology':>16}")
    print("─" * (col + 35))
    for metric, vals in by_metric.items():
        u = vals.get("unia_input", "—")
        m = vals.get("merged_ontology", "—")
        u_s = f"{u:>15.4f}" if isinstance(u, float) else f"{'—':>15}"
        m_s = f"{m:>16.4f}" if isinstance(m, float) else f"{'—':>16}"
        print(f"{metric:<{col}}{u_s}{m_s}")


if __name__ == "__main__":
    main()
