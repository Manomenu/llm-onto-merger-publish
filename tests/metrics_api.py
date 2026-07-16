#!/usr/bin/env python3
"""
Compute ontology metrics via the public OntoMetrics API (schema metrics)
and self-implemented formulas (KB metrics).

API:  https://ontometrics.informatik.uni-rostock.de/ontologymetrics/
      (University of Rostock, public, no auth required)
      Note: by calling this API you agree that the ontology may be stored
      on the server for research purposes.

Usage:
    python tests/metrics_api.py <folder_name>

Reads:
    tests/inputs/<folder_name>/*.owl   — two input ontologies
    tests/outputs/<folder_name>/merged_ontology.owl

Writes:
    tests/outputs/<folder_name>/metrics_api.csv
    Columns: graf, metryka, wartosc, zrodlo, interpretacja

Metrics (13 total):
    Schema:   average_depth, max_depth, average_breadth, max_breadth, ARC, ALC
    KB:       integrity, accuracy, cohesion, completeness, understandability, conciseness
    Reasoner: unsatisfiable_classes  (requires owlready2 + Java/HermiT)
"""

import csv
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, Literal, URIRef

_OWL_DISJOINT_WITH = OWL.disjointWith


def _load_graph(path: str) -> Graph:
    """Load OWL file and strip owl:disjointWith triples (same preprocessing as main pipeline)."""
    g = Graph()
    g.parse(path)
    disjoint = list(g.triples((None, _OWL_DISJOINT_WITH, None)))
    for triple in disjoint:
        g.remove(triple)
    if disjoint:
        print(f"  stripped {len(disjoint)} disjointWith triples from {path}")
    return g


ONTOMETRICS_URL = (
    "https://ontometrics.informatik.uni-rostock.de/ontologymetrics/ServletController"
)

# Seconds to wait between consecutive API calls (polite use of public service)
_DELAY_S = 3

# ── Metric registry ────────────────────────────────────────────────────────────

