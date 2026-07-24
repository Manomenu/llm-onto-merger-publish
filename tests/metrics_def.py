#!/usr/bin/env python3
"""
Compute ontology quality metrics based on 7 academic quality dimensions.

Metrics are derived from the Ewaluacja sections of each dimension:
  1. Structural Coherence          — ARC, unsatisfiable_classes, cycle_count
  2. Domain Coherence              — (case study only; no automated metric)
  3. Conciseness                   — syntactic_uniqueness_ratio, ALC
  4. Knowledge Completeness        — cross_onto_relations_count
  5. Hierarchy Integration Quality — cross_onto_subclassof_count, connectivity_ratio,
                                     average_depth, max_depth, average_breadth, max_breadth, ARC
  6. Accuracy                      — triple_preservation_ratio
  7. Understandability             — annotation_coverage_ratio

Usage:
    python tests/metrics_def.py <folder_name>

Reads:
    tests/inputs/<folder_name>/*.owl
    tests/outputs/<folder_name>/merged_ontology.owl
    tests/outputs/<folder_name>/applied_alignments.owl  (optional)

Writes:
    tests/outputs/<folder_name>/metrics_def.csv
    tests/outputs/<folder_name>/metrics_def.html
"""

import argparse
import csv
import json
import multiprocessing
import sys
from collections import defaultdict, deque
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, Literal, URIRef

_OWL_DISJOINT_WITH = OWL.disjointWith
_OWL_CLASS = OWL.Class
_OWL_OBJ = OWL.ObjectProperty
_OWL_DATA = OWL.DatatypeProperty
_OWL_ANN = OWL.AnnotationProperty
_OWL_FP = OWL.FunctionalProperty
_OWL_IFP = OWL.InverseFunctionalProperty
_OWL_THING = OWL.Thing
_SUB = RDFS.subClassOf
_LABEL = RDFS.label
_COMMENT = RDFS.comment
_PROP_TYPES = (_OWL_OBJ, _OWL_DATA, _OWL_ANN, _OWL_FP, _OWL_IFP)

# Understandability — synonym & definition predicates
# Category name → (css-abbreviation, badge-colour)
_CATEGORIES: dict[str, tuple[str, str]] = {
    "Structural Coherence": ("sc", "#c0392b"),
    "Domain Coherence": ("dc", "#8e44ad"),
    "Conciseness": ("cn", "#16a085"),
    "Knowledge Completeness": ("kc", "#27ae60"),
    "Hierarchy Integration Quality": ("hi", "#2980b9"),
    "Accuracy": ("ac", "#d35400"),
    "Understandability": ("un", "#7f8c8d"),
}

# Display names for tool columns (used in HTML headers, console summary, and
# downstream by metrics_and_insights_raport.py / chart legends).  Internal
# dictionary keys stay technical (union_input / merged_ontology / ...) — this
# map is rendering-only.
_COLUMN_DISPLAY: dict[str, str] = {
    "union_input":         "Naive Union",
    "applied_alignments":  "Applied Alignments",
    "arom_ontology":       "AROM",
    "comerger_ontology":   "CoMerger",
    "boomer_ontology":     "Boomer",
    "merged_ontology":     "Our Solution",
}

