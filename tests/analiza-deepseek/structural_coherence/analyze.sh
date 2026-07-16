#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)

uv run python3 ../extract_metric.py \
    --metric cycle_count \
    --datasets "${DATASETS[@]}" \
    --output cycle_count.csv

echo
echo "=== cycle_count.csv ==="
cat cycle_count.csv | column -t -s,
