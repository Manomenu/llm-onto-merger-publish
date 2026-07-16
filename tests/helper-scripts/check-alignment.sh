#!/usr/bin/env bash
# tests/helper-scripts/check-alignment.sh — run AML on a tests/inputs/<name>
# ontology pair and print how many alignments it found + the matched pairs.
#
# Usage:
#   tests/helper-scripts/check-alignment.sh <folder-name>
#   tests/helper-scripts/check-alignment.sh swo-acm

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

NAME="${1:?Usage: check-alignment.sh <folder-name-under-tests/inputs>}"
INPUT_DIR="tests/inputs/$NAME"

if [ ! -d "$INPUT_DIR" ]; then
  echo "Error: directory not found: $INPUT_DIR" >&2
  exit 1
fi

OWL_FILES=( "$INPUT_DIR"/*.owl )
if [ ${#OWL_FILES[@]} -ne 2 ]; then
  echo "Error: expected exactly 2 .owl files in $INPUT_DIR, found ${#OWL_FILES[@]}" >&2
  exit 1
fi
IFS=$'\n' OWL_SORTED=( $(printf '%s\n' "${OWL_FILES[@]}" | sort) )
unset IFS
BASE="${OWL_SORTED[0]}"
CANDIDATE="${OWL_SORTED[1]}"

echo "========================================"
echo "  AML alignment check: $NAME"
echo "    base:      $BASE"
echo "    candidate: $CANDIDATE"
echo "========================================"

uv run python3 - "$BASE" "$CANDIDATE" <<'PY'
import asyncio
import sys
from pathlib import Path

from rdflib import Graph, RDFS

from llm_onto_merger.alignment import AmlAlignmentModule


def _local(uri: str) -> str:
    return uri.split("#")[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


def _load_labels(*paths: Path) -> dict[str, str]:
    """Map entity URI -> rdfs:label across the given ontology files."""
    labels: dict[str, str] = {}
    for path in paths:
        g = Graph()
        g.parse(path.as_posix())
        for subj, label in g.subject_objects(RDFS.label):
            labels.setdefault(str(subj), str(label))
    return labels


async def main() -> None:
    base, candidate = Path(sys.argv[1]), Path(sys.argv[2])
    labels = _load_labels(base, candidate)

    def name(uri: str) -> str:
        return labels.get(uri) or _local(uri)

    alignments = await AmlAlignmentModule().create_alignment(base, candidate)

    print(f"\nFound {len(alignments)} alignment(s):\n")
    for a in alignments:
        print(f"  {name(a.entity1)} ↔ {name(a.entity2)}  "
              f"(relation: {a.relation}, measure: {a.measure:.3f})")


asyncio.run(main())
PY