# ── Metric registry ────────────────────────────────────────────────────────────
_REGISTRY: dict[str, dict] = {
    # ── Structural Coherence ───────────────────────────────────────────────────
    "ARC": {
        "source": "self-implemented",
        "categories": ["Structural Coherence", "Hierarchy Integration Quality"],
        "target": "low (ideally 1)",
        "interpretation": (
            "Absolute Root Cardinality — liczba klas bez nazwanego rodzica (korzeni hierarchii). "
            "Wartość 1 = spójna hierarchia z jednym korzeniem, brak orphan classes. "
            "Wymiar SC: każda klasa niebędąca korzeniem powinna mieć nazwaną nadklasę. "
            "Wymiar HIQ: ARC maleje gdy klasy-korzenie z obu ontologii zostają powiązane "
            "przez cross-ontology is-a lub zgrupowane pod wspólnym przodkiem."
        ),
    },
    # "unsatisfiable_classes": disabled — HermiT too slow on large ontologies
    "cycle_count": {
        "source": "self-implemented",
        "categories": ["Structural Coherence"],
        "target": "= 0",
        "interpretation": (
            "Liczba cykli (back edges) w grafie skierowanym relacji subClassOf, "
            "wykrytych przez iteracyjny DFS. Docelowo = 0 — hierarchia klas powinna "
            "być acyklicznym grafem skierowanym (DAG) zakotwiczonym w owl:Thing. "
            "Cykl is-a (A ⊑ B ⊑ A) jest semantyczną sprzecznością."
        ),
    },
    # ── Conciseness ───────────────────────────────────────────────────────────
    "syntactic_uniqueness_ratio": {
        "source": "self-implemented",
        "categories": ["Conciseness"],
        "target": "= 1.0",
        "interpretation": (
            "Syntactic Uniqueness Ratio = liczba unikalnych nazw lokalnych klas / "
            "całkowita liczba URI klas. Wartość < 1.0 = duplikaty nazw pod różnymi "
            "namespace'ami (np. onto1:Person i onto2:Person jako osobne klasy). "
            "Docelowo = 1.0: żadne dwie klasy nie mają tej samej nazwy lokalnej."
        ),
    },
    "structural_redundancy": {
        "source": "self-implemented",
        "categories": ["Conciseness"],
        "target": "= 0",
        "interpretation": (
            "Odsetek klas z asertowaną krawędzią rdfs:subClassOf wywodliwą "
            "z pozostałych asercji przez przechodniość subsumpcji: c ma rodziców "
            "p1 ≠ p2, przy czym p2 jest przodkiem p1 (istnieje ścieżka p1 →* p2 "
            "omijająca c). Diament — nieporównywalni rodzice o jedynie wspólnym "
            "przodku — NIE jest liczony (legalne wielodziedziczenie). "
            "Znormalizowane przez |C| → wartość w [0,1] porównywalna między "
            "datasetami. Target = 0."
        ),
    },
    "ALC": {
        "source": "self-implemented",
        "categories": ["Conciseness", "Hierarchy Integration Quality"],
        "target": "context-dependent",
        "interpretation": (
            "Absolute Leaf Cardinality — liczba klas bez podklas (liści). "
            "Wymiar C: spada po merge = mniej duplikatów liści = lepsza deduplication; "
            "interpretować razem z triple_preservation_ratio (zbyt duży spadek = utrata wiedzy). "
            "Wymiar HIQ: po dodaniu cross-ontology is-a część liści staje się węzłami pośrednimi."
        ),
    },
    # ── Knowledge Completeness ────────────────────────────────────────────────
    "cross_onto_relations_count": {
        "source": "self-implemented",
        "categories": ["Knowledge Completeness"],
        "target": "high",
        "interpretation": (
            "Liczba wszystkich relacji RDF (dowolny predykat) łączących encje z Onto1 "
            "z encjami z Onto2 w scalonej ontologii. Dla naiwnej unii = 0. "
            "Wzrost po merge = nowa wiedza emergentna — fakty nieobecne w żadnym źródle "
            "osobno, powstałe przez połączenie obu ontologii."
        ),
    },
    "corc_per_applied_alignment": {
        "source": "self-implemented",
        "categories": ["Knowledge Completeness"],
        "target": "high",
        "interpretation": (
            "CORC / liczba_scaleń. Normalizuje liczbę relacji cross-onto przez liczbę "
            "wykonanych scaleń (encji z proweniencją z obu ontologii). "
            "Dla narzędzi scalających w nowy namespace (AROM, CoMerger, Our Solution): "
            "mianownik = liczba encji 'both'. Dla narzędzi tylko asertujących equivalentClass "
            "(Applied Alignments, Boomer): mianownik = CORC (każde alignment = 1 relacja → ratio = 1.0). "
            "Wyższy wynik oznacza, że każde scalenie generuje więcej faktów cross-onto."
        ),
    },
    "new_cross_onto_relations_count": {
        "source": "self-implemented",
        "categories": ["Knowledge Completeness"],
        "target": "high",
        "interpretation": (
            "Liczba NOWYCH cross-ontologicznych relacji (dowolny predykat) — "
            "tripli łączących encje z różnych ontologii, których NIE da się "
            "wyprowadzić z unii przez samo relabelowanie aliasu (po normalizacji "
            "old_to_new). Naive collapse zamienia intra-onto triple na cross-onto "
            "przez tagowanie 'both', ale po normalizacji local-name pair jest "
            "identyczny z source — więc się nie liczy. Liczy tylko genuinely "
            "dodaną wiedzę między ontologiami (np. LLM-created cross-onto axioms). "
            "Target: wysokie = wartościowe scalanie semantyki."
        ),
    },
    "new_intra_onto_relations_count": {
        "source": "self-implemented",
        "categories": ["Knowledge Completeness"],
        "target": "context-dependent",
        "interpretation": (
            "Liczba nowych relacji RDF (dowolny predykat) łączących dwie encje z TEJ SAMEJ "
            "ontologii źródłowej (Onto1↔Onto1 lub Onto2↔Onto2), nieobecnych w unii wejściowej. "
            "Wysoka wartość może wskazywać na uwidocznienie implicit relacji domenowych "
            "— model scalający sprawia, że stają się explicit. "
            "Niska wartość sugeruje, że model głównie łączył ontologie, bez uzupełniania "
            "wiedzy wewnątrz każdej z nich."
        ),
    },
    "triple_count_delta": {
        "source": "self-implemented",
        "categories": ["Knowledge Completeness"],
        "target": "high",
        "interpretation": (
            "Różnica liczby trójek RDF między scaloną ontologią a unią ontologii wejściowych "
            "(merged_triples − union_triples). "
            "Wartość dodatnia = metoda dodała nową wiedzę; "
            "wartość zero = czyste remapowanie bez przyrostu; "
            "wartość ujemna = metoda usunęła aksjomaty (np. coherence repair)."
        ),
    },
    # ── Hierarchy Integration Quality ─────────────────────────────────────────
    "cross_onto_subclassof_count": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality", "Knowledge Completeness"],
        "target": "high",
        "interpretation": (
            "Liczba relacji SubClassOf łączących klasę z Onto1 z klasą z Onto2 "
            "(lub odwrotnie) w scalonej ontologii. Dla naiwnej unii = 0. "
            "Wyższy wynik = silniejsze zszycie hierarchii obu ontologii. "
            "Per He et al. (2022): bez cross-ontology is-a ~58% klas jest odłączonych "
            "od reszty hierarchii."
        ),
    },
    "connectivity_ratio": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "= 1.0",
        "interpretation": (
            "Connectivity Ratio = liczba klas mających co najmniej jednego nazwanego rodzica "
            "przez relację SubClassOf / całkowita liczba klas. "
            "Klasa bez żadnego rodzica (korzeń hierarchii lub izolowany węzeł) nie jest liczona. "
            "Docelowo = 1.0: każda klasa podłączona do hierarchii."
        ),
    },
    "average_depth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "higher after merge",
        "interpretation": (
            "Średnia głębokość hierarchii klas (śr. liczba krawędzi SubClassOf od "
            "owl:Thing do klasy). Wzrost po merge = klasy jednej ontologii zagnieżdżone "
            "głębiej w hierarchii drugiej przez nowe cross-ontology is-a."
        ),
    },
    "max_depth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "higher after merge",
        "interpretation": (
            "Maksymalna głębokość drzewa klas (najdłuższa ścieżka od korzenia do liścia). "
            "Wzrost = encje jednej ontologii zostały zagnieżdżone głębiej w hierarchii drugiej."
        ),
    },
    "average_breadth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "context-dependent",
        "interpretation": (
            "Średnia liczba bezpośrednich podklas na węzeł posiadający dzieci. "
            "Wzrost = klasy jednej ontologii zyskały podklasy z drugiej; "
            "bardzo wysoka wartość sugeruje brak pośrednich kategorii taksonomicznych."
        ),
    },
    "max_breadth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "context-dependent",
        "interpretation": (
            "Maksymalna liczba bezpośrednich podklas jednej klasy. "
            "Bardzo wysoka wartość = 'klasa-worek' skupiająca wiele pojęć bez pośrednich "
            "poziomów — sygnał do wprowadzenia dodatkowych kategorii taksonomicznych."
        ),
    },
    # ── Accuracy ──────────────────────────────────────────────────────────────
    "triple_preservation_ratio": {
        "source": "self-implemented",
        "categories": ["Accuracy"],
        "target": "= 1.0",
        "interpretation": (
            "Triple Preservation Ratio = liczba trójek RDF z Onto1 ∪ Onto2 "
            "(porównanie po lokalnych nazwach S/P/O, z normalizacją przez alias LLM) "
            "obecnych w scalonej ontologii / całkowita liczba trójek w Onto1 ∪ Onto2. "
            "Docelowo = 1.0. Niska wartość = duże straty wiedzy źródłowej wymagające uzasadnienia."
        ),
    },
    # ── Domain Coherence ──────────────────────────────────────────────────────
    "applied_alignments": {
        "source": "self-implemented",
        "categories": ["Domain Coherence"],
        "target": "context-dependent",
        "interpretation": (
            "Liczba alignmentów faktycznie zastosowanych przez LLM (Was_Alignment_Applied=true). "
            "Kolumna applied_alignments = wszystkie alignmenty wejściowe (każdy zastosowany "
            "bezwarunkowo na etapie apply_alignments). Kolumna merged_ontology = ile LLM zaakceptował "
            "po weryfikacji kontekstu (relacji, properties, typów). "
            "Różnica wskazuje ile par alignmentu LLM uznał za niepoprawne i pozostawił rozdzielone."
        ),
    },
    "multi_domain_range_change_per_alignment": {
        "source": "self-implemented",
        "categories": ["Domain Coherence"],
        "target": "= 0",
        "interpretation": (
            "Liczba nowo wprowadzonych multi-domain/range properties (merged - union) "
            "podzielona przez liczbę zaaplikowanych alignments. "
            "Mierzy ile konfliktów domain/range metoda średnio wprowadza na jeden "
            "zaakceptowany alignment. Target = 0: metoda nie tworzy nowych konfliktów. "
            "Wartość dodatnia = metoda agresywnie scala koncepty o niezgodnych "
            "zakresach (intersection inference issues)."
        ),
    },
    "multi_domain_range_count": {
        "source": "self-implemented",
        "categories": ["Domain Coherence"],
        "target": "= 0",
        "interpretation": (
            "Number of properties with more than one rdfs:domain or rdfs:range declaration "
            "in the merged ontology. OWL interprets multiple domain/range axioms as their "
            "intersection (conjunction): if a property has domain A and domain B, every "
            "instance using it is inferred to belong to both A and B simultaneously — "
            "causing unintended inferences or unsatisfiability when A and B are disjoint. "
            "Target = 0: each property should declare at most one domain and at most one range."
        ),
    },
    # ── Understandability ─────────────────────────────────────────────────────
    "annotation_coverage_ratio": {
        "source": "self-implemented",
        "categories": ["Understandability"],
        "target": "= 1.0",
        "interpretation": (
            "Annotation Coverage Ratio = liczba encji (klas + właściwości) posiadających "
            "rdfs:label lub rdfs:comment / całkowita liczba encji. Docelowo = 1.0. "
            "Opatrzone etykietami encje umożliwiają ekspertom domenowym weryfikację "
            "semantycznej poprawności i spójności ontologii po scaleniu."
        ),
    },
    "comment_coverage_ratio": {
        "source": "self-implemented",
        "categories": ["Understandability"],
        "target": "= 1.0",
        "interpretation": (
            "Comment Coverage Ratio = liczba encji (klas + właściwości) posiadających "
            "rdfs:comment / całkowita liczba encji. Docelowo = 1.0. "
            "Bardziej rygorystyczna miara niż ACR — wymaga pełnej dokumentacji "
            "(comment), nie tylko etykiety. Per Osman et al. (2021): "
            "comments są kluczowe dla użyteczności dziedzinowej scalonej ontologii."
        ),
    },
}


# ── rdflib helpers ─────────────────────────────────────────────────────────────


def _load_graph(path: str) -> Graph:
    g = Graph()
    g.parse(path)
    for t in list(g.triples((None, _OWL_DISJOINT_WITH, None))):
        g.remove(t)
    return g


def _local(uri: URIRef) -> str:
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


# Predicates whose subject/object are semantically interchangeable.  Tools like
# AROM may re-serialize these in the opposite direction from the raw input
# (e.g. input has `RO_0002212 owl:inverseOf RO_0002335`, output has the
# reverse), which would otherwise register as a spurious "new relation" in the
# NCRC/NIRC set-difference below.
_SYMMETRIC_PREDICATES = frozenset(
    {OWL.inverseOf, OWL.equivalentClass, OWL.equivalentProperty, _OWL_DISJOINT_WITH, OWL.sameAs}
)


