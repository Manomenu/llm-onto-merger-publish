#!/usr/bin/env bash
# Example: run CoMerger on the conference dataset (cmt.owl + edas.owl).
# Output lands in thirdparty/CoMerger-1.2/artifacts/ (gitignored).
#
# Usage:
#   ./thirdparty/CoMerger-1.2/example-run.sh
#
# Prerequisites:
#   - Maven installed (brew install maven)
#   - First run also triggers ./build.sh which downloads ~150MB of Maven deps
#     into .m2-local/ (local, not ~/.m2/).

set -euo pipefail

COMERGER_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$COMERGER_DIR/../.." && pwd)"

INPUT_DIR="$REPO_ROOT/tests/inputs/conference"
OUTPUT_DIR="$COMERGER_DIR/artifacts/conference"

mkdir -p "$OUTPUT_DIR"

echo "Running CoMerger example: conference"
echo "  inputs: $INPUT_DIR"
echo "  output: $OUTPUT_DIR"
echo

"$COMERGER_DIR/comerger.sh" \
  "$INPUT_DIR/cmt.owl" \
  "$INPUT_DIR/edas.owl" \
  "$OUTPUT_DIR"

echo
echo "Done. See $OUTPUT_DIR/merged_ontology.owl"
