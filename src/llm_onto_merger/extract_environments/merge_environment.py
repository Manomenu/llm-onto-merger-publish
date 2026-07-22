import itertools
import string
from collections import deque

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, URIRef

from ..alignment.alignment import Alignment
from ..ontology import graph_to_string, namespace_of, render_kg2code_preamble

_CODEC_CHARS = string.ascii_lowercase

_WELL_KNOWN_NS: tuple[str, ...] = (
    str(RDF),
    str(XSD),
    str(RDFS),
    str(OWL),
    "http://www.w3.org/2003/11/swrl#",
    "http://www.w3.org/2003/11/swrlb#",
    "http://www.owl-ontologies.com/2005/08/07/xsp.owl#",
    "http://protege.stanford.edu/plugins/owl/protege#",
)

# Reserved code for entities introduced by the LLM (not from either source ontology).
MERGED_NS = "http://merged#"
MERGED_CODE = "zz"


def _encode_border(uri: URIRef, ns_to_code: dict[str, str]) -> str:
    """Encode a border URIRef as 'code::LocalName' for the prompt."""
    s = str(uri)
    ns = namespace_of(s)
    code = ns_to_code.get(ns)
    local = s[len(ns):]
    return f"{code}::{local}" if code and local else s


def build_namespace_codec(
    onto_1: Graph,
    onto_2: Graph,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], frozenset[str]]:
    """Assign short alphabetic codes to each unique namespace prefix.

    Namespaces are collected from every URIRef position in both ontologies
    (subjects, predicates, objects).  Well-known namespaces are added only
    for the ones not already present in the data.  Code zz is permanently
    reserved for MERGED_NS (entities introduced by the LLM).

    Returns:
        uri_to_code    — full subject URI → namespace code  (for graph_to_string)
        code_to_ns     — code → namespace prefix  (for URI reconstruction)
        ns_to_code     — namespace prefix → code  (for is_well_known by code)
        well_known_codes — frozenset of codes assigned to well-known namespaces
    """
    data_namespaces = {
        ns
        for g in (onto_1, onto_2)
        for s, p, o in g
        for node in (s, p, o)
        if isinstance(node, URIRef)
        for ns in [namespace_of(str(node))]
        if ns
    }
    # Well-known NS added only if absent from data; zz is reserved, skip it.
    all_namespaces = sorted(data_namespaces | set(_WELL_KNOWN_NS))

    codes = (
        c
        for length in itertools.count(2)
        for c in ("".join(combo) for combo in itertools.product(_CODEC_CHARS, repeat=length))
        if c != MERGED_CODE
    )
    ns_to_code: dict[str, str] = {}
    code_to_ns: dict[str, str] = {}
    for ns, code in zip(all_namespaces, codes):
        ns_to_code[ns] = code
        code_to_ns[code] = ns

    # Reserve zz for merged namespace (LLM-created entities).
    ns_to_code[MERGED_NS] = MERGED_CODE
    code_to_ns[MERGED_CODE] = MERGED_NS

    uri_to_code: dict[str, str] = {
        str(s): ns_to_code[ns]
        for g in (onto_1, onto_2)
        for s, _, _ in g
        if isinstance(s, URIRef)
        for ns in [namespace_of(str(s))]
        if ns and ns in ns_to_code
    }
    well_known_codes = frozenset(
        ns_to_code[ns] for ns in _WELL_KNOWN_NS if ns in ns_to_code
    )
    return uri_to_code, code_to_ns, ns_to_code, well_known_codes


class MergeEnvironmentConfig:
    def __init__(self, max_chars: int = 10_000) -> None:
        self.max_chars = max_chars