def _canon_key(p: URIRef, s_key: str, p_key: str, o_key: str) -> tuple[str, str, str]:
    """Build an (s, p, o) key, ordering subject/object lexicographically for
    symmetric predicates so that a direction-flipped triple maps to the same
    key.  No-op for other predicates."""
    if p in _SYMMETRIC_PREDICATES and o_key < s_key:
        s_key, o_key = o_key, s_key
    return (s_key, p_key, o_key)


def _classes(g: Graph) -> set[URIRef]:
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
    result: set[URIRef] = set()
    for ptype in _PROP_TYPES:
        for s in g.subjects(RDF.type, ptype):
            if isinstance(s, URIRef):
                result.add(s)
    return result


# ── Self-implemented metric computation ────────────────────────────────────────


def _count_cycles(g: Graph) -> int:
    """Count back-edges in the subClassOf directed graph (each = one cycle)."""
    adj: dict[URIRef, list[URIRef]] = defaultdict(list)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and o != _OWL_THING:
            adj[s].append(o)

    all_nodes: set[URIRef] = set(adj.keys())
    for vs in adj.values():
        all_nodes.update(vs)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[URIRef, int] = {n: WHITE for n in all_nodes}
    cycles = 0

    for start in all_nodes:
        if color[start] != WHITE:
            continue
        stack: list[tuple[URIRef, int]] = [(start, 0)]
        color[start] = GRAY
        while stack:
            node, ci = stack[-1]
            neighbors = adj[node]
            if ci < len(neighbors):
                stack[-1] = (node, ci + 1)
                child = neighbors[ci]
                c = color[child]
                if c == GRAY:
                    cycles += 1
                elif c == WHITE:
                    color[child] = GRAY
                    stack.append((child, 0))
            else:
                color[node] = BLACK
                stack.pop()

    return cycles


def _multi_domain_range_count(g: Graph) -> float:
    """Count properties with more than one rdfs:domain or rdfs:range declaration.

    OWL interprets multiple domain/range axioms as conjunction, so an unintended
    second declaration causes unexpected inferences (or unsatisfiability if the
    two classes are disjoint).  Target = 0.
    """
    dom: dict[URIRef, int] = {}
    rng: dict[URIRef, int] = {}
    for s, _, _ in g.triples((None, RDFS.domain, None)):
        if isinstance(s, URIRef):
            dom[s] = dom.get(s, 0) + 1
    for s, _, _ in g.triples((None, RDFS.range, None)):
        if isinstance(s, URIRef):
            rng[s] = rng.get(s, 0) + 1
    return float(sum(
        1 for p in set(dom) | set(rng)
        if dom.get(p, 0) > 1 or rng.get(p, 0) > 1
    ))


def _connectivity_ratio(g: Graph) -> float:
    """Fraction of named classes that have at least one named parent via subClassOf."""
    cls = _classes(g)
    if not cls:
        return 1.0
    has_parent = {
        s
        for s, _, o in g.triples((None, _SUB, None))
        if isinstance(s, URIRef) and isinstance(o, URIRef) and s in cls and o in cls
    }
    return len(has_parent) / len(cls)


def _structural_redundancy(g: Graph) -> float:
    """Fraction of classes with an asserted rdfs:subClassOf edge derivable from the rest.

    A class c is structurally redundant iff it has two distinct named parents p1, p2
    such that p2 ∈ Anc(p1) — i.e. there is an asserted subClassOf chain p1 →* p2, so
    the asserted edge c ⊑ p2 follows from c ⊑ p1 by subsumption transitivity
    (redundancy proper, sensu Grimm & Wissmann 2011).  A diamond — incomparable
    parents that merely share a common ancestor — is NOT counted: that is legitimate
    multiple inheritance.  Justification chains passing through c itself (possible
    only on an is-a cycle) are rejected via a local re-check that skips c.
    Normalised by |C| → ratio in [0,1] comparable across datasets.
    """
    cls = _classes(g)
    if not cls:
        return 0.0

    parents: dict[URIRef, set[URIRef]] = defaultdict(set)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and s in cls and o in cls:
            parents[s].add(o)

    _ancestor_cache: dict[URIRef, frozenset[URIRef]] = {}

    def ancestors_inclusive(start: URIRef) -> frozenset[URIRef]:
        if start in _ancestor_cache:
            return _ancestor_cache[start]
        visited: set[URIRef] = set()
        queue: deque[URIRef] = deque([start])
        while queue:
            n = queue.popleft()
            if n in visited:
                continue
            visited.add(n)
            for p in parents.get(n, set()):
                if p not in visited:
                    queue.append(p)
        result = frozenset(visited)
        _ancestor_cache[start] = result
        return result

    def reaches_avoiding(start: URIRef, target: URIRef, banned: URIRef) -> bool:
        """True iff an asserted subClassOf chain start →* target avoids `banned`."""
        visited: set[URIRef] = set()
        queue: deque[URIRef] = deque([start])
        while queue:
            n = queue.popleft()
            if n == banned or n in visited:
                continue
            if n == target:
                return True
            visited.add(n)
            queue.extend(parents.get(n, set()))
        return False

    redundant = 0
    for c, ps in parents.items():
        if len(ps) < 2:
            continue
        is_redundant = False
        for p1 in ps:
            anc = ancestors_inclusive(p1)
            for p2 in ps:
                if p2 is p1 or p2 == p1 or p2 not in anc:
                    continue
                # Fast path is sound unless the chain could run through c
                # itself (c on a cycle above p1); then verify avoiding c.
                if c not in anc or reaches_avoiding(p1, p2, banned=c):
                    is_redundant = True
                    break
            if is_redundant:
                break
        if is_redundant:
            redundant += 1

    return round(redundant / len(cls), 6)


def _hierarchy_stats(g: Graph, cls: set[URIRef]) -> dict[str, float]:
    """Compute ALC, depth and breadth metrics from the subClassOf hierarchy."""
    if not cls:
        return {
            "ALC": 0.0,
            "average_depth": 0.0,
            "max_depth": 0.0,
            "average_breadth": 0.0,
            "max_breadth": 0.0,
        }

    children: dict[URIRef, list[URIRef]] = defaultdict(list)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and s in cls:
            children[o].append(s)

    alc = float(sum(1 for c in cls if not children.get(c)))

    # Root classes: have no named parent within cls (plus owl:Thing as universal root).
    has_named_parent: set[URIRef] = {
        s for s, _, o in g.triples((None, _SUB, None))
        if isinstance(s, URIRef) and isinstance(o, URIRef) and s in cls and o in cls
    }
    roots = (cls - has_named_parent) | {_OWL_THING}

    depths: dict[URIRef, int] = {}
    queue: deque[tuple[URIRef, int]] = deque((r, 0) for r in roots)
    visited: set[URIRef] = set(roots)
    while queue:
        node, d = queue.popleft()
        for child in children.get(node, []):
            if child not in visited:
                visited.add(child)
                depths[child] = d + 1
                queue.append((child, d + 1))

    depth_vals = list(depths.values())
    avg_depth = sum(depth_vals) / len(depth_vals) if depth_vals else 0.0
    max_depth = float(max(depth_vals)) if depth_vals else 0.0

    breadths = [len(ch) for node, ch in children.items() if node in cls and ch]
    avg_breadth = sum(breadths) / len(breadths) if breadths else 0.0
    max_breadth = float(max(breadths)) if breadths else 0.0

    return {
        "ALC": alc,
        "average_depth": round(avg_depth, 4),
        "max_depth": max_depth,
        "average_breadth": round(avg_breadth, 4),
        "max_breadth": max_breadth,
    }


_ALIAS_PRED = "http://merged#alias"


_WELL_KNOWN_NS = frozenset(
    str(ns)
    for ns in (RDF, RDFS, OWL, XSD)
)


def _primary_ns(entities: set[URIRef]) -> str:
    """Namespace (prefix up to and including '#') with the most URIs, ignoring well-known namespaces."""
    from collections import Counter
    counts: Counter[str] = Counter()
    for u in entities:
        s = str(u)
        ns = s[: s.index("#") + 1] if "#" in s else (s[: s.rindex("/") + 1] if "/" in s else "")
        if ns and ns not in _WELL_KNOWN_NS:
            counts[ns] += 1
    return counts.most_common(1)[0][0] if counts else ""