# api_key: one or more substrings to match against parsed API response keys (tried in order).
# None = self-implemented only.
_REGISTRY: dict[str, dict] = {
    "average_depth": {
        "api_key": ["average_depth"],
        "source": "ontometrics_api",
        "interpretation": (
            "Srednia glebokosc hierarchii klas (srednia liczba krawedzi od korzenia "
            "do kazdej klasy). Wyzszy wynik = bogatsza, bardziej szczegolowa hierarchia; "
            "zbyt wysoki moze utrudniac nawigacje. "
            "Wymiar: Jakość integracji hierarchii — wzrost wartości po scaleniu wskazuje, "
            "że nowe relacje is-a między encjami z obu ontologii pogłębiły taksonomię."
        ),
    },
    "max_depth": {
        "api_key": ["maximal_depth", "max_depth", "maximum_depth"],
        "source": "ontometrics_api",
        "interpretation": (
            "Maksymalna głębokość drzewa klas (najdłuższa ścieżka od korzenia do liścia). "
            "Większa wartość = obecność wysoce wyspecjalizowanych pojęć. "
            "Wymiar: Jakość integracji hierarchii — wzrost max_depth sugeruje, że encje "
            "jednej ontologii zostały osadzone głębiej w hierarchii drugiej dzięki nowym "
            "relacjom cross-ontology is-a."
        ),
    },
    "average_breadth": {
        "api_key": ["average_breadth"],
        "source": "ontometrics_api",
        "interpretation": (
            "Średnia liczba bezpośrednich podklas przypadająca na węzeł posiadający dzieci. "
            "Wyższy wynik = szerzej rozgałęzione ontologie. "
            "Wymiar: Jakość integracji hierarchii — wzrost po scaleniu sugeruje, że klasy "
            "z jednej ontologii zyskały nowe podklasy z drugiej; optymalna wartość zależy "
            "od domeny."
        ),
    },
    "max_breadth": {
        "api_key": ["maximal_breadth", "max_breadth", "maximum_breadth"],
        "source": "ontometrics_api",
        "interpretation": (
            "Maksymalna liczba bezpośrednich podklas jednej klasy. "
            "Wysoka wartość może wskazywać brak pośrednich poziomów hierarchii. "
            "Wymiar: Jakość integracji hierarchii — wzrost po scaleniu może oznaczać, "
            "że jeden węzeł stał się wspólnym przodkiem dla klas z obu ontologii; "
            "bardzo wysoka wartość sugeruje potrzebę wprowadzenia pośrednich kategorii."
        ),
    },
    "ARC": {
        "api_key": None,
        "source": "self-implemented",
        "interpretation": (
            "Liczba klas bez nazwanego rodzica (korzenie hierarchii). "
            "Wartość 1 oznacza spójną, jednolitą hierarchię z jednym punktem wejścia. "
            "Wymiar: Spójność strukturalna — niska wartość (idealna = 1) oznacza brak "
            "osieroconych klas na szczycie hierarchii; Jakość integracji hierarchii — "
            "ARC powinno maleć po udanym scaleniu, gdyż klasy-korzenie z obu ontologii "
            "powinny zostać powiązane relacjami is-a lub zgrupowane pod wspólnym przodkiem."
        ),
    },
    "unsatisfiable_classes": {
        "api_key": None,
        "source": "hermit_reasoner",
        "interpretation": (
            "Liczba klas wykrytych jako niespełnialne (unsatisfiable) przez reasoner HermiT "
            "— tzn. klas inferencyjnie równoważnych owl:Nothing, które nie mogą mieć "
            "żadnych instancji bez wywołania sprzeczności logicznej. "
            "Idealna wartość = 0. "
            "Wymiar: Spójność strukturalna — zgodnie z def. Jiménez-Ruiz & Cuenca Grau (2011) "
            "oraz Poveda-Villalón et al. (2012): ontologia jest strukturalnie spójna wtedy "
            "i tylko wtedy, gdy żadna klasa nie jest inferencyjnie unsatisfiable. "
            "Jest to najsilniejsza z dostępnych metryk strukturalnych — bezpośredni dowód "
            "na brak aksjomatycznych sprzeczności w ontologii."
        ),
    },
    "ALC": {
        "api_key": ["/alc", "absolute_leaf_cardinality"],
        "source": "ontometrics_api",
        "interpretation": (
            "Liczba klas bez żadnej podklasy (liście). "
            "Wyższy = więcej wyspecjalizowanych, atomowych pojęć w ontologii. "
            "Wymiar: Kompletność wiedzy — wysoka wartość wskazuje zachowanie "
            "wyspecjalizowanych pojęć z obu ontologii wejściowych; "
            "Jakość integracji hierarchii — po dodaniu relacji cross-ontology is-a "
            "część klas-liści staje się węzłami pośrednimi, co obniża ALC, ale poprawia "
            "integrację hierarchii."
        ),
    },
    "integrity": {
        "api_key": None,
        "source": "self-implemented",
        "interpretation": (
            "Ułamek trójek ze zbioru wejściowego (po lokalnych nazwach S/P/O) "
            "zachowanych w merged (dla unii = 1.0). "
            "Bliżej 1.0 = mniej informacji stracono podczas scalania. "
            "Wymiar: Kompletność wiedzy — bezpośrednio mierzy, jaka frakcja faktów "
            "z ontologii wejściowych przetrwała scalanie; niska wartość oznacza duże "
            "straty informacji i wymaga uzasadnienia (np. celowe usunięcie redundancji)."
        ),
    },
    "accuracy": {
        "api_key": None,
        "source": "self-implemented",
        "interpretation": (
            "Średni ułamek nazw lokalnych klas i właściwości ze zbioru wejściowego "
            "obecnych w merged (dla unii = 1.0). "
            "Bliżej 1.0 = lepsze pokrycie oryginalnego słownika pojęć. "
            "Wymiar: Kompletność wiedzy — mierzy zachowanie słownika pojęć obu ontologii; "
            "Zwięzłość — scalone encje mogą otrzymać nowe nazwy (np. 'MedicalPerson' "
            "zamiast 'Person'), co obniża accuracy przy zachowaniu semantyki."
        ),
    },
    "cohesion": {
        "api_key": None,
        "source": "self-implemented",
        "interpretation": (
            "Ułamek właściwości posiadających zdefiniowaną jednocześnie domenę i zakres. "
            "Wyższy = lepiej opisane relacje między klasami. "
            "Wymiar: Spójność domenowa — właściwości z zdefiniowaną domeną i zakresem "
            "precyzyjnie ograniczają, między jakimi klasami mogą zachodzić relacje, "
            "co redukuje ryzyko niespójności domenowych (np. 'hasAge' jednocześnie "
            "dla Person i Car) i czyni ontologię bardziej wiarygodną dla ekspertów."
        ),
    },
    "completeness": {
        "api_key": None,
        "source": "self-implemented",
        "interpretation": (
            "Ułamek par subClassOf (po lokalnych nazwach klasy nadrzędnej i podrzędnej) "
            "ze zbioru wejściowego zachowanych w merged (dla unii = 1.0). "
            "Bliżej 1.0 = lepsza zachowalność struktury hierarchicznej. "
            "Wymiar: Kompletność wiedzy — mierzy zachowanie relacji is-a z ontologii "
            "wejściowych, które stanowią rdzeń wiedzy hierarchicznej."
        ),
    },
    "understandability": {
        "api_key": None,
        "source": "self-implemented",
        "interpretation": (
            "Ułamek klas i właściwości posiadających rdfs:label lub rdfs:comment. "
            "Wyższy = ontologia łatwiejsza do zrozumienia przez człowieka. "
            "Wymiar: Spójność domenowa — opatrzone etykietami encje umożliwiają "
            "ekspertom domenowym weryfikację poprawności pojęć i ich relacji, "
            "co ułatwia wykrycie błędów semantycznych (np. nieprawidłowych is-a) "
            "oraz ocenę zgodności ontologii z wiedzą dziedzinową."
        ),
    },
    "conciseness": {
        "api_key": None,
        "source": "self-implemented",
        "interpretation": (
            "Stosunek unikalnych nazw lokalnych klas do całkowitej liczby URI klas. "
            "Wartość 1.0 = brak redundancji nazw; poniżej 1.0 = kolizje nazw "
            "między różnymi przestrzeniami nazw. "
            "Wymiar: Zwięzłość — bezpośrednio mierzy unikalność nazw klas; wartość "
            "poniżej 1.0 wskazuje, że te same pojęcia mogą być reprezentowane przez "
            "wiele URI (np. onto1:Person i onto2:Person jako oddzielne klasy), "
            "co narusza zasadę braku duplikatów i powinno być naprawione przez scalenie."
        ),
    },
}

