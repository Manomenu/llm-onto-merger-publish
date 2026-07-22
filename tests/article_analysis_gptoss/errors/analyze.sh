#!/usr/bin/env bash
# Per-turn LLM error/fallback rate for the gpt-oss article runs (s2=aml,
# s3=ref), recovered from each run dir's run.log — PURE LOG PARSING, never
# invokes merging or measure computation.  Shares error_rate_turns.py with
# article_analysis_deepseek (same helper-reuse convention as analyze-all.sh).
#
# Usage:
#   bash analyze.sh                 # turns = turn1..turn5 (default)
#   bash analyze.sh turn1 turn2     # explicit turn list
set -euo pipefail
cd "$(dirname "$0")"

TURNS=("$@")
[ ${#TURNS[@]} -gt 0 ] || TURNS=(turn1 turn2 turn3 turn4 turn5)

TURN_ARGS=()
for T in "${TURNS[@]}"; do
  TURN_ARGS+=(--turn "$T")
done

uv run python3 ../../article_analysis_deepseek/error_rate_turns.py \
    --layout gptoss --model gpt-oss-20b \
    "${TURN_ARGS[@]}" \
    --dataset confOf-ekaw --dataset human-mouse --dataset swo-acm \
    --out-csv errors.csv --out-summary errors_summary.csv

echo
echo "=== errors.csv ==="
column -t -s, < errors.csv
echo
echo "=== errors_summary.csv ==="
column -t -s, < errors_summary.csv