def _build_alias_maps(
    g: Graph,
    onto1_locals: set[str],
    onto2_locals: set[str],
    arom_provenance: dict[str, dict[str, str]] | None = None,
    relabeling_map: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build local-name alias maps from the merged graph.

    Formats supported:
      1. LLM merger format — `merged#alias` triples with literal "code;;LocalName"
      2. AROM format — `code_provenance` dict from arom_stats.json (keyed by URI,
         values are {"<ontology_n>": "<local_name>"}).  Passed via arom_provenance.
      3. create_ontology relabeling map (old_local → new_local for rdfs:label renames)
      4. CoMerger merged# entities — URI local name encodes two source IDs with
         underscores stripped, joined by a single '_':
         e.g. merged#MA0000009_NCIC12472 from MA_0000009 + NCI_C12472.

    Returns (old_to_new, new_to_source, uri_to_new_local) where:
      old_to_new: OldLocalName → NewLocalName  (for renaming normalisation)
      new_to_source: NewLocalName → 'onto1' | 'onto2' | 'both'  (attribution)
      uri_to_new_local: full source URI → merged local name (precise aliasing,
                       avoids over-mapping built-ins that share local names)
    """
    old_to_new: dict[str, str] = {}
    new_to_source: dict[str, str] = {}
    uri_to_new_local: dict[str, str] = {}

    # Inverse relabeling: new_human_readable → old_coded.
    # Needed for Format 1: LLM aliases store post-relabeling names (human-readable)
    # rather than original coded names, so we reverse-map to identify the source ontology.
    inv_relabeling: dict[str, str] = {}
    if relabeling_map:
        for old_coded, new_human in relabeling_map.items():
            inv_relabeling[new_human] = old_coded

    # Format 1: LLM merger (zz::alias / merged#alias triples)
    for s, p, o in g:
        if (
            str(p) != _ALIAS_PRED
            or not isinstance(s, URIRef)
            or not isinstance(o, Literal)
        ):
            continue
        parts = str(o).split(";;", 1)
        if len(parts) != 2 or not parts[1]:
            continue
        old_local = parts[1]
        # Alias names are post-relabeling (human-readable); resolve back to coded name
        # via the inverse relabeling map so that onto1/onto2 membership is detectable.
        resolved = inv_relabeling.get(old_local, old_local)
        new_local = _local(s)
        old_to_new[resolved] = new_local
        in1 = resolved in onto1_locals
        in2 = resolved in onto2_locals
        src = "both" if in1 and in2 else ("onto1" if in1 else ("onto2" if in2 else ""))
        if src:
            existing = new_to_source.get(new_local)
            new_to_source[new_local] = "both" if existing and existing != src else src

    # Format 2: AROM provenance map (Code_X URIs with per-source rdfs:label)
    # NEW: when provenance carries full source URIs ("1_uri"/"2_uri") we map by
    # URI (precise — only the actually aligned entity is normalised, no
    # collateral damage to built-ins like owl:Class that share local names).
    # Legacy fallback: when only local names are present, map by local name
    # (over-aliases when two distinct source entities share the same local).
    if arom_provenance:
        for code_uri, by_onto in arom_provenance.items():
            new_local = _local(URIRef(code_uri))
            in1 = "1" in by_onto
            in2 = "2" in by_onto
            src = "both" if in1 and in2 else ("onto1" if in1 else ("onto2" if in2 else ""))
            if src:
                existing = new_to_source.get(new_local)
                new_to_source[new_local] = "both" if existing and existing != src else src
            has_uris = any(k.endswith("_uri") for k in by_onto)
            if has_uris:
                for key, val in by_onto.items():
                    if key.endswith("_uri") and val:
                        uri_to_new_local[val] = new_local
            else:
                for source_local in by_onto.values():
                    old_to_new[source_local] = new_local

    # Format 3: create_ontology relabeling map (old_local → new_local for rdfs:label renames)
    if relabeling_map:
        for old_local, new_local in relabeling_map.items():
            if old_local not in old_to_new:
                old_to_new[old_local] = new_local

    # Format 4: CoMerger merged# entities
    # URI format: http://merged#{id1_stripped}_{id2_stripped} where the source IDs
    # had their underscores removed before joining (NCI_C12472 → NCIC12472,
    # MA_0000009 → MA0000009).  Build a normalized (no-underscore) lookup to
    # reverse-match the split parts against known source entity local names.
    onto1_norm = {loc.replace("_", "").lower(): loc for loc in onto1_locals}
    onto2_norm = {loc.replace("_", "").lower(): loc for loc in onto2_locals}
    _COMERGER_NS = "http://merged#"
    for s in g.subjects():
        if not isinstance(s, URIRef):
            continue
        s_str = str(s)
        if not s_str.startswith(_COMERGER_NS):
            continue
        local_name = _local(s)
        if "_" not in local_name or local_name in new_to_source:
            continue  # skip already-tagged or no-split URIs
        idx = local_name.index("_")
        p1 = local_name[:idx].lower()
        p2 = local_name[idx + 1:].lower()
        if p1 in onto1_norm and p2 in onto2_norm:
            new_to_source[local_name] = "both"
            old_to_new[onto1_norm[p1]] = local_name
            old_to_new[onto2_norm[p2]] = local_name
        elif p1 in onto2_norm and p2 in onto1_norm:
            new_to_source[local_name] = "both"
            old_to_new[onto2_norm[p1]] = local_name
            old_to_new[onto1_norm[p2]] = local_name

    return old_to_new, new_to_source, uri_to_new_local


def _compute_self_metrics(
    g: Graph,
    onto1_entities: set[URIRef],
    onto2_entities: set[URIRef],
    union: Graph | None = None,
    arom_provenance: dict[str, dict[str, str]] | None = None,
    relabeling_map: dict[str, str] | None = None,
    applied_alignments_count: int | None = None,
) -> dict[str, float]:
    cls = _classes(g)
    prop = _properties(g)
    n_c = len(cls)

    onto1_locals = {_local(e) for e in onto1_entities}
    onto2_locals = {_local(e) for e in onto2_entities}

    # Namespace-primary + alias-aware source attribution.
    #
    # Priority order for determining whether a URI is "from onto1" or "from onto2":
    #   1. Original URI membership in onto1_entities / onto2_entities (exact match).
    #   2. Namespace check: if the URI's namespace equals onto1's dominant namespace
    #      (and not onto2's), attribute to onto1, and vice-versa.  This handles LLM
    #      outputs that create human-readable names inside the original ontology
    #      namespaces (e.g. human.owl#Membrane when original used NCI codes).
    #   3. Alias / provenance fallback for entities in a third namespace (e.g. zz::,
    #      merged::, AROM's merging::).  These use _build_alias_maps / arom_provenance
    #      and may be tagged "both" (merged from one entity in each ontology).
    #
    _, new_to_source, _ = _build_alias_maps(
        g, onto1_locals, onto2_locals, arom_provenance=arom_provenance,
        relabeling_map=relabeling_map,
    )
    onto1_ns = _primary_ns(onto1_entities)
    onto2_ns = _primary_ns(onto2_entities)

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

    # ARC — classes without a named parent
    has_named_parent = {
        s
        for s, _, o in g.triples((None, _SUB, None))
        if isinstance(s, URIRef)
        and isinstance(o, URIRef)
        and o != _OWL_THING
        and s in cls
    }
    arc = float(len(cls - has_named_parent))

    cycle_count = float(_count_cycles(g))

    unique_local = len({_local(c) for c in cls})
    syntactic_uniqueness_ratio = unique_local / n_c if n_c else 1.0

    # Cross-ontology predicate: a triple is cross-onto when the endpoints cover
    # different ontologies.  Rules (applied uniformly to all tools):
    #   • both purely onto1 → excluded (intra-onto1)
    #   • both purely onto2 → excluded (intra-onto2)
    #   • both "both"-tagged (merged↔merged) → excluded: these relations were
    #     inherited simultaneously from both source ontologies and are not new
    #   • "both"↔single-ontology → counted: the merged entity carries the other
    #     ontology's representative, so the triple crosses ontology boundaries
    def _is_cross(s, o) -> bool:
        s1, s2 = _from_onto1(s), _from_onto2(s)
        o1, o2 = _from_onto1(o), _from_onto2(o)
        if (s1 and s2) and (o1 and o2):        # merged ↔ merged → excluded
            return False
        if (s1 and not s2) and (o1 and not o2): # both purely onto1
            return False
        if (s2 and not s1) and (o2 and not o1): # both purely onto2
            return False
        return (s1 and o2) or (s2 and o1)

    cross_sub = sum(
        1
        for s, _, o in g.triples((None, _SUB, None))
        if _is_cross(s, o)
    )
    cross_rel = sum(
        1
        for s, _, o in g
        if _is_cross(s, o)
    )

    both_count = sum(1 for v in new_to_source.values() if v == "both")
    if applied_alignments_count is not None:
        _denom = applied_alignments_count
    else:
        _denom = both_count if both_count > 0 else cross_rel
    corc_per_applied = round(cross_rel / _denom, 4) if _denom > 0 else 0.0

    # Multi D/R newly added by the merge, normalised by applied alignments.
    # Multi D/R is inherent to source properties (collapse_alignments preserves it),
    # so comparing absolute counts unfairly favours methods that apply fewer alignments.
    # This delta-per-alignment isolates the conflict actually introduced.
    if union is not None:
        mdr_g = _multi_domain_range_count(g)
        mdr_u = _multi_domain_range_count(union)
        mdr_delta = mdr_g - mdr_u
        _mdr_change_per_alignment = round(mdr_delta / _denom, 6) if _denom > 0 else 0.0
    else:
        _mdr_change_per_alignment = 0.0

    connectivity = _connectivity_ratio(g)

    # Triple preservation ratio vs union
    # BNode objects are excluded: their internal IDs differ across parse sessions,
    # so str(bnode) comparisons produce false negatives for restrictions/unions.
    if union is not None:
        old_to_new, _, uri_to_new_local = _build_alias_maps(
            g, onto1_locals, onto2_locals, arom_provenance=arom_provenance,
            relabeling_map=relabeling_map,
        )

        def _norm(local: str) -> str:
            return old_to_new.get(local, local)

        def _norm_uri(u) -> str:
            """Prefer URI-based aliasing if available — avoids over-mapping
            built-ins (e.g. owl:Class) when they share local names with
            actually aligned entities (e.g. oboInOwl:Class).
            Falls back to local-name aliasing for legacy provenance without URIs.
            """
            if isinstance(u, URIRef):
                return uri_to_new_local.get(str(u), _norm(_local(u)))
            return str(u)

        def _key(s, p, o) -> tuple[str, str, str]:
            return (
                _local(s),
                _local(p),
                _local(o) if isinstance(o, URIRef) else str(o),
            )

        def _key_norm(s, p, o) -> tuple[str, str, str]:
            return (_norm_uri(s), _norm_uri(p), _norm_uri(o))

        union_triples = {
            _key_norm(s, p, o)
            for s, p, o in union
            if isinstance(s, URIRef) and not isinstance(o, BNode)
            and p != _LABEL  # rdfs:label is encoded in the URI by create_ontology — not truly lost
        }
        g_triples = {
            _key(s, p, o)
            for s, p, o in g
            if isinstance(s, URIRef) and not isinstance(o, BNode)
            and p != _LABEL
        }
        tpr = (
            len(g_triples & union_triples) / len(union_triples)
            if union_triples
            else 1.0
        )

        # New intra-ontology relations (alias-aware): triples in g where both S and O
        # belong to the SAME source (including renamed entities), but the triple
        # (by local-name key) is absent from union.
        #
        # For "both"-tagged merged entities whose local name belongs to one of the
        # original namespaces (e.g. merged#NCI_C12814 where NCI_C12814 ∈ onto1_locals),
        # we resolve to that primary source so intra-onto triples via merged entities
        # are counted correctly.
        # Alias/relabel-normalised union keys, shared by NIRC and NCRC so both
        # measure novelty against the SAME baseline.  _norm_uri folds two kinds
        # of identity change back onto the merged names: (a) entity-merge aliases
        # (Y aligned to X → Y's local name maps to X's), so naive collapse of
        # `Y subClassOf Z` into `merged#X subClassOf Z` matches the original union
        # triple and is NOT counted as new; (b) OBO relabeling (NCI_C12345 →
        # Hippocampus), so a relation that merely survived relabeling is not
        # mistaken for newly introduced knowledge.  Only genuinely new edges
        # introduced by the merge logic remain.
        union_keys_norm = {
            _canon_key(p, _norm_uri(s), _norm_uri(p), _norm_uri(o))
            for s, p, o in union
            if isinstance(s, URIRef) and isinstance(o, URIRef)
        }

        # Raw (un-normalised) union triples by local name.  A relation whose raw
        # local-name triple already appears verbatim in the union is present in a
        # source ontology and therefore NOT new, even when alias/relabel
        # normalisation of one endpoint desyncs its canonical key from the union's
        # (e.g. AROM re-serialising SWO obsolescence axioms such as
        # `X IAO_0100001 Y` or `X subClassOf ObsoleteClass`, which exist in the
        # input SWO but whose normalised key no longer matches).
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
            """Resolve entity to single source for NIRC.

            Attribution priority MUST match _from_onto1/_from_onto2 (used by the
            cross-ontology predicate) so NIRC and NCRC stay disjoint: a relabeled
            entity living in a source's dominant namespace (e.g. human.owl#Cardiac_Valve,
            absent from onto1_entities because the original IRI was an NCI code) would
            otherwise fall through to the alias map and be mis-attributed, leaking a
            genuinely cross-ontology triple into NIRC. 'both' is resolved by
            local-name membership as before."""
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

        new_intra_rel = float(
            sum(
                1
                for s, p, o in g
                if isinstance(s, URIRef)
                and isinstance(o, URIRef)
                and not (_is_both(s) and _is_both(o))  # both↔both excluded (same as CORC rule)
                and _intra_source(s) is not None
                and _intra_source(s) == _intra_source(o)
                and _canon_key(p, _local(s), _local(p), _local(o)) not in union_keys_norm
                and _raw_key(s, p, o) not in union_raw
            )
        )

        triple_count_delta = float(len(g) - len(union))

        # NEW cross-ontology relations — triples (any predicate) that bridge
        # ontologies AND are not derivable from a union triple via alias/relabel
        # normalisation (union_keys_norm, built above and shared with NIRC).
        new_cross_rel = float(sum(
            1
            for s, p, o in g
            if isinstance(s, URIRef) and isinstance(o, URIRef)
            and _is_cross(s, o)
            and _canon_key(p, _local(s), _local(p), _local(o)) not in union_keys_norm
            and _raw_key(s, p, o) not in union_raw
        ))

    else:
        tpr = 1.0
        new_intra_rel = 0.0
        triple_count_delta = 0.0
        new_cross_rel = 0.0

    entities = cls | prop
    n_e = len(entities)
    annotated = sum(
        1
        for e in entities
        if any(True for _ in g.objects(e, _LABEL))
        or any(True for _ in g.objects(e, _COMMENT))
    )
    annotation_coverage = annotated / n_e if n_e else 0.0
    commented = sum(1 for e in entities if any(True for _ in g.objects(e, _COMMENT)))
    comment_coverage = commented / n_e if n_e else 0.0

    hierarchy = _hierarchy_stats(g, cls)

    return {
        "ARC": arc,
        "cycle_count": cycle_count,
        "syntactic_uniqueness_ratio": round(syntactic_uniqueness_ratio, 4),
        "cross_onto_subclassof_count": float(cross_sub),
        "new_cross_onto_relations_count": new_cross_rel,
        "cross_onto_relations_count": float(cross_rel),
        "corc_per_applied_alignment": corc_per_applied,
        "new_intra_onto_relations_count": new_intra_rel,
        "triple_count_delta": triple_count_delta,
        "connectivity_ratio": round(connectivity, 4),
        "triple_preservation_ratio": round(tpr, 4),
        "annotation_coverage_ratio": round(annotation_coverage, 4),
        "comment_coverage_ratio": round(comment_coverage, 4),
        "multi_domain_range_count": _multi_domain_range_count(g),
        "multi_domain_range_change_per_alignment": _mdr_change_per_alignment,
        "structural_redundancy": _structural_redundancy(g),
        **hierarchy,
    }


def _compute_suspected_counts(
    g: Graph,
    onto1_entities: set[URIRef],
    onto2_entities: set[URIRef],
    tainted_uris: set[URIRef],
) -> dict[str, int]:
    """Count metric contributions tied to alignments the LLM later rejected.

    `tainted_uris` are the merged URIs in applied_alignments.owl that originate
    from rejected alignment pairs (entity1 of each rejected pair — entity2 was
    collapsed into entity1 by apply_alignments).  Triples involving any tainted
    URI are likely incorrect since they conflate concepts the LLM considers
    semantically distinct.
    """
    if not tainted_uris:
        return {}

    onto1_locals = {_local(e) for e in onto1_entities}
    onto2_locals = {_local(e) for e in onto2_entities}
    _, new_to_source, _ = _build_alias_maps(g, onto1_locals, onto2_locals)
    onto1_ns = _primary_ns(onto1_entities)
    onto2_ns = _primary_ns(onto2_entities)

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

    def _is_tainted(u) -> bool:
        return isinstance(u, URIRef) and u in tainted_uris

    def _is_cross(s, o) -> bool:
        s1, s2 = _from_onto1(s), _from_onto2(s)
        o1, o2 = _from_onto1(o), _from_onto2(o)
        if (s1 and s2) or (o1 and o2):
            return False
        return (s1 and o2) or (s2 and o1)

    cross_sub_susp = sum(
        1
        for s, _, o in g.triples((None, _SUB, None))
        if (_is_tainted(s) or _is_tainted(o)) and _is_cross(s, o)
    )
    cross_rel_susp = sum(
        1
        for s, _, o in g
        if (_is_tainted(s) or _is_tainted(o)) and _is_cross(s, o)
    )

    return {
        "cross_onto_subclassof_count": cross_sub_susp,
        "cross_onto_relations_count": cross_rel_susp,
    }


# ── HermiT reasoner check ─────────────────────────────────────────────────────

# XSD datatypes absent from the OWL 2 datatype map — HermiT rejects them.
# See: https://www.w3.org/TR/owl2-syntax/#Datatype_Maps
_XSD_UNSUPPORTED = frozenset(
    [
        XSD.date,
        XSD.time,
        XSD.duration,
        XSD.gYear,
        XSD.gYearMonth,
        XSD.gMonth,
        XSD.gMonthDay,
        XSD.gDay,
    ]
)


def _strip_hermit_unsupported(g: Graph) -> Graph:
    """Return a copy of g safe for HermiT.

    Removes all blank-node restrictions (owl:allValuesFrom / owl:someValuesFrom /
    rdfs:range) that reference XSD datatypes not in the OWL 2 datatype map,
    plus any remaining references to those blank nodes.
    """
    bad_bnodes: set[BNode] = set()
    for s, _, o in g:
        if (isinstance(o, URIRef) and o in _XSD_UNSUPPORTED) or (
            isinstance(o, Literal) and o.datatype in _XSD_UNSUPPORTED
        ):
            if isinstance(s, BNode):
                bad_bnodes.add(s)

    result = Graph()
    for s, p, o in g:
        if isinstance(o, URIRef) and o in _XSD_UNSUPPORTED:
            continue
        if isinstance(o, Literal) and o.datatype in _XSD_UNSUPPORTED:
            continue
        if isinstance(s, BNode) and s in bad_bnodes:
            continue
        if isinstance(o, BNode) and o in bad_bnodes:
            continue
        result.add((s, p, o))
    return result


_HERMIT_TIMEOUT_S = 120


def _hermit_worker(tmp_path: str, q: "multiprocessing.Queue[dict]") -> None:
    import owlready2

    try:
        world = owlready2.World()
        onto = world.get_ontology(f"file://{tmp_path}").load()
        with onto:
            owlready2.sync_reasoner_hermit(world, infer_property_values=False)
        unsat = list(world.inconsistent_classes())
        q.put({"unsatisfiable_classes": float(len(unsat))})
    except Exception as exc:
        q.put({"unsatisfiable_classes": None, "error": str(exc)})


def _reasoner_check(g: Graph, label: str) -> dict[str, float | None]:
    """Run HermiT via owlready2 and return number of unsatisfiable classes.

    Killed after _HERMIT_TIMEOUT_S seconds to handle large/complex ontologies.
    """
    try:
        import owlready2  # noqa: F401 — availability check
    except ImportError:
        print(
            f"  [HermiT/{label}] owlready2 not installed — skipping (pip install owlready2)"
        )
        return {"unsatisfiable_classes": None}

    import os
    import tempfile

    g_safe = _strip_hermit_unsupported(g)
    stripped = len(g) - len(g_safe)
    if stripped:
        print(
            f"  [HermiT/{label}] stripped {stripped} triples with unsupported XSD datatypes"
        )

    with tempfile.NamedTemporaryFile(suffix=".owl", delete=False) as f:
        g_safe.serialize(destination=f.name, format="xml")
        tmp_path = f.name

    try:
        print(f"  → HermiT [{label}] …", end=" ", flush=True)
        q: multiprocessing.Queue = multiprocessing.Queue()
        p = multiprocessing.Process(target=_hermit_worker, args=(tmp_path, q))
        p.start()
        p.join(_HERMIT_TIMEOUT_S)
        if p.is_alive():
            p.kill()
            p.join()
            print(f"TIMEOUT (>{_HERMIT_TIMEOUT_S}s) — skipping")
            return {"unsatisfiable_classes": None}
        result = q.get_nowait()
        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            return {"unsatisfiable_classes": None}
        print(f"{int(result['unsatisfiable_classes'])} unsatisfiable classes")
        return result
    finally:
        os.unlink(tmp_path)


# ── HTML report ───────────────────────────────────────────────────────────────

_CAT_COLOR: dict[str, str] = {cat: color for cat, (_, color) in _CATEGORIES.items()}

_SOURCE_BORDER: dict[str, str] = {
    "self-implemented": "#27ae60",
    "hermit_reasoner": "#8e44ad",
}

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ontology quality metrics — {folder}</title>
<style>
  body  {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1   {{ font-size: 1.4rem; margin-bottom: 0.3rem; }}
  p.sub {{ color: #666; font-size: 0.9rem; margin: 0 0 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.87rem; }}
  th, td {{ padding: 0.5rem 0.7rem; text-align: left; vertical-align: top;
            border: 1px solid #d0d0d0; }}
  th {{ background: #2c3e50; color: #fff; white-space: nowrap; }}
  tr:nth-child(even) {{ background: #f7f7f7; }}
  tr:hover {{ background: #eaf3fb; }}
  td.num   {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.na    {{ text-align: center; color: #aaa; }}
  td.src   {{ font-size: 0.78rem; white-space: nowrap; }}
  td.tgt   {{ font-size: 0.78rem; color: #666; white-space: nowrap; }}
  td.cats  {{ max-width: 230px; }}
  td.interp {{ font-size: 0.82rem; color: #444; max-width: 320px; }}
  .badge  {{ display: inline-block; padding: 2px 7px; border-radius: 3px;
             font-size: 0.72rem; margin: 1px; color: #fff; white-space: nowrap; }}
  .legend {{ margin-top: 1.5rem; font-size: 0.8rem; }}
  .legend h3 {{ font-size: 0.85rem; margin: 0.6rem 0 0.3rem; color: #555; }}
  .legend-row {{ display: flex; flex-wrap: wrap; gap: 0.8rem; }}
  .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
  .dot  {{ width: 13px; height: 13px; border-radius: 2px; display: inline-block; flex-shrink: 0; }}
  .src-dot {{ width: 4px; height: 18px; border-radius: 2px; display: inline-block; flex-shrink: 0; }}
  .note {{ margin-top: 1rem; font-size: 0.8rem; color: #888; font-style: italic; }}
  .susp {{ color: #c0392b; font-size: 0.78rem; font-weight: 600;
           font-variant-numeric: tabular-nums; margin-left: 0.2rem; cursor: help; }}
</style>
</head>
<body>
<h1>Ontology quality metrics &mdash; <code>{folder}</code></h1>
<p class="sub">7-dimensional evaluation framework</p>
<table>
  <thead>
    <tr>
      <th>Metric</th>
      <th>Naive Union</th>
      {applied_col_header}
      {arom_col_header}
      {comerger_col_header}
      {boomer_col_header}
      <th>Our Solution</th>
      <th>Target</th>
      <th>Source</th>
      <th>Categories</th>
      <th>Interpretation</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
{legend}
<p class="note">
  Note: Domain Coherence and Conciseness (semantic) require manual case-study evaluation —
  no fully automated proxy exists for detecting semantically equivalent but differently-named concepts.
</p>
</body>
</html>
"""

