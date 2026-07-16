#!/usr/bin/env bash
# AROM wrapper: take two OWL ontologies + output dir, run AML for alignment,
# then AROMRunner (MergingWithoutRefactoring) and extract provenance sidecar.
#
# Usage:
#   thirdparty/arom/arom.sh <ONT1.owl> <ONT2.owl> <OUTPUT_DIR> [ALIGNMENT.rdf]
#
# Args:
#   ONT1.owl       — first source ontology
#   ONT2.owl       — second source ontology
#   OUTPUT_DIR     — destination for arom_ontology.owl + arom_stats.json + run.log
#   ALIGNMENT.rdf  — optional: pre-computed OAEI alignment file (e.g. from AML).
#                    If omitted, AML is invoked here.
#
# Outputs in OUTPUT_DIR:
#   arom_ontology.owl    Merged ontology (AROM, MergingWithoutRefactoring mode)
#   arom_stats.json      Provenance map for cross-ontology metric attribution
#   run.log              AROMRunner stdout/stderr

set -euo pipefail

if [ $# -lt 3 ] || [ $# -gt 4 ]; then
  echo "Usage: $0 <ONT1.owl> <ONT2.owl> <OUTPUT_DIR> [ALIGNMENT.rdf]" >&2
  exit 1
fi

ONT1="$1"
ONT2="$2"
OUT_DIR="$3"
ALIGNMENT="${4:-}"

if [ ! -f "$ONT1" ]; then echo "Error: $ONT1 not found" >&2; exit 1; fi
if [ ! -f "$ONT2" ]; then echo "Error: $ONT2 not found" >&2; exit 1; fi

AROM_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$AROM_DIR/../.." && pwd)"

ONT1_ABS="$(cd "$(dirname "$ONT1")" && pwd)/$(basename "$ONT1")"
ONT2_ABS="$(cd "$(dirname "$ONT2")" && pwd)/$(basename "$ONT2")"

mkdir -p "$OUT_DIR"
OUT_DIR_ABS="$(cd "$OUT_DIR" && pwd)"

echo "========================================"
echo "  AROM wrapper"
echo "    onto1:        $ONT1_ABS"
echo "    onto2:        $ONT2_ABS"
echo "    output dir:   $OUT_DIR_ABS"
echo "========================================"

cd "$REPO_ROOT"

# Step 1: ensure we have an alignment file (run AML if not provided)
if [ -z "$ALIGNMENT" ]; then
  echo "  → no alignment file provided — running AML"
  uv run python -c "
import asyncio, sys
from llm_onto_merger.alignment import AmlAlignmentModule
from llm_onto_merger.alignment.aml_alignment import ALIGNMENT_OUTPUT
mod = AmlAlignmentModule()
alignments = asyncio.run(mod.create_alignment('$ONT1_ABS', '$ONT2_ABS'))
print(f'  AML returned {len(alignments)} alignments → {ALIGNMENT_OUTPUT}')
"
  ALIGNMENT="$REPO_ROOT/artifacts/tmp_alignment.owl"
fi
ALIGNMENT_ABS="$(cd "$(dirname "$ALIGNMENT")" && pwd)/$(basename "$ALIGNMENT")"
echo "    alignment:    $ALIGNMENT_ABS"

# Step 2: ensure AROMRunner is built
if [ ! -f "$AROM_DIR/bin/merging/AROMRunner.class" ]; then
  echo "  → AROMRunner.class missing — building"
  "$AROM_DIR/build.sh"
fi

# Step 3: run AROMRunner
CP="$AROM_DIR/bin:$(find "$AROM_DIR/lib" -name "*.jar" | tr '\n' ':')"
echo
echo "========================================"
echo "  Running AROM (MergingWithoutRefactoring)"
echo "========================================"
java --add-opens=java.base/java.lang=ALL-UNNAMED \
  -cp "$CP" merging.AROMRunner \
  "$ONT1_ABS" \
  "$ONT2_ABS" \
  "$ALIGNMENT_ABS" \
  "$OUT_DIR_ABS/arom_ontology.owl" \
  2>&1 | tee "$OUT_DIR_ABS/run.log" || true

if [ ! -f "$OUT_DIR_ABS/arom_ontology.owl" ]; then
  echo "  ERROR: AROMRunner failed to produce arom_ontology.owl" >&2
  exit 1
fi

# Step 4: extract provenance sidecar (rdfs:label per Code_X URI)
echo
echo "========================================"
echo "  Extracting provenance → arom_stats.json"
echo "========================================"
uv run python "$AROM_DIR/extract_arom_stats.py" \
  --arom "$OUT_DIR_ABS/arom_ontology.owl" \
  --output "$OUT_DIR_ABS/arom_stats.json"

echo
echo "Done. Output in: $OUT_DIR_ABS"
