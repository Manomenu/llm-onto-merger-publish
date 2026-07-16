#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)
METRICS=(ARC average_depth max_depth average_breadth max_breadth)

# 1. Raw per-metric CSVs (all 4 datasets)
for METRIC in "${METRICS[@]}"; do
    uv run python3 ../extract_metric.py \
        --metric "$METRIC" \
        --datasets "${DATASETS[@]}" \
        --output "${METRIC}.csv"
done

# 2. Combined chart: avg_depth, ARC, avg_breadth, max_breadth (max_depth dropped)
uv run python3 ../aggregate_pct.py \
    --metric average_depth average_depth.csv \
    --metric ARC ARC.csv \
    --metric average_breadth average_breadth.csv \
    --metric max_breadth max_breadth.csv \
    --exclude swo-union-s2 \
    --output hiq_pct_change.csv

uv run python3 ../plot_pct.py \
    --input hiq_pct_change.csv \
    --output hiq_pct_change.jpg

echo
echo "=== hiq_pct_change.csv ==="
cat hiq_pct_change.csv | column -t -s,