class MergeEnvironment:
    def __init__(
        self,
        onto_1: Graph,
        onto_2: Graph,
        alignments: list[Alignment],
        border1: deque[URIRef] | None = None,
        border2: deque[URIRef] | None = None,
        border1_graph: Graph | None = None,
        border2_graph: Graph | None = None,
        ns_to_code: dict[str, str] | None = None,
        code_to_ns: dict[str, str] | None = None,
        max_chars: int = 10_000,
    ) -> None:
        self.onto_1 = onto_1
        self.onto_2 = onto_2
        self.alignments = alignments
        self.border1: deque[URIRef] = border1 if border1 is not None else deque()
        self.border2: deque[URIRef] = border2 if border2 is not None else deque()
        self.border1_graph: Graph = border1_graph if border1_graph is not None else Graph()
        self.border2_graph: Graph = border2_graph if border2_graph is not None else Graph()
        self._ns_to_code: dict[str, str] = ns_to_code or {}
        self._code_to_ns: dict[str, str] = code_to_ns or {}
        self._max_chars = max_chars
        # Track which nodes have been queued into border1/border2 to prevent duplicate
        # deque entries when new neighbours are discovered during expand_extracted.
        self._border1_queued: set[URIRef] = set(self.border1)
        self._border2_queued: set[URIRef] = set(self.border2)
        # Nodes explicitly placed in interior: seeds (phase 1) + nodes expanded via _expand_one
        # (phase 2).  Distinct from onto_1/onto_2 subjects because move_entity_triples also
        # pulls in triples where the seed is the *object*, making border nodes appear as
        # subjects in the interior graph without having been deliberately expanded.
        self.expanded_nodes_1: set[URIRef] = set()
        self.expanded_nodes_2: set[URIRef] = set()

    @property
    def ns_to_code(self) -> dict[str, str]:
        return self._ns_to_code

    def interior_char_estimate(self) -> int:
        """Estimate serialized size of the two interior graphs combined."""
        return (
            len(graph_to_string(self.onto_1, self._ns_to_code))
            + len(graph_to_string(self.onto_2, self._ns_to_code))
        )

    def _render_border(
        self, border_graph: Graph, expanded_nodes: set[URIRef], used_chars: int
    ) -> str:
        """Render border nodes as Entity declarations, with triples when space allows.

        Nodes in *expanded_nodes* (seeds and phase-2 expansions) are excluded — they
        appear in [Ontology_N] and must not be duplicated in [Border_N].
        """
        subjects = sorted(
            {s for s, _, _ in border_graph if isinstance(s, URIRef)} - expanded_nodes,
            key=str,
        )
        lines = []
        remaining = self._max_chars - used_chars
        for subj in subjects:
            enc = _encode_border(subj, self._ns_to_code)
            tuple_strs = []
            for _, p, o in border_graph.triples((subj, None, None)):
                p_enc = _encode_border(URIRef(str(p)), self._ns_to_code)
                o_enc = str(o) if isinstance(o, Literal) else _encode_border(URIRef(str(o)), self._ns_to_code)
                tuple_strs.append(f"('{enc}', '{p_enc}', '{o_enc}')")
            full_line = f"Entity('{enc}', tuples=[{', '.join(tuple_strs)}])"
            bare_line = f"Entity('{enc}', tuples=[])"
            chosen = full_line if len(full_line) <= remaining else bare_line
            lines.append(chosen)
            remaining -= len(chosen) + 1  # +1 for the joining newline
        return "\n".join(lines)

    def to_string(self) -> tuple[str, dict[str, str]]:
        """Serialise the environment as a KG2Code prompt string.

        Every URI is encoded as 'code::LocalName' so the LLM can reconstruct
        full URIs from the response.  Returns (prompt_string, code_to_ns).
        """
        onto1_str = graph_to_string(self.onto_1, self._ns_to_code)
        onto2_str = graph_to_string(self.onto_2, self._ns_to_code)
        alignments_str = "\n".join(al.to_string() for al in self.alignments)
        base_chars = len(onto1_str) + len(onto2_str) + len(alignments_str)
        border1_str = self._render_border(self.border1_graph, self.expanded_nodes_1, base_chars)
        border2_str = self._render_border(self.border2_graph, self.expanded_nodes_2, base_chars + len(border1_str))
        text = f"""
            {render_kg2code_preamble(self._ns_to_code)}


            [Ontology_1]:
            {onto1_str}
            [Border_1]:
            {border1_str}

            [Ontology_2]:
            {onto2_str}
            [Border_2]:
            {border2_str}

            [Alignment]:
            {alignments_str}
        """
        return text, self._code_to_ns
