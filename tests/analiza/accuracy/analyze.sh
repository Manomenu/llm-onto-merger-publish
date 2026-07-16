#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)

# 1. Raw per-metric CSV
uv run python3 ../extract_metric.py \
    --metric triple_preservation_ratio \
    --datasets "${DATASETS[@]}" \
    --output triple_preservation_ratio.csv

# 2. Aggregated mean across 4 datasets.  Naive Union excluded (trivially 1.0).
#    TPR uses _key_norm on union — alias-aware via old_to_new (Format 1–4
#    in _build_alias_maps), so renames via relabeling_map.json or aliasy are
#    handled correctly and a triple lost only when truly missing from g.
uv run python3 ../aggregate_mean.py \
    --metric "Triple Preservation Ratio" triple_preservation_ratio.csv \
    --exclude-method "Naive Union" \
    --output tpr_mean.csv

uv run python3 ../plot_pct.py \
    --input tpr_mean.csv \
    --output tpr_mean.jpg \
    --ylabel-for "Triple Preservation Ratio" "Triple preservation ratio (avg over 4 datasets)" \
    --bar-fmt "%.2f"

echo
echo "=== triple_preservation_ratio.csv (raw) ==="
cat triple_preservation_ratio.csv | column -t -s,
echo
echo "=== tpr_mean.csv ==="
cat tpr_mean.csv | column -t -s,