_LEGEND_TEMPLATE = """\
<div class="legend">
  <h3>Source</h3>
  <div class="legend-row">
    <span class="legend-item"><span class="src-dot" style="background:#27ae60"></span> self-implemented</span>
    <span class="legend-item"><span class="src-dot" style="background:#8e44ad"></span> hermit_reasoner</span>
  </div>
  <h3>Quality dimension</h3>
  <div class="legend-row">
{cat_legend}
  </div>
</div>"""


def _fmt(v: float | None) -> str:
    if v is None:
        return '<td class="na">N/A</td>'
    if v == int(v) and abs(v) < 1e9:
        return f'<td class="num">{int(v)}</td>'
    return f'<td class="num">{v:.4f}</td>'


def _cat_badges(categories: list[str]) -> str:
    parts = []
    for cat in categories:
        color = _CAT_COLOR.get(cat, "#999")
        parts.append(f'<span class="badge" style="background:{color}">{cat}</span>')
    return "".join(parts)


def _fmt_applied(v: float | None, suspected: int) -> str:
    """Like _fmt, but appends '(X suspected)' badge when LLM rejected alignments."""
    if v is None:
        return '<td class="na">N/A</td>'
    base = f"{int(v)}" if v == int(v) and abs(v) < 1e9 else f"{v:.4f}"
    if suspected > 0:
        return (
            f'<td class="num">{base} '
            f'<span class="susp" title="liczba przyczynków metryki wynikających z alignmentów '
            f'odrzuconych przez LLM — prawdopodobnie semantycznie błędnych">'
            f'({suspected} suspected)</span></td>'
        )
    return f'<td class="num">{base}</td>'


