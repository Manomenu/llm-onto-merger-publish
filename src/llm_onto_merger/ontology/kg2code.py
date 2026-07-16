from pydantic import BaseModel
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import split_uri

from ..logger import get_logger
from .uri import namespace_of

log = get_logger(__name__)

ALIAS_PREDICATE_CODED = "zz::alias"
ALIAS_PREDICATE = "http://merged#alias"

# Well-known local names → canonical predicate URIRef. Used as a fallback when
# the LLM emits a hallucinated code prefix (e.g. 'ha::alias' instead of
# 'zz::alias', or 'am::type' instead of the actual rdf code). The local name
# is unambiguous for these predicates so we recover the triple instead of
# discarding it.
_PREDICATE_FALLBACKS: dict[str, URIRef] = {
    "alias": URIRef(ALIAS_PREDICATE),
    "type": RDF.type,
    "subClassOf": RDFS.subClassOf,
    "subPropertyOf": RDFS.subPropertyOf,
    "domain": RDFS.domain,
    "range": RDFS.range,
    "label": RDFS.label,
    "comment": RDFS.comment,
    "disjointWith": OWL.disjointWith,
    "equivalentClass": OWL.equivalentClass,
    "equivalentProperty": OWL.equivalentProperty,
    "sameAs": OWL.sameAs,
    "inverseOf": OWL.inverseOf,
}


def _try_predicate_fallback(p_coded: str) -> URIRef | None:
    """Recover a predicate URIRef by local name when its code prefix is unknown.

    Handles three formats the LLM sometimes emits instead of canonical 'code::Local':
      'code::label'   — wrong code (e.g. 'ha::alias')
      'rdfs:label'    — Turtle-style single colon (NOT what the prompt asks for)
      'label'         — bare local name
    """
    # Canonical or wrong-code: 'xx::Local'
    idx = p_coded.find("::")
    if idx > 0:
        return _PREDICATE_FALLBACKS.get(p_coded[idx + 2:])
    # Turtle-style: 'rdfs:label' (single colon, but not a full http: URI)
    idx = p_coded.find(":")
    if idx > 0 and not p_coded.startswith("http"):
        return _PREDICATE_FALLBACKS.get(p_coded[idx + 1:])
    # Bare local name
    return _PREDICATE_FALLBACKS.get(p_coded)

_KG2CODE_PREAMBLE_TEMPLATE = """
Each ontology entity is represented as:
  Entity(uri, tuples)
where:
  uri    — 'code::LocalName'  uniquely identifies the entity, e.g. 'aa::Person'
  tuples — outgoing triples: list of (subject_uri, predicate_uri, object_uri_or_literal)
           every URI element uses the same 'code::LocalName' encoding
           literal values (strings, numbers) are written as-is without a code prefix

Example:
  Entity('aa::Person', tuples=[
      ('aa::Person', '{rdfs}::subClassOf', 'ab::Animal'),
      ('aa::Person', '{rdf}::type', '{owl}::Class'),
  ])

When generating a Merged_Ontology you MUST use the same code prefixes for existing entities.
For entirely new concepts you may use 'zz::NewName'.
"""


def render_kg2code_preamble(ns_to_code: dict[str, str]) -> str:
    """Render the KG2Code preamble with this run's actual rdf/rdfs/owl codes.

    The example predicates must use the codec's real codes: a fictional code
    like 'af' may collide with a code actually assigned to a data namespace,
    and an LLM mimicking the example would then emit predicates that decode
    silently into the wrong namespace (e.g. http://cmt#subClassOf).
    """
    return _KG2CODE_PREAMBLE_TEMPLATE.format(
        rdf=ns_to_code.get(str(RDF), "rdf"),
        rdfs=ns_to_code.get(str(RDFS), "rdfs"),
        owl=ns_to_code.get(str(OWL), "owl"),
    )


class Entity(BaseModel):
    uri: str
    tuples: list[tuple[str, str, str]]


class DropReport(BaseModel):
    invalid_entities: list[str] = []
    bad_subject_entities: list[str] = []
    bad_predicate_triples: list[tuple[str, str]] = []
    # True iff the LLM response could not be parsed at all (invalid JSON,
    # schema validation failure, ...) and the merger fell back to a naive
    # apply_alignments-style merge for the env.  Doesn't include suspected_
    # /per-triple drops — those are mid-flight parsing issues handled by
    # _try_predicate_fallback / _decode_alias_literal etc.
    llm_failed: bool = False

    @property
    def total(self) -> int:
        return len(self.invalid_entities) + len(self.bad_subject_entities) + len(self.bad_predicate_triples)


