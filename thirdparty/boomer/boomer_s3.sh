#!/usr/bin/env bash
# Boomer wrapper variant for scenario_3: build the ptable from a PRE-COMPUTED
# OAEI alignment file (e.g. the OAEI reference / gold standard) instead of
# running a matcher (AML/LogMap/lexical).  No matcher is invoked.
#
# Usage:
#   thirdparty/boomer/boomer_s3.sh <ONT1.owl> <ONT2.owl> <OUTPUT_DIR> <ALIGNMENT.rdf>
#
# Args:
#   ONT1.owl       — first source ontology
#   ONT2.owl       — second source ontology
#   OUTPUT_DIR     — destination for merged_ontology.owl + report.md + run output
#   ALIGNMENT.rdf  — REQUIRED: OAEI alignment file (same format AML/LogMap emit);
#                    its per-cell measure becomes p_equiv in the ptable.
#
# Optional env vars (same as boomer.sh):
#   BOOMER_WINDOW_COUNT   default 10
#   BOOMER_RUNS           default 5
#
# This mirrors boomer.sh exactly except the ptable source: it passes
# --alignment-file to generate_inputs.py instead of --use-aml/--use-logmap.

set -euo pipefail

if [ $# -ne 4 ]; then
  echo "Usage: $0 <ONT1.owl> <ONT2.owl> <OUTPUT_DIR> <ALIGNMENT.rdf>" >&2
  exit 1
fi

ONT1="$1"
ONT2="$2"
OUT_DIR="$3"
ALIGNMENT="$4"

if [ ! -f "$ONT1" ]; then echo "Error: $ONT1 not found" >&2; exit 1; fi
if [ ! -f "$ONT2" ]; then echo "Error: $ONT2 not found" >&2; exit 1; fi
if [ ! -f "$ALIGNMENT" ]; then echo "Error: $ALIGNMENT not found" >&2; exit 1; fi

BOOMER_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$BOOMER_DIR/../.." && pwd)"
ARTIFACTS_DIR="$BOOMER_DIR/artifacts"

WINDOW_COUNT="${BOOMER_WINDOW_COUNT:-10}"
RUNS="${BOOMER_RUNS:-5}"

ONT1_ABS="$(cd "$(dirname "$ONT1")" && pwd)/$(basename "$ONT1")"
ONT2_ABS="$(cd "$(dirname "$ONT2")" && pwd)/$(basename "$ONT2")"
ALIGNMENT_ABS="$(cd "$(dirname "$ALIGNMENT")" && pwd)/$(basename "$ALIGNMENT")"

echo "========================================"
echo "  Boomer wrapper (scenario_3 / reference alignment)"
echo "    onto1:        $ONT1_ABS"
echo "    onto2:        $ONT2_ABS"
echo "    alignment:    $ALIGNMENT_ABS"
echo "    output dir:   $OUT_DIR"
echo "    artifacts:    $ARTIFACTS_DIR"
echo "    window-count: $WINDOW_COUNT"
echo "    runs:         $RUNS"
echo "========================================"

cd "$REPO_ROOT"
mkdir -p "$ARTIFACTS_DIR"
uv run python "$BOOMER_DIR/generate_inputs.py" \
  --onto1 "$ONT1_ABS" \
  --onto2 "$ONT2_ABS" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --alignment-file "$ALIGNMENT_ABS"

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

# Post-processing identical to boomer.sh: Boomer writes <OUT_DIR>.ofn / .md
# ALONGSIDE the output folder.  Convert .ofn → merged_ontology.owl (RDF/XML).
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
  BOOMER_RAW="$ARTIFACTS_DIR/boomer_raw.owl"
  "$OWLTOOLS" "$OFN_FILE" -o "file://$BOOMER_RAW"
  rm -f "$OFN_FILE"
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
