#!/bin/bash
# LLM error-rate analysis: failed environments / total environments for the LAST
# run of each dataset, read from logs/app.log.  A "failed" env = LLM response
# could not be parsed (pipeline fell back to deterministic collapse_alignments).
set -euo pipefail
cd "$(dirname "$0")"

LOG="../../../logs/app.log"

uv run python3 error_rate.py \
    --log "$LOG" \
    --dataset conference \
    --dataset human-mouse \
    --out-csv error_rate.csv \
    --out-jpg error_rate.jpg

echo
echo "=== error_rate.csv ==="
cat error_rate.csv | column -t -s,