def _encode(uri: str, ns_to_code: dict[str, str]) -> str:
    """Encode a full URI as 'code::LocalName'. Falls back to the bare URI on miss."""
    ns = namespace_of(uri)
    code = ns_to_code.get(ns)
    local = uri[len(ns):]
    return f"{code}::{local}" if code and local else uri


def _decode(coded: str, code_to_ns: dict[str, str]) -> URIRef | Literal:
    """Decode 'code::LocalName' → URIRef. Falls back to Literal for unknowns.

    Emits a warning when the value looks URI-shaped (contains '::') but the
    namespace code is unknown or the local name is empty.  No warning is
    emitted for values without '::' that fall back to Literal — those are
    legitimately literal object values (e.g. rdfs:comment text).
    """
    idx = coded.find("::")
    if idx > 0:
        code, local = coded[:idx], coded[idx + 2:]
        ns = code_to_ns.get(code)
        if ns and local:
            return URIRef(ns + local)
        if not ns:
            log.warning(
                "Decoder: unknown namespace code '%s' in '%s' — falling back to Literal",
                code, coded,
            )
        elif not local:
            log.warning(
                "Decoder: empty local name after '::' in '%s' — falling back to Literal",
                coded,
            )
    if coded.startswith("http"):
        return URIRef(coded)
    return Literal(coded)


def graph_to_string(graph: Graph, ns_to_code: dict[str, str]) -> str:
    """Render all entities in *graph* as KG2Code Entity(...) declarations.

    Every URI — subject, predicate, object — is encoded as 'code:LocalName'
    using ns_to_code so the full URI can be reconstructed from the response.
    Does NOT include KG2CODE_PREAMBLE.
    """
    subjects = sorted({s for s, _, _ in graph if isinstance(s, URIRef)}, key=str)
    lines = []
    for subj in subjects:
        subj_enc = _encode(str(subj), ns_to_code)
        tuple_strs = [
            f"('{subj_enc}', '{_encode(str(p), ns_to_code)}', "
            f"'{str(o) if isinstance(o, Literal) else _encode(str(o), ns_to_code)}')"
            for _, p, o in graph.triples((subj, None, None))
        ]
        lines.append(f"Entity('{subj_enc}', tuples=[{', '.join(tuple_strs)}])")
    return "\n".join(lines)


def _predicate_serializable(p: URIRef) -> bool:
    """True iff *p* can be written as an RDF/XML predicate (a splittable QName).

    RDF/XML emits every predicate as an element QName, so its local part must be
    a valid XML NCName.  LLM hallucinations occasionally yield a decodable but
    non-NCName local name (e.g. 'http://merged#alias?' from a stray 'zz::alias?')
    which decodes fine yet makes graph.serialize(format="xml") raise
    ValueError("Can't split ...").  We mirror the serializer's own check
    (rdflib.namespace.split_uri) so such triples are dropped up front instead of
    crashing the whole merge at save time.
    """
    try:
        split_uri(str(p))
        return True
    except ValueError:
        return False


def _is_valid_entity(e: Entity, code_to_ns: dict[str, str]) -> bool:
    uri = e.uri.strip()
    if not uri:
        return False
    idx = uri.find("::")
    if idx > 0:
        return uri[:idx] in code_to_ns and bool(uri[idx + 2:])
    return uri.startswith("http")


def _decode_alias_literal(s: str, code_to_ns: dict[str, str]) -> URIRef | None:
    """Decode an alias literal → URIRef with progressive fallbacks.

    Tries in order:
      1. Correct format:  'code;;LocalName'
      2. Wrong separator: 'code::LocalName'
      3. Regex scan:      find first 'code::LocalName' pattern in prose
    Logs a warning for every fallback used; returns None only if all fail.
    """
    import re

    def _try(code: str, local: str, source: str) -> URIRef | None:
        ns = code_to_ns.get(code)
        if ns and local:
            return URIRef(ns + local)
        return None

    # 1. canonical ;;
    idx = s.find(";;")
    if idx >= 0:
        result = _try(s[:idx], s[idx + 2:], s)
        if result:
            return result

    # 2. wrong separator ::
    idx = s.find("::")
    if idx >= 0:
        result = _try(s[:idx], s[idx + 2:], s)
        if result:
            log.warning(
                "Alias decoder: used '::' fallback (expected ';;') in '%s'", s
            )
            return result

    # 3. scan prose for any 'code::LocalName' token
    for m in re.finditer(r'\b([a-z]{2,})::([\w]+)', s):
        result = _try(m.group(1), m.group(2), s)
        if result:
            log.warning(
                "Alias decoder: extracted '%s::%s' from prose literal '%s'",
                m.group(1), m.group(2), s,
            )
            return result

    log.warning(
        "Alias decoder: could not decode alias literal '%s' — discarded", s
    )
    return None


