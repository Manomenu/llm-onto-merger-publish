#!/usr/bin/env python3
"""Extract AROM provenance + per-ontology source attribution from arom_ontology.owl.

AROM rewrites merged entity URIs to `<merged_iri>#Code_N` and tags each one
with rdfs:label values of the form ``"<ontology_n>. <local_name>"``.  This
script reads those labels and emits a JSON sidecar that downstream metrics
code (metrics_def, metrics_and_insights_raport) can use for cross-ontology
attribution — without it cross_onto_* counts and triple_preservation_ratio
would collapse to zero because the merged URIs sit in a brand-new namespace.

Output (``arom_stats.json`` next to the merged OWL):

    {
      "code_provenance": {
        "<merging_iri>#Code_1": {
          "1": "SubjectArea",
          "2": "CommunicationsTopic"
        },
        ...
      },
      "merged_count": 9,
      "from_onto1_count": 9,
      "from_onto2_count": 9
    }

Each `code_provenance[code][n] = local_name` means: the entity coded as
`<code>` originated (also) from ontology #n with that local name.  When both
"1" and "2" keys are present, the entity is genuinely cross-ontology.

Usage:
    uv run python extract_arom_stats.py \\
        --arom <path/to/arom_ontology.owl> \\
        --output <path/to/arom_stats.json>
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import RDFS, Graph, Literal, URIRef


_LABEL_PATTERN = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$")


def _extract_provenance(g: Graph) -> dict[str, dict[str, str]]:
    """Walk rdfs:label triples of Code_X URIs; parse provenance markers.

    Returns {code_uri: {onto_n_str: local_name}}.
    """
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for s, _, o in g.triples((None, RDFS.label, None)):
        if not isinstance(s, URIRef) or not isinstance(o, Literal):
            continue
        if "Code_" not in str(s):
            continue
        match = _LABEL_PATTERN.match(str(o))
        if not match:
            continue
        onto_n, local = match.group(1), match.group(2)
        result[str(s)][onto_n] = local
    return dict(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arom", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if not args.arom.exists():
        sys.exit(f"AROM output not found: {args.arom}")

    print(f"[extract_arom_stats] loading {args.arom}")
    g = Graph()
    g.parse(str(args.arom))
    print(f"  triples: {len(g)}")

    provenance = _extract_provenance(g)
    from_onto1 = sum(1 for codes in provenance.values() if "1" in codes)
    from_onto2 = sum(1 for codes in provenance.values() if "2" in codes)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "code_provenance": provenance,
                "merged_count": len(provenance),
                "from_onto1_count": from_onto1,
                "from_onto2_count": from_onto2,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        f"[extract_arom_stats] saved → {args.output} "
        f"({len(provenance)} merged entities, onto1×{from_onto1} / onto2×{from_onto2})"
    )


if __name__ == "__main__":
    main()