# ── OntoMetrics API ────────────────────────────────────────────────────────────


def _query_api(owl_bytes: bytes, label: str) -> dict[str, float]:
    """POST an OWL file (as bytes) to OntoMetrics and return parsed metrics."""
    print(f"  → OntoMetrics API [{label}] …", end=" ", flush=True)
    resp = requests.post(
        ONTOMETRICS_URL,
        data={
            "text": owl_bytes.decode("utf-8", errors="replace"),
            "base": "on",
            "schema": "on",
            "knowledge": "on",
            "graph": "on",
            "store_aggreement": "on",
        },
        timeout=120,
    )
    resp.raise_for_status()
    metrics = _parse_html(resp.text)
    print(f"{len(metrics)} metrics")
    return metrics


# Ordered list of section markers as they appear in the response HTML.
_SECTIONS = [
    ("base", "Base metrics"),
    ("base", "Class axioms"),
    ("base", "Object property axioms"),
    ("base", "Data property axioms"),
    ("base", "Individual axioms"),
    ("base", "Annotation axioms"),
    ("schema", "Schema metrics"),
    ("kb", "Knowledgebase metrics"),
    ("graph", "Graph metrics"),
]

_SKIP_ANYWHERE = frozenset(["show", "hide", "more", "details", "powered", "copyright"])
_SKIP_FIRST = frozenset(
    [
        "home",
        "result",
        "faq",
        "wiki",
        "contact",
        "impressum",
        "results",
        "ontologyid",
        "optional",
        "created",
    ]
)


