#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)
# SUR-relevant datasets: only those where Naive Union has SUR < 1.0
# (i.e., source ontologies actually have repeating local names).
# Otherwise the metric is trivially 1.0 and the average is meaningless.
SUR_DATASETS=(conference-s2 swo-union-s2)

# 1. Raw per-metric CSVs
uv run python3 ../extract_metric.py \
    --metric syntactic_uniqueness_ratio \
    --datasets "${SUR_DATASETS[@]}" \
    --output syntactic_uniqueness_ratio.csv

uv run python3 ../extract_metric.py \
    --metric structural_redundancy \
    --datasets "${DATASETS[@]}" \
    --output structural_redundancy.csv

# 2. Average across applicable datasets — both metrics are normalised ratios
#    in [0,1].  Naive Union + Applied Alignments included (informative baselines).
uv run python3 ../aggregate_mean.py \
    --metric "Syntactic Uniqueness Ratio" syntactic_uniqueness_ratio.csv \
    --metric "Structural Redundancy" structural_redundancy.csv \
    --output conciseness_mean.csv

uv run python3 ../plot_pct.py \
    --input conciseness_mean.csv \
    --output conciseness_mean.jpg \
    --ylabel-for "Syntactic Uniqueness Ratio" "Syntactic uniqueness ratio (avg)" \
    --ylabel-for "Structural Redundancy" "Structural redundancy (avg)" \
    --bar-fmt "%.2f"

echo
echo "=== syntactic_uniqueness_ratio.csv (raw, conference+swo only) ==="
cat syntactic_uniqueness_ratio.csv | column -t -s,
echo
echo "=== structural_redundancy.csv (raw, all 4 datasets) ==="
cat structural_redundancy.csv | column -t -s,
echo
echo "=== conciseness_mean.csv ==="
cat conciseness_mean.csv | column -t -s,
