#!/usr/bin/env bash
# Scenario #4: human-mouse ONLY, LLM merger ONLY, with verbose error diagnostics.
#
# Purpose: understand WHY environments produce empty merged graphs.  Sets
# LLM_MERGE_DEBUG=1 so module.py logs, for every empty merged graph, the cause:
#   - input_keys (URI–URI input triples), entities_received, dropped breakdown,
#   - a DEGENERATE (empty input → nothing to merge) vs REAL classification,
#   - and (only for REAL, i.e. input>0) the raw LLM response.
#
# Most "empty graph" envs are DEGENERATE: a leaf/peripheral alignment pair whose
# extracted environment has no interior URI–URI structure, so the LLM correctly
# returns nothing — that is NOT a merge failure (see tests/analiza/errors/).
#
# Usage:
#   tests/scenarios/scenario_4.sh            # reference.rdf as input (reproduces s3)
#   tests/scenarios/scenario_4.sh --aml      # AML as input instead
#
# Output: tests/scenarios/outputs/human-mouse-s4/... (gitignored).  Full log in
# run.log; the per-env EMPTY-cause lines are also streamed to the console.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
if [ -f "$REPO_ROOT/.env" ]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

DATASET="human-mouse"  # scenario_4 is human-mouse-only by design
USE_AML=0
[ "${1:-}" = "--aml" ] && USE_AML=1

INPUT_DIR="tests/inputs/$DATASET"
OWL_FILES=( "$INPUT_DIR"/*.owl )
IFS=$'\n' OWL_SORTED=( $(printf '%s\n' "${OWL_FILES[@]}" | sort) ); unset IFS
BASE="${OWL_SORTED[0]}"; CANDIDATE="${OWL_SORTED[1]}"
REFERENCE="$INPUT_DIR/reference.rdf"

OUT_DIR="tests/scenarios/outputs/${DATASET}-s4/${DATASET}-s4_debug"
mkdir -p "$OUT_DIR"

# Input alignment: reference (default, reproduces the s3 run) or AML.
ALIGN_ARGS=()
if [ "$USE_AML" = "1" ]; then
  ALIGN_ARGS=( --alignment-tool aml )
  echo "  alignment: AML"
else
  if [ ! -f "$REFERENCE" ]; then echo "Error: $REFERENCE missing" >&2; exit 1; fi
  ALIGN_ARGS=( --alignment-file "$REFERENCE" )
  echo "  alignment: reference ($REFERENCE)"
fi

echo "========================================"
echo "  Scenario 4 / $DATASET (verbose error diagnostics)"
echo "    base:       $BASE"
echo "    candidate:  $CANDIDATE"
echo "    output dir: $OUT_DIR"
echo "    LLM_MERGE_DEBUG=1 → empty-graph cause is logged per env"
echo "========================================"

# LLM merger only (baselines irrelevant for this diagnostic).  LLM_MERGE_DEBUG=1
# turns on the verbose cause logging.  Stream the cause/error lines live.
set +o pipefail
LLM_MERGE_DEBUG=1 uv run llm-onto-merger \
  --base "$BASE" \
  --candidate "$CANDIDATE" \
  "${ALIGN_ARGS[@]}" \
  --output "$OUT_DIR" \
  --max-env-chars 15000 \
  --parallel-llm-request-count 24 \
  2>&1 \
  | tee "$OUT_DIR/run.log" \
  | { grep --line-buffered -E "EMPTY merged graph — cause|EMPTY-with-input DEBUG|Alignment application summary|could not be parsed" || true; }
rc="${PIPESTATUS[0]}"
set -o pipefail

echo
echo "Done (exit $rc). Full log: $OUT_DIR/run.log"
echo "Summary of empty-graph causes (DEGENERATE vs REAL):"
grep -oE "cause: (DEGENERATE|REAL)[^|]*" "$OUT_DIR/run.log" | sort | uniq -c || true