def _parse_html(html: str) -> dict[str, float]:
    """Extract numeric metric values from the OntoMetrics result page."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)

    idx = text.find("Results")
    if idx >= 0:
        text = text[idx:]

    section_spans: list[tuple[int, str]] = []
    for prefix, marker in _SECTIONS:
        pos = text.find(marker)
        if pos >= 0:
            section_spans.append((pos, prefix))
    section_spans.sort()

    def _section_at(pos: int) -> str:
        label = "base"
        for sp, sl in section_spans:
            if sp <= pos:
                label = sl
        return label

    metrics: dict[str, float] = {}
    pattern = re.compile(r"([A-Z][A-Za-z /()\-]+?):\s*(-?\d+\.?\d*(?:e[+-]?\d+)?)")
    for m in pattern.finditer(text):
        raw_name = m.group(1).strip()
        if len(raw_name) > 55:
            continue
        lower = raw_name.lower()
        if any(w in lower for w in _SKIP_ANYWHERE):
            continue
        if lower.split()[0] in _SKIP_FIRST:
            continue
        try:
            value = float(m.group(2))
        except ValueError:
            continue

        section = _section_at(m.start())
        key = (
            raw_name.lower()
            .replace(" ", "_")
            .replace("/", "_per_")
            .replace("(", "")
            .replace(")", "")
            .replace("-", "_")
        )
        full_key = f"{section}/{key}"
        if full_key not in metrics:
            metrics[full_key] = value

    return metrics


# ── rdflib helpers ─────────────────────────────────────────────────────────────

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
_DOMAIN = RDFS.domain
_RANGE = RDFS.range

_PROP_TYPES = (_OWL_OBJ, _OWL_DATA, _OWL_ANN, _OWL_FP, _OWL_IFP)


def _local(uri: URIRef) -> str:
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


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


def _kb_self(
    g: Graph,
    union: Graph | None = None,
    union_classes: set[URIRef] | None = None,
    union_props: set[URIRef] | None = None,
) -> dict[str, float]:
    """KB metrics computed locally (always self-implemented)."""
    cls = _classes(g)
    prop = _properties(g)
    n_c = len(cls)
    n_p = len(prop)

    # Integrity: fraction of union triples (by local-name tuples S/P/O) present in g
    if union is not None:

        def _triple_key(s, p, o) -> tuple[str, str, str]:
            return (
                _local(s),
                _local(p),
                _local(o) if isinstance(o, URIRef) else str(o),
            )

        union_triples = {
            _triple_key(s, p, o) for s, p, o in union if isinstance(s, URIRef)
        }
        g_triples = {_triple_key(s, p, o) for s, p, o in g if isinstance(s, URIRef)}
        integrity = (
            len(g_triples & union_triples) / len(union_triples)
            if union_triples
            else 1.0
        )
    else:
        integrity = 1.0  # union itself

    # Accuracy: mean of class-name coverage and property-name coverage vs union
    if union_classes is not None and union_props is not None:
        u_cls_names = {_local(c) for c in union_classes}
        u_prop_names = {_local(p) for p in union_props}
        m_cls_names = {_local(c) for c in cls}
        m_prop_names = {_local(p) for p in prop}
        acc_c = (
            len(m_cls_names & u_cls_names) / len(u_cls_names) if u_cls_names else 1.0
        )
        acc_p = (
            len(m_prop_names & u_prop_names) / len(u_prop_names)
            if u_prop_names
            else 1.0
        )
        accuracy = (acc_c + acc_p) / 2
    else:
        accuracy = 1.0  # union itself

    # Cohesion: fraction of properties with both domain AND range defined
    with_domain = {p for p in prop if any(True for _ in g.objects(p, _DOMAIN))}
    with_range = {p for p in prop if any(True for _ in g.objects(p, _RANGE))}
    cohesion = len(with_domain & with_range) / n_p if n_p else 0.0

    # Completeness: fraction of subClassOf pairs (local names) from union in g
    if union is not None:

        def _sub_pairs(src: Graph) -> set[tuple[str, str]]:
            return {
                (_local(s), _local(o))
                for s, _, o in src.triples((None, _SUB, None))
                if isinstance(s, URIRef) and isinstance(o, URIRef) and o != _OWL_THING
            }

        union_pairs = _sub_pairs(union)
        g_pairs = _sub_pairs(g)
        completeness = (
            len(g_pairs & union_pairs) / len(union_pairs) if union_pairs else 1.0
        )
    else:
        completeness = 1.0  # union itself

    # Understandability: fraction of classes+properties with rdfs:label or rdfs:comment
    entities = cls | prop
    n_e = len(entities)
    annotated = sum(
        1
        for e in entities
        if any(True for _ in g.objects(e, _LABEL))
        or any(True for _ in g.objects(e, _COMMENT))
    )
    understandability = annotated / n_e if n_e else 0.0

    # Conciseness: unique local class names / total number of class URIs
    unique_local = len({_local(c) for c in cls})
    conciseness = unique_local / n_c if n_c else 1.0

    # ARC: Absolute Root Cardinality — classes with no named parent
    has_named_parent = {
        s
        for s, _, o in g.triples((None, _SUB, None))
        if isinstance(s, URIRef)
        and isinstance(o, URIRef)
        and o != _OWL_THING
        and s in cls
    }
    arc = len(cls - has_named_parent)

    return {
        "integrity": round(integrity, 4),
        "accuracy": round(accuracy, 4),
        "cohesion": round(cohesion, 4),
        "completeness": round(completeness, 4),
        "understandability": round(understandability, 4),
        "conciseness": round(conciseness, 4),
        "ARC": float(arc),
    }


# ── HermiT reasoner check ─────────────────────────────────────────────────────

# XSD datatypes absent from the OWL 2 datatype map — HermiT rejects them.
_XSD_UNSUPPORTED = frozenset([
    XSD.date, XSD.time, XSD.duration,
    XSD.gYear, XSD.gYearMonth, XSD.gMonth, XSD.gMonthDay, XSD.gDay,
])


def _strip_hermit_unsupported(g: Graph) -> Graph:
    """Return a copy of g with HermiT-incompatible XSD datatype restrictions removed."""
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


def _reasoner_check(g: Graph, label: str) -> dict[str, float | None]:
    """Run HermiT via owlready2 and return the number of unsatisfiable classes.

    Returns {"unsatisfiable_classes": None} if owlready2 or Java is unavailable,
    which causes the metric to appear as N/A in the output.
    """
    try:
        import owlready2
    except ImportError:
        print(f"  [HermiT/{label}] owlready2 not installed — skipping (pip install owlready2)")
        return {"unsatisfiable_classes": None}

    import os
    import tempfile

    g_safe = _strip_hermit_unsupported(g)
    stripped = len(g) - len(g_safe)
    if stripped:
        print(f"  [HermiT/{label}] stripped {stripped} triples with unsupported XSD datatypes")

    with tempfile.NamedTemporaryFile(suffix=".owl", delete=False) as f:
        g_safe.serialize(destination=f.name, format="xml")
        tmp_path = f.name

    try:
        print(f"  → HermiT [{label}] …", end=" ", flush=True)
        world = owlready2.World()
        onto = world.get_ontology(f"file://{tmp_path}").load()
        with onto:
            owlready2.sync_reasoner_hermit(world, infer_property_values=False)
        unsat = list(world.inconsistent_classes())
        count = len(unsat)
        print(f"{count} unsatisfiable classes")
        return {"unsatisfiable_classes": float(count)}
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return {"unsatisfiable_classes": None}
    finally:
        os.unlink(tmp_path)


# ── HTML report ───────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ontology metrics — {folder}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1   {{ font-size: 1.4rem; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th, td {{ padding: 0.55rem 0.8rem; text-align: left; vertical-align: top; border: 1px solid #d0d0d0; }}
  th {{ background: #2c3e50; color: #fff; white-space: nowrap; }}
  tr:nth-child(even) {{ background: #f7f7f7; }}
  tr:hover {{ background: #eaf3fb; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.na  {{ text-align: center; color: #aaa; }}
  td.src {{ font-size: 0.78rem; color: #555; white-space: nowrap; }}
  td.interp {{ font-size: 0.82rem; color: #444; max-width: 340px; }}
  .schema-row td {{ border-left: 3px solid #2980b9; }}
  .kb-row    td {{ border-left: 3px solid #27ae60; }}
  .legend {{ margin-top: 1rem; font-size: 0.8rem; display: flex; gap: 1.5rem; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.4rem; }}
  .dot {{ width: 12px; height: 12px; border-radius: 2px; display: inline-block; }}
</style>
</head>
<body>
<h1>Ontology metrics &mdash; <code>{folder}</code></h1>
<table>
  <thead>
    <tr>
      <th>Metric</th>
      <th>union_input_onto</th>
      {applied_col_header}
      <th>merged_onto</th>
      <th>Source</th>
      <th>Interpretation</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
<div class="legend">
  <span><span class="dot" style="background:#2980b9"></span> Schema metric</span>
  <span><span class="dot" style="background:#27ae60"></span> KB metric</span>
</div>
</body>
</html>
"""

