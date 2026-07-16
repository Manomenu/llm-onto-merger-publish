#!/usr/bin/env python3
"""Generate applied_alignments.owl — alignment-collapsed merge into merged# namespace.

Aligned entity pairs are collapsed into new merged# entities carrying triples from both
source entities.  Non-aligned entities keep their original namespaces.  A sidecar
applied_stats.json records provenance for cross-onto metrics.

Usage:
    uv run python tests/generate_applied_alignments.py \\
        --onto1 path/to/onto1.owl \\
        --onto2 path/to/onto2.owl \\
        --output path/to/cache_dir \\
        [--tool aml|logmap]
        [--alignment-file path/to/reference.rdf]   # bypass matcher, use given alignment
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rdflib import Graph

from llm_onto_merger.alignment import alignment_modules_dict
from llm_onto_merger.alignment.alignment import parse_oaei_alignment
from llm_onto_merger.ontology import collapse_alignments_to_merged_ns, save_ontology


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onto1", required=True, type=Path)
    parser.add_argument("--onto2", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tool", default="aml", choices=list(alignment_modules_dict))
    parser.add_argument(
        "--alignment-file",
        default=None,
        type=Path,
        help="Pre-computed OAEI alignment (RDF/XML). When set, --tool is ignored.",
    )
    args = parser.parse_args()

    if not args.onto1.exists():
        sys.exit(f"onto1 not found: {args.onto1}")
    if not args.onto2.exists():
        sys.exit(f"onto2 not found: {args.onto2}")
    args.output.mkdir(parents=True, exist_ok=True)

    if args.alignment_file is not None:
        if not args.alignment_file.exists():
            sys.exit(f"alignment file not found: {args.alignment_file}")
        print(f"[generate_applied_alignments] using alignment file {args.alignment_file} …")
        alignments = parse_oaei_alignment(args.alignment_file)
        print(f"  loaded {len(alignments)} alignments from file")
    else:
        print(f"[generate_applied_alignments] running {args.tool} alignment …")
        module = alignment_modules_dict[args.tool]()
        alignments = asyncio.run(module.create_alignment(args.onto1, args.onto2))
        print(f"  {args.tool} returned {len(alignments)} alignments")

    raw_1 = Graph()
    raw_1.parse(str(args.onto1))
    raw_2 = Graph()
    raw_2.parse(str(args.onto2))
    applied, provenance = collapse_alignments_to_merged_ns(raw_1, raw_2, alignments)
    save_ontology(applied, args.output, name="applied_alignments")
    print(f"  saved {len(applied)} triples → {args.output}/applied_alignments.owl")

    stats_path = args.output / "applied_stats.json"
    stats_path.write_text(
        json.dumps({"code_provenance": provenance}, indent=2),
        encoding="utf-8",
    )
    print(f"  provenance ({len(provenance)} pairs) → {stats_path}")


if __name__ == "__main__":
    main()