def build_alias_map(graphs: list[Graph], code_to_ns: dict[str, str]) -> dict[str, str]:
    """Extract alias triples and return {old_uri: new_uri}.

    Accepts both literal objects ('code;;LocalName' — correct format) and
    URIRef objects (LLM used '::' instead of ';;' so the object was decoded
    as a live URI).  Both cases are treated as the old URI.
    """
    alias_pred = URIRef(ALIAS_PREDICATE)
    result: dict[str, str] = {}
    for graph in graphs:
        for s, p, o in graph.triples((None, alias_pred, None)):
            if not isinstance(s, URIRef):
                continue
            if isinstance(o, URIRef):
                result[str(o)] = str(s)
            elif isinstance(o, Literal):
                old_uri = _decode_alias_literal(str(o), code_to_ns)
                if old_uri:
                    result[str(old_uri)] = str(s)
    return result


def entities_to_graph(entities: list[Entity], code_to_ns: dict[str, str]) -> tuple[Graph, DropReport]:
    """Reconstruct an rdflib Graph from LLM-returned Entity list.

    Every URI element is decoded via code_to_ns.  Unknown codes fall back to
    Literal; triples whose subject or predicate does not decode as URIRef are
    dropped with a warning.  Returns (graph, drop_report).
    """
    invalid = [e.uri for e in entities if not _is_valid_entity(e, code_to_ns)]
    if invalid:
        log.warning(
            "Dropped %d invalid/placeholder entities from LLM response",
            len(invalid),
        )
    valid = [e for e in entities if _is_valid_entity(e, code_to_ns)]
    graph = Graph()
    bad_subjects: list[str] = []
    bad_preds: list[tuple[str, str]] = []
    for entity in valid:
        subj = _decode(entity.uri, code_to_ns)
        if not isinstance(subj, URIRef):
            log.warning(
                "Triple group dropped: subject '%s' did not decode as URI",
                entity.uri,
            )
            bad_subjects.append(entity.uri)
            continue
        for _, p_coded, o_coded in entity.tuples:
            p = _decode(p_coded, code_to_ns)
            if not isinstance(p, URIRef):
                fallback = _try_predicate_fallback(p_coded)
                if fallback is not None:
                    log.warning(
                        "Predicate fallback: '%s' → '%s' (LLM used wrong code prefix)",
                        p_coded, str(fallback),
                    )
                    p = fallback
            o = _decode(o_coded, code_to_ns)
            if isinstance(p, URIRef) and _predicate_serializable(p):
                graph.add((subj, p, o))
            elif isinstance(p, URIRef):
                # Decoded to a URI but its local name is not a valid XML NCName
                # (e.g. 'http://merged#alias?') — unusable as an RDF/XML
                # predicate, so drop it rather than crash serialization later.
                log.warning(
                    "Triple dropped: predicate '%s' → '%s' is not RDF/XML-serializable "
                    "(invalid NCName local name; subject was '%s')",
                    p_coded, str(p), entity.uri,
                )
                bad_preds.append((entity.uri, p_coded))
            else:
                log.warning(
                    "Triple dropped: predicate '%s' did not decode as URI (subject was '%s')",
                    p_coded, entity.uri,
                )
                bad_preds.append((entity.uri, p_coded))
    if bad_subjects or bad_preds:
        log.warning(
            "entities_to_graph summary: dropped %d entities (bad subject) and %d triples (bad predicate)",
            len(bad_subjects), len(bad_preds),
        )
    return graph, DropReport(
        invalid_entities=invalid,
        bad_subject_entities=bad_subjects,
        bad_predicate_triples=bad_preds,
    )
