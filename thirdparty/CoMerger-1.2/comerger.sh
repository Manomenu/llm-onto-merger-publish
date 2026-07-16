#!/usr/bin/env bash
# CoMerger wrapper: take two OWL ontologies + output dir, run AML for alignment,
# then CoMergerRunner (HolisticMerger) and save as merged_ontology.owl.
#
# Usage:
#   thirdparty/CoMerger-1.2/comerger.sh <ONT1.owl> <ONT2.owl> <OUTPUT_DIR> [ALIGNMENT.rdf]
#
# Args:
#   ONT1.owl       — first source ontology
#   ONT2.owl       — second source ontology
#   OUTPUT_DIR     — destination dir for merged_ontology.owl + run.log
#   ALIGNMENT.rdf  — optional: pre-computed OAEI alignment file.  If omitted, AML is invoked.
#
# Outputs in OUTPUT_DIR:
#   merged_ontology.owl   The merged ontology (RDF/XML)
#   run.log               CoMergerRunner stdout/stderr

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

COMERGER_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$COMERGER_DIR/Source_Code"
REPO_ROOT="$(cd "$COMERGER_DIR/../.." && pwd)"

ONT1_ABS="$(cd "$(dirname "$ONT1")" && pwd)/$(basename "$ONT1")"
ONT2_ABS="$(cd "$(dirname "$ONT2")" && pwd)/$(basename "$ONT2")"

mkdir -p "$OUT_DIR"
OUT_DIR_ABS="$(cd "$OUT_DIR" && pwd)"

echo "========================================"
echo "  CoMerger wrapper"
echo "    onto1:        $ONT1_ABS"
echo "    onto2:        $ONT2_ABS"
echo "    output dir:   $OUT_DIR_ABS"
echo "========================================"

cd "$REPO_ROOT"

# Step 1: ensure we have an alignment file (run AML if not provided)
if [ -z "$ALIGNMENT" ]; then
  echo "  → no alignment file provided — running AML"
  uv run python -c "
import asyncio
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

# Step 2: ensure CoMergerRunner is built
if [ ! -f "$SRC_DIR/target/classes/fusion/comerger/algorithm/merger/holisticMerge/CoMergerRunner.class" ] \
   || [ ! -f "$SRC_DIR/target/cp_full.txt" ]; then
  echo "  → CoMergerRunner / classpath missing — building (this takes a minute first time)"
  "$COMERGER_DIR/build.sh"
fi

# Step 3: run CoMergerRunner
CP="$(cat "$SRC_DIR/target/cp_full.txt")"
echo
echo "========================================"
echo "  Running CoMerger (HolisticMerger)"
# Time limit (seconds).  CoMerger's holistic-merge "refine" phase runs the
# Pellet reasoner, whose RBox automaton construction blows up (exponential)
# on ontologies with many object-property chains (e.g. SWO, which pulls in
# BFO/RO/OBI).  On such pairs it never terminates, so we cap it and record a
# timeout marker instead of hanging the whole analysis run.  Override with
# COMERGER_TIMEOUT=<seconds> (0 disables the limit).
COMERGER_TIMEOUT="${COMERGER_TIMEOUT:-180}"
TIMEOUT_MARKER="$OUT_DIR_ABS/comerger_timeout.txt"
rm -f "$TIMEOUT_MARKER"

echo "========================================"
echo "  time limit: ${COMERGER_TIMEOUT}s (COMERGER_TIMEOUT to override; 0 = none)"

# Run java in the background so a watchdog can enforce the limit portably
# (macOS has no `timeout`/`gtimeout` by default).
java --add-opens=java.base/java.lang=ALL-UNNAMED \
  -cp "$CP" \
  fusion.comerger.algorithm.merger.holisticMerge.CoMergerRunner \
  "$ONT1_ABS" \
  "$ONT2_ABS" \
  "$ALIGNMENT_ABS" \
  "$OUT_DIR_ABS/merged_ontology.owl" \
  >"$OUT_DIR_ABS/run.log" 2>&1 &
JAVA_PID=$!

TIMED_OUT=0
if [ "$COMERGER_TIMEOUT" -gt 0 ]; then
  elapsed=0
  while kill -0 "$JAVA_PID" 2>/dev/null; do
    if [ "$elapsed" -ge "$COMERGER_TIMEOUT" ]; then
      TIMED_OUT=1
      echo "  TIMEOUT: CoMerger exceeded ${COMERGER_TIMEOUT}s — killing PID $JAVA_PID" \
        | tee -a "$OUT_DIR_ABS/run.log"
      pkill -P "$JAVA_PID" 2>/dev/null || true
      kill -TERM "$JAVA_PID" 2>/dev/null || true
      sleep 2
      kill -KILL "$JAVA_PID" 2>/dev/null || true
      break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
fi

JAVA_RC=0
wait "$JAVA_PID" 2>/dev/null || JAVA_RC=$?

if [ "$TIMED_OUT" = "1" ]; then
  printf 'CoMerger timed out after %s seconds (limit reached).\n' "$COMERGER_TIMEOUT" \
    > "$TIMEOUT_MARKER"
  rm -f "$OUT_DIR_ABS/merged_ontology.owl"
  echo "TIMEOUT: no merged_ontology.owl produced — wrote $TIMEOUT_MARKER" >&2
  exit 124
fi

if [ ! -f "$OUT_DIR_ABS/merged_ontology.owl" ]; then
  echo "ERROR: CoMerger did not produce $OUT_DIR_ABS/merged_ontology.owl (java exit $JAVA_RC)" >&2
  exit 1
fi

echo
echo "Done. Output: $OUT_DIR_ABS/merged_ontology.owl"
