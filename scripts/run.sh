#!/usr/bin/env bash
# Interactive launcher for llm-onto-merger.
#
# Usage:
#   scripts/run.sh                 # prompts for everything
#   scripts/run.sh conference      # uses tests/inputs/conference, prompts for the rest
#
# Picks the two .owl files in tests/inputs/<name>/ alphabetically as base & candidate.
# Defaults:
#   alignment tool    aml
#   max env chars     15000
#   output subfolder  outputs   →  tests/outputs/<name>/
#
# Pass a different output subfolder to write to tests/<subfolder>/<name>/ instead.

set -euo pipefail
shopt -s nullglob

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck source=../.env
  source "$REPO_ROOT/.env"
  set +a
fi

DEFAULT_ALIGNMENT_TOOL="aml"
DEFAULT_MAX_CHARS=15000
DEFAULT_OUTPUT_SUBFOLDER="outputs"
# parallel_llm_request_count default = wartość z .env (PARALLEL_LLM_REQUEST_COUNT),
# fallback do 4 jeśli .env nie ustawia.
DEFAULT_PARALLEL_LLM_REQUESTS="${PARALLEL_LLM_REQUEST_COUNT:-4}"

INPUT_NAME="${1:-}"
if [ -z "$INPUT_NAME" ]; then
  echo "Available input folders:"
  for d in tests/inputs/*/; do
    echo "  - $(basename "$d")"
  done
  echo
  read -r -p "Input folder name: " INPUT_NAME
fi

INPUT_DIR="tests/inputs/$INPUT_NAME"
if [ ! -d "$INPUT_DIR" ]; then
  echo "Error: directory not found: $INPUT_DIR" >&2
  exit 1
fi

OWL_FILES=( "$INPUT_DIR"/*.owl )
if [ ${#OWL_FILES[@]} -ne 2 ]; then
  echo "Error: expected exactly 2 .owl files in $INPUT_DIR, found ${#OWL_FILES[@]}" >&2
  exit 1
fi
# Sort alphabetically for deterministic base/candidate assignment.
IFS=$'\n' OWL_SORTED=( $(printf '%s\n' "${OWL_FILES[@]}" | sort) )
unset IFS
BASE="${OWL_SORTED[0]}"
CANDIDATE="${OWL_SORTED[1]}"

AVAILABLE_TOOLS=$(uv run python -c "from llm_onto_merger.alignment import alignment_modules_dict; print(' '.join(alignment_modules_dict))" 2>/dev/null)
if [ -z "$AVAILABLE_TOOLS" ]; then
  AVAILABLE_TOOLS="aml logmap"
fi
echo
echo "Available alignment tools: $AVAILABLE_TOOLS"
read -r -p "Alignment tool [$DEFAULT_ALIGNMENT_TOOL]: " ALIGNMENT_TOOL
ALIGNMENT_TOOL="${ALIGNMENT_TOOL:-$DEFAULT_ALIGNMENT_TOOL}"

read -r -p "Max env chars [$DEFAULT_MAX_CHARS]: " MAX_CHARS
MAX_CHARS="${MAX_CHARS:-$DEFAULT_MAX_CHARS}"

read -r -p "Output subfolder under tests/ [$DEFAULT_OUTPUT_SUBFOLDER]: " OUTPUT_SUBFOLDER
OUTPUT_SUBFOLDER="${OUTPUT_SUBFOLDER:-$DEFAULT_OUTPUT_SUBFOLDER}"

read -r -p "Parallel LLM requests [$DEFAULT_PARALLEL_LLM_REQUESTS]: " PARALLEL_REQUESTS
PARALLEL_REQUESTS="${PARALLEL_REQUESTS:-$DEFAULT_PARALLEL_LLM_REQUESTS}"

OUTPUT_DIR="tests/$OUTPUT_SUBFOLDER/$INPUT_NAME"

echo
echo "Running with:"
echo "  base:                       $BASE"
echo "  candidate:                  $CANDIDATE"
echo "  alignment tool:             $ALIGNMENT_TOOL"
echo "  max env chars:              $MAX_CHARS"
echo "  parallel llm request count: $PARALLEL_REQUESTS"
echo "  output dir:                 $OUTPUT_DIR"
echo

exec uv run llm-onto-merger \
  --base "$BASE" \
  --candidate "$CANDIDATE" \
  --alignment-tool "$ALIGNMENT_TOOL" \
  --output "$OUTPUT_DIR" \
  --max-env-chars "$MAX_CHARS" \
  --parallel-llm-request-count "$PARALLEL_REQUESTS"
