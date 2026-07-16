#!/usr/bin/env bash
# Boomer wrapper: takes two OWL ontologies + output dir, generates the required
# Boomer inputs (combined.owl, prefixes.yaml, ptable.tsv) into ./artifacts/, and
# runs the bundled Boomer binary.
#
# Usage:
#   thirdparty/boomer/boomer.sh <ONT1.owl> <ONT2.owl> <OUTPUT_DIR> [MATCHER]
#
# MATCHER (optional, 4th positional arg) — source of ptable mappings:
#   aml       run AML matcher, use its measure as p_equiv per pair
#   logmap    run LogMap matcher, use its measure as p_equiv per pair
#   lexical   (default) local-name match across both ontologies, fixed p_equiv=0.70
#
# Optional env vars (override default Boomer params):
#   BOOMER_WINDOW_COUNT   default 10
#   BOOMER_RUNS           default 5
#
# Example:
#   thirdparty/boomer/boomer.sh \\
#       tests/inputs/conference/cmt.owl \\
#       tests/inputs/conference/edas.owl \\
#       /tmp/boomer_conference \\
#       aml

set -euo pipefail

if [ $# -lt 3 ] || [ $# -gt 4 ]; then
  echo "Usage: $0 <ONT1.owl> <ONT2.owl> <OUTPUT_DIR> [aml|logmap|lexical]" >&2
  exit 1
fi

ONT1="$1"
ONT2="$2"
OUT_DIR="$3"
MATCHER="${4:-lexical}"

case "$MATCHER" in
  aml|logmap|lexical) ;;
  *) echo "Error: MATCHER must be one of: aml, logmap, lexical (got: $MATCHER)" >&2; exit 1 ;;
esac

if [ ! -f "$ONT1" ]; then echo "Error: $ONT1 not found" >&2; exit 1; fi
if [ ! -f "$ONT2" ]; then echo "Error: $ONT2 not found" >&2; exit 1; fi

BOOMER_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$BOOMER_DIR/../.." && pwd)"
ARTIFACTS_DIR="$BOOMER_DIR/artifacts"

WINDOW_COUNT="${BOOMER_WINDOW_COUNT:-10}"
RUNS="${BOOMER_RUNS:-5}"

ONT1_ABS="$(cd "$(dirname "$ONT1")" && pwd)/$(basename "$ONT1")"
ONT2_ABS="$(cd "$(dirname "$ONT2")" && pwd)/$(basename "$ONT2")"

echo "========================================"
echo "  Boomer wrapper"
echo "    onto1:        $ONT1_ABS"
echo "    onto2:        $ONT2_ABS"
echo "    output dir:   $OUT_DIR"
echo "    artifacts:    $ARTIFACTS_DIR"
echo "    matcher:      $MATCHER"
echo "    window-count: $WINDOW_COUNT"
echo "    runs:         $RUNS"
echo "========================================"

# Translate MATCHER → generate_inputs.py flag
MATCHER_FLAG=()
case "$MATCHER" in
  aml)     MATCHER_FLAG=( --use-aml ) ;;
  logmap)  MATCHER_FLAG=( --use-logmap ) ;;
  lexical) MATCHER_FLAG=() ;;
esac

cd "$REPO_ROOT"
mkdir -p "$ARTIFACTS_DIR"
uv run python "$BOOMER_DIR/generate_inputs.py" \
  --onto1 "$ONT1_ABS" \
  --onto2 "$ONT2_ABS" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  "${MATCHER_FLAG[@]}"

mkdir -p "$OUT_DIR"
echo
echo "========================================"
echo "  Running Boomer"
echo "========================================"
"$BOOMER_DIR/bin/boomer" \
  --ontology "$ARTIFACTS_DIR/combined.owl" \
  --ptable "$ARTIFACTS_DIR/ptable.tsv" \
  --prefixes "$ARTIFACTS_DIR/prefixes.yaml" \
  --output "$OUT_DIR" \
  --window-count "$WINDOW_COUNT" \
  --runs "$RUNS"

# Boomer writes <OUT_DIR>.ofn (merged ontology in OWL Functional Notation) and
# <OUT_DIR>.md (markdown report) ALONGSIDE the OUT_DIR folder — not inside it.
# Convert .ofn → merged_ontology.owl (RDF/XML) via owltools and move into OUT_DIR.
BASENAME="$(basename "$OUT_DIR")"
PARENT="$(cd "$(dirname "$OUT_DIR")" && pwd)"
OUT_DIR_ABS="$PARENT/$BASENAME"
OFN_FILE="$PARENT/$BASENAME.ofn"
MD_FILE="$PARENT/$BASENAME.md"
OWLTOOLS="$REPO_ROOT/thirdparty/owltools/owltools"

if [ -f "$OFN_FILE" ]; then
  echo
  echo "========================================"
  echo "  Post-processing"
  echo "    .ofn → raw → apply equivalences → merged_ontology.owl"
  echo "========================================"
  if [ ! -x "$OWLTOOLS" ]; then
    echo "Error: $OWLTOOLS not found/executable — needed for OFN → RDF/XML conversion" >&2
    exit 1
  fi
  # Step 1: OFN → RDF/XML (raw Boomer output: declarations + equivalentClass axioms)
  BOOMER_RAW="$ARTIFACTS_DIR/boomer_raw.owl"
  "$OWLTOOLS" "$OFN_FILE" -o "file://$BOOMER_RAW"
  rm -f "$OFN_FILE"
  # Step 2: apply Boomer's accepted equivalences to source ontologies (like
  # apply_alignments does for AML/LogMap) so the result is a full merged ontology
  # comparable to applied_alignments.owl and the LLM's merged_ontology.owl.
  uv run python "$BOOMER_DIR/apply_boomer.py" \
    --onto1 "$ONT1_ABS" \
    --onto2 "$ONT2_ABS" \
    --boomer-raw "$BOOMER_RAW" \
    --output "$OUT_DIR_ABS/merged_ontology.owl"
fi
if [ -f "$MD_FILE" ]; then
  mv "$MD_FILE" "$OUT_DIR_ABS/report.md"
fi

echo
echo "Done. Output in: $OUT_DIR_ABS"