_SCHEMA_METRICS = {
    "average_depth",
    "max_depth",
    "average_breadth",
    "max_breadth",
    "ARC",
    "ALC",
}


def _fmt(v: float | None) -> str:
    if v is None:
        return '<td class="na">N/A</td>'
    return f'<td class="num">{v:.4f}</td>'


def _write_html(
    rows: list[dict],
    out_path: Path,
    folder: str,
    has_applied: bool,
) -> None:
    # Pivot: metric → {graph → value}, metric → source, metric → interpretation
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    by_source: dict[str, str] = {}
    by_interp: dict[str, str] = {}
    for r in rows:
        by_metric[r["metric"]][r["graph"]] = r["value"]
        by_source.setdefault(r["metric"], r["source"])
        by_interp.setdefault(r["metric"], r["interpretation"])

    html_rows: list[str] = []
    for metric_name in _REGISTRY:
        vals = by_metric.get(metric_name, {})
        src = by_source.get(metric_name, "")
        interp = by_interp.get(metric_name, "")
        row_cls = "schema-row" if metric_name in _SCHEMA_METRICS else "kb-row"

        u = vals.get("union_input")
        m = vals.get("merged_ontology")
        a = vals.get("applied_alignments") if has_applied else None

        applied_cell = _fmt(a) if has_applied else ""

        html_rows.append(
            f'    <tr class="{row_cls}">\n'
            f"      <td><strong>{metric_name}</strong></td>\n"
            f"      {_fmt(u)}\n"
            f"      {applied_cell}\n"
            f"      {_fmt(m)}\n"
            f'      <td class="src">{src}</td>\n'
            f'      <td class="interp">{interp}</td>\n'
            f"    </tr>"
        )

    applied_col_header = "<th>applied_alignments_onto</th>" if has_applied else ""

    html = _HTML_TEMPLATE.format(
        folder=folder,
        applied_col_header=applied_col_header,
        rows="\n".join(html_rows),
    )
    out_path.write_text(html, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <folder_name>", file=sys.stderr)
        sys.exit(1)

    folder = sys.argv[1]
    repo_root = Path(__file__).parent.parent
    input_dir = repo_root / "tests" / "inputs" / folder
    output_dir = repo_root / "tests" / "outputs" / folder
    out_csv = output_dir / "metrics_api.csv"

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
    print(f"  onto1:              {len(onto1)} triples")
    print(f"  onto2:              {len(onto2)} triples")
    print(f"  union_input:        {len(union)} triples")
    print(f"  merged_ontology:    {len(merged)} triples")
    if applied is not None:
        print(f"  applied_alignments: {len(applied)} triples")
    else:
        print("  applied_alignments: not found — skipped")

    u_cls = _classes(union)
    u_prop = _properties(union)

    # ── API calls ──────────────────────────────────────────────────────────────
    print("\nQuerying OntoMetrics API …")
    api_graphs: list[tuple[str, bytes]] = [
        ("union_input", union.serialize(format="xml").encode("utf-8")),
        ("merged_ontology", merged_path.read_bytes()),
    ]
    if applied is not None:
        api_graphs.append(
            ("applied_alignments", applied.serialize(format="xml").encode("utf-8"))
        )

    api_results: dict[str, dict[str, float]] = {}
    for i, (graph_name, owl_bytes) in enumerate(api_graphs):
        if i > 0:
            time.sleep(_DELAY_S)
        try:
            api_results[graph_name] = _query_api(owl_bytes, graph_name)
        except Exception as exc:
            print(f"  ERROR for {graph_name}: {exc}", file=sys.stderr)
            api_results[graph_name] = {}

    # ── Self-implemented KB metrics ───────────────────────────────────────────
    self_kb: dict[str, dict[str, float | None]] = {
        "union_input":     _kb_self(union),
        "merged_ontology": _kb_self(merged, union, u_cls, u_prop),
    }
    if applied is not None:
        self_kb["applied_alignments"] = _kb_self(applied, union, u_cls, u_prop)

    # ── HermiT reasoner metrics ───────────────────────────────────────────────
    print("\nRunning HermiT reasoner …")
    graphs_to_check = [
        ("union_input",     union),
        ("merged_ontology", merged),
    ]
    if applied is not None:
        graphs_to_check.append(("applied_alignments", applied))
    for gname, g in graphs_to_check:
        self_kb[gname].update(_reasoner_check(g, gname))

    # ── Assemble rows ──────────────────────────────────────────────────────────
    graph_names = ["union_input", "merged_ontology"] + (
        ["applied_alignments"] if applied is not None else []
    )

    rows: list[dict] = []
    for graph_name in graph_names:
        api_raw = api_results.get(graph_name, {})
        for metric_name, meta in _REGISTRY.items():
            api_key = meta["api_key"]
            source = meta["source"]
            interp = meta["interpretation"]
            value: float | None = None

            if api_key is not None:
                value = next(
                    (v for k, v in api_raw.items() if any(alt in k for alt in api_key)),
                    None,
                )
            else:
                value = self_kb[graph_name].get(metric_name)

            if value is None:
                continue

            rows.append(
                {
                    "graph": graph_name,
                    "metric": metric_name,
                    "value": value,
                    "source": source,
                    "interpretation": interp,
                }
            )

    if not rows:
        print("No metrics collected — API may be unavailable.", file=sys.stderr)
        sys.exit(1)

    # ── Write CSV ──────────────────────────────────────────────────────────────
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["graph", "metric", "value", "source", "interpretation"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Metrics written to {out_csv}")

    # ── Write HTML ─────────────────────────────────────────────────────────────
    out_html = out_csv.with_suffix(".html")
    _write_html(rows, out_html, folder, applied is not None)
    print(f"Report  written to {out_html}\n")

    # ── Console summary ────────────────────────────────────────────────────────
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    by_source: dict[str, str] = {}
    for r in rows:
        by_metric[r["metric"]][r["graph"]] = r["value"]
        by_source.setdefault(r["metric"], r["source"])

    col = max(len(m) for m in _REGISTRY)
    has_app = applied is not None
    hdr = (
        f"{'metric':<{col}}  {'union_input':>15}  {'applied_alignments':>20}"
        f"  {'merged_ontology':>16}  source"
        if has_app
        else f"{'metric':<{col}}  {'union_input':>15}  {'merged_ontology':>16}  source"
    )
    print(hdr)
    print("─" * len(hdr))
    for metric_name in _REGISTRY:
        vals = by_metric.get(metric_name, {})
        u = vals.get("union_input")
        m = vals.get("merged_ontology")
        u_s = f"{u:>15.4f}" if u is not None else f"{'—':>15}"
        m_s = f"{m:>16.4f}" if m is not None else f"{'—':>16}"
        src = by_source.get(metric_name, "")
        if has_app:
            a = vals.get("applied_alignments")
            a_s = f"{a:>20.4f}" if a is not None else f"{'—':>20}"
            print(f"{metric_name:<{col}}{u_s}{a_s}{m_s}  {src}")
        else:
            print(f"{metric_name:<{col}}{u_s}{m_s}  {src}")


if __name__ == "__main__":
    main()