def _write_html(
    rows: list[dict],
    out_path: Path,
    folder: str,
    has_applied: bool,
    suspected_counts: dict[str, int] | None = None,
    has_boomer: bool = False,
    has_arom: bool = False,
    has_comerger: bool = False,
) -> None:
    suspected_counts = suspected_counts or {}
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_metric[r["metric"]][r["graph"]] = r["value"]

    html_rows: list[str] = []
    for metric_name, meta in _REGISTRY.items():
        vals = by_metric.get(metric_name, {})
        u_val = vals.get("union_input")
        m_val = vals.get("merged_ontology")
        a_val = vals.get("applied_alignments") if has_applied else None
        b_val = vals.get("boomer_ontology") if has_boomer else None
        ar_val = vals.get("arom_ontology") if has_arom else None
        c_val = vals.get("comerger_ontology") if has_comerger else None
        if all(v is None for v in (u_val, m_val, a_val, b_val, ar_val, c_val)):
            continue
        border = _SOURCE_BORDER.get(meta["source"], "#ccc")
        badges = _cat_badges(meta["categories"])
        susp = suspected_counts.get(metric_name, 0)
        applied_cell = _fmt_applied(a_val, susp) if has_applied else ""
        arom_cell = _fmt(ar_val) if has_arom else ""
        comerger_cell = _fmt(c_val) if has_comerger else ""
        boomer_cell = _fmt(b_val) if has_boomer else ""

        html_rows.append(
            f'    <tr style="border-left: 3px solid {border}">\n'
            f"      <td><strong>{metric_name}</strong></td>\n"
            f"      {_fmt(u_val)}\n"
            f"      {applied_cell}\n"
            f"      {arom_cell}\n"
            f"      {comerger_cell}\n"
            f"      {boomer_cell}\n"
            f"      {_fmt(m_val)}\n"
            f'      <td class="tgt">{meta["target"]}</td>\n'
            f'      <td class="src">{meta["source"]}</td>\n'
            f'      <td class="cats">{badges}</td>\n'
            f'      <td class="interp">{meta["interpretation"]}</td>\n'
            f"    </tr>"
        )

    applied_col_header  = f"<th>{_COLUMN_DISPLAY['applied_alignments']}</th>" if has_applied else ""
    arom_col_header     = f"<th>{_COLUMN_DISPLAY['arom_ontology']}</th>"      if has_arom else ""
    comerger_col_header = f"<th>{_COLUMN_DISPLAY['comerger_ontology']}</th>"  if has_comerger else ""
    boomer_col_header   = f"<th>{_COLUMN_DISPLAY['boomer_ontology']}</th>"    if has_boomer else ""

    cat_legend_lines = []
    for cat, (_, color) in _CATEGORIES.items():
        cat_legend_lines.append(
            f'    <span class="legend-item">'
            f'<span class="dot" style="background:{color}"></span> {cat}</span>'
        )
    legend = _LEGEND_TEMPLATE.format(cat_legend="\n".join(cat_legend_lines))

    html = _HTML_TEMPLATE.format(
        folder=folder,
        applied_col_header=applied_col_header,
        arom_col_header=arom_col_header,
        comerger_col_header=comerger_col_header,
        boomer_col_header=boomer_col_header,
        rows="\n".join(html_rows),
        legend=legend,
    )
    out_path.write_text(html, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute ontology quality metrics based on 7 academic quality dimensions."
    )
    parser.add_argument(
        "folder_name", help="Subfolder under tests/inputs/ and tests/vllm_outputs/"
    )
    args = parser.parse_args()

    folder = args.folder_name
    repo_root = Path(__file__).parent.parent
    input_dir = repo_root / "tests" / "inputs" / folder
    output_dir = repo_root / "tests" / "vllm_outputs" / folder
    out_csv = output_dir / "metrics_def.csv"

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

    merged_path = output_dir / "merged_ontology.owl"
    applied_path = output_dir / "applied_alignments.owl"
    boomer_path = output_dir / "boomer_ontology.owl"
    arom_path = output_dir / "arom_ontology.owl"
    comerger_path = output_dir / "comerger_ontology.owl"
    alignment_stats_path = output_dir / "alignment_stats.json"
    boomer_stats_path = output_dir / "boomer_stats.json"
    arom_stats_path = output_dir / "arom_stats.json"
    comerger_stats_path = output_dir / "comerger_stats.json"

    if not merged_path.exists():
        print(f"merged_ontology.owl not found in {output_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading ontologies for: {folder}")
    onto1 = _load_graph(str(input_files[0]))
    onto2 = _load_graph(str(input_files[1]))
    union = Graph()
    for t in onto1:
        union.add(t)
    for t in onto2:
        union.add(t)
    merged = _load_graph(str(merged_path))
    applied = _load_graph(str(applied_path)) if applied_path.exists() else None
    boomer = _load_graph(str(boomer_path)) if boomer_path.exists() else None
    arom = _load_graph(str(arom_path)) if arom_path.exists() else None
    comerger = _load_graph(str(comerger_path)) if comerger_path.exists() else None
    arom_provenance: dict[str, dict[str, str]] | None = None
    if arom is not None and arom_stats_path.exists():
        arom_provenance = json.loads(arom_stats_path.read_text(encoding="utf-8")).get(
            "code_provenance"
        )

    print(f"  onto1:              {len(onto1)} triples")
    print(f"  onto2:              {len(onto2)} triples")
    print(f"  union_input:        {len(union)} triples")
    print(f"  merged_ontology:    {len(merged)} triples")
    if applied is not None:
        print(f"  applied_alignments: {len(applied)} triples")
    else:
        print("  applied_alignments: not found — skipped")
    if boomer is not None:
        print(f"  boomer_ontology:    {len(boomer)} triples")
    else:
        print("  boomer_ontology:    not found — skipped")
    if arom is not None:
        print(f"  arom_ontology:      {len(arom)} triples")
    else:
        print("  arom_ontology:      not found — skipped")
    if comerger is not None:
        print(f"  comerger_ontology:  {len(comerger)} triples")
    else:
        print("  comerger_ontology:  not found — skipped")

    # Entity sets for cross-ontology metrics (URI-based source attribution)
    onto1_entities: set[URIRef] = {s for s, _, _ in onto1 if isinstance(s, URIRef)}
    onto2_entities: set[URIRef] = {s for s, _, _ in onto2 if isinstance(s, URIRef)}

    # ── Self-implemented metrics ───────────────────────────────────────────────
    print("\nComputing self-implemented metrics …")
    graph_objects: dict[str, Graph] = {
        "union_input": union,
        "merged_ontology": merged,
    }
    if applied is not None:
        graph_objects["applied_alignments"] = applied
    if arom is not None:
        graph_objects["arom_ontology"] = arom
    if comerger is not None:
        graph_objects["comerger_ontology"] = comerger
    if boomer is not None:
        graph_objects["boomer_ontology"] = boomer

    self_metrics: dict[str, dict[str, float | None]] = {}
    for name, g in graph_objects.items():
        union_arg = None if name == "union_input" else union
        prov = arom_provenance if name == "arom_ontology" else None
        self_metrics[name] = _compute_self_metrics(
            g, onto1_entities, onto2_entities, union_arg, arom_provenance=prov
        )
        print(f"  {name}: done")

    # ── HermiT reasoner (disabled — too slow on large ontologies) ────────────
    for name in graph_objects:
        self_metrics[name]["unsatisfiable_classes"] = None

    # ── Alignment application stats (from sidecar JSON written by merger) ─────
    suspected_counts: dict[str, int] = {}
    if alignment_stats_path.exists():
        stats = json.loads(alignment_stats_path.read_text(encoding="utf-8"))
        total_align = float(stats.get("total_alignments", 0))
        applied_align = float(stats.get("applied_count", 0))
        rejected_count = int(total_align - applied_align)
        rejected = stats.get("rejected_alignments", [])
        # union_input: no alignments by definition
        if "union_input" in self_metrics:
            self_metrics["union_input"]["applied_alignments"] = 0.0
        # applied_alignments.owl was built by applying ALL alignments unconditionally
        if "applied_alignments" in self_metrics:
            self_metrics["applied_alignments"]["applied_alignments"] = total_align
        # merged_ontology: only alignments LLM accepted after context verification
        if "merged_ontology" in self_metrics:
            self_metrics["merged_ontology"]["applied_alignments"] = applied_align
        # arom_ontology: AROM has no rejection — applies all alignments ≥ threshold.
        # With default threshold=0.0 that equals total_align.
        if "arom_ontology" in self_metrics:
            self_metrics["arom_ontology"]["applied_alignments"] = total_align
        # comerger_ontology: read authoritative count from comerger_stats.json
        # (written by CoMergerRunner via HModel.getEqClasses() etc.).  Counting
        # owl:equivalentClass in the output OWL is UNRELIABLE on large
        # ontologies — CoMerger doesn't always materialize every collapsed
        # equiv group as a triple in the final file (silent under-count).
        if "comerger_ontology" in self_metrics and comerger is not None:
            if comerger_stats_path.exists():
                cstats = json.loads(comerger_stats_path.read_text(encoding="utf-8"))
                self_metrics["comerger_ontology"]["applied_alignments"] = float(
                    cstats.get("applied_equiv_total", 0)
                )
                print(
                    f"  comerger_stats: applied_equiv_total = "
                    f"{cstats.get('applied_equiv_total', 0)} "
                    f"(classes={cstats.get('applied_equiv_classes', 0)}, "
                    f"obj_pro={cstats.get('applied_equiv_object_properties', 0)}, "
                    f"data_pro={cstats.get('applied_equiv_data_properties', 0)})"
                )
            else:
                # Fallback: count owl:equivalentClass triples (unreliable for big ontos)
                equiv_count = sum(1 for _ in comerger.triples((None, OWL.equivalentClass, None)))
                self_metrics["comerger_ontology"]["applied_alignments"] = float(equiv_count)
                print(
                    "  comerger_stats.json missing — falling back to "
                    f"owl:equivalentClass count ({equiv_count}); rebuild CoMerger Runner "
                    "to get authoritative number"
                )
        print(
            f"  alignment_stats: {int(applied_align)}/{int(total_align)} accepted by LLM"
        )

        # Suspected counts for the applied_alignments column: every rejected
        # alignment's entity1 (entity2 was collapsed into it) is a "tainted" URI.
        if applied is not None and rejected:
            tainted_uris = {URIRef(a["entity1"]) for a in rejected}
            suspected_counts = _compute_suspected_counts(
                applied, onto1_entities, onto2_entities, tainted_uris
            )
            # applied_alignments metric itself: # of rejected alignments
            suspected_counts["applied_alignments"] = rejected_count
            print(
                f"  suspected (applied_alignments column): {suspected_counts}"
            )
    else:
        print("  alignment_stats.json not found — skipping applied_alignments metric")

    # ── Boomer accepted count (from sidecar JSON written by apply_boomer.py) ──
    if boomer_stats_path.exists() and "boomer_ontology" in self_metrics:
        bstats = json.loads(boomer_stats_path.read_text(encoding="utf-8"))
        self_metrics["boomer_ontology"]["applied_alignments"] = float(
            bstats.get("accepted_equiv_count", 0)
        )
        print(
            f"  boomer_stats: {int(bstats.get('accepted_equiv_count', 0))} "
            f"equivalence axioms accepted by Boomer"
        )

    # ── Assemble rows ──────────────────────────────────────────────────────────
    # Order encodes "pipeline progression":
    #   union_input → applied_alignments (naive) → arom_ontology / comerger_ontology
    #   (algorithmic) → boomer_ontology (probabilistic) → merged_ontology (LLM, final).
    graph_names = ["union_input"]
    if applied is not None:
        graph_names.append("applied_alignments")
    if arom is not None:
        graph_names.append("arom_ontology")
    if comerger is not None:
        graph_names.append("comerger_ontology")
    if boomer is not None:
        graph_names.append("boomer_ontology")
    graph_names.append("merged_ontology")

    rows: list[dict] = []
    for graph_name in graph_names:
        for metric_name, meta in _REGISTRY.items():
            value = self_metrics[graph_name].get(metric_name)
            if value is None:
                continue
            rows.append(
                {
                    "graph": graph_name,
                    "metric": metric_name,
                    "value": value,
                    "source": meta["source"],
                    "categories": ", ".join(meta["categories"]),
                    "target": meta["target"],
                    "interpretation": meta["interpretation"],
                }
            )

    if not rows:
        print("No metrics collected.", file=sys.stderr)
        sys.exit(1)

    # ── Write CSV ──────────────────────────────────────────────────────────────
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "graph",
                "metric",
                "value",
                "target",
                "source",
                "categories",
                "interpretation",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nMetrics written to {out_csv}")

    # ── Write HTML ─────────────────────────────────────────────────────────────
    out_html = out_csv.with_suffix(".html")
    _write_html(
        rows, out_html, folder, applied is not None, suspected_counts,
        has_boomer=boomer is not None,
        has_arom=arom is not None,
        has_comerger=comerger is not None,
    )
    print(f"Report  written to {out_html}\n")

    # ── Console summary ────────────────────────────────────────────────────────
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_metric[r["metric"]][r["graph"]] = r["value"]

    has_app = applied is not None
    has_arom = arom is not None
    has_comerger = comerger is not None
    has_boom = boomer is not None
    col = max(len(m) for m in _REGISTRY)
    # Column widths chosen to fit the longest display name in each slot.
    hdr_parts = [f"{'metric':<{col}}", f"{_COLUMN_DISPLAY['union_input']:>15}"]
    if has_app:
        hdr_parts.append(f"{_COLUMN_DISPLAY['applied_alignments']:>18}")
    if has_arom:
        hdr_parts.append(f"{_COLUMN_DISPLAY['arom_ontology']:>10}")
    if has_comerger:
        hdr_parts.append(f"{_COLUMN_DISPLAY['comerger_ontology']:>12}")
    if has_boom:
        hdr_parts.append(f"{_COLUMN_DISPLAY['boomer_ontology']:>10}")
    hdr_parts.append(f"{_COLUMN_DISPLAY['merged_ontology']:>14}")
    hdr_parts.append("target")
    hdr = "  ".join(hdr_parts)
    print(hdr)
    print("─" * len(hdr))
    for metric_name, meta in _REGISTRY.items():
        vals = by_metric.get(metric_name, {})
        u = vals.get("union_input")
        m = vals.get("merged_ontology")
        if not vals:
            continue

        def _fs(v: float | None, w: int) -> str:
            if v is None:
                return f"{'—':>{w}}"
            if v == int(v) and abs(v) < 1e9:
                return f"{int(v):>{w}}"
            return f"{v:>{w}.4f}"

        u_s = _fs(u, 15)
        m_s = _fs(m, 14)
        tgt = meta["target"]
        parts = [f"{metric_name:<{col}}", u_s]
        if has_app:
            parts.append(_fs(vals.get("applied_alignments"), 18))
        if has_arom:
            parts.append(_fs(vals.get("arom_ontology"), 10))
        if has_comerger:
            parts.append(_fs(vals.get("comerger_ontology"), 12))
        if has_boom:
            parts.append(_fs(vals.get("boomer_ontology"), 10))
        parts.append(m_s)
        print(f"{'  '.join(parts)}  {tgt}")


if __name__ == "__main__":
    main()
