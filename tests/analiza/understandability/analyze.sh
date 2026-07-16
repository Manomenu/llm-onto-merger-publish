#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)

# 1. Raw per-metric CSV — Comment Coverage Ratio (CCR).
#    Stricter than ACR: requires rdfs:comment, not just rdfs:label.
uv run python3 ../extract_metric.py \
    --metric comment_coverage_ratio \
    --datasets "${DATASETS[@]}" \
    --output comment_coverage_ratio.csv

# 2. Average across 4 datasets — CCR is a ratio in [0,1].  Includes Naive Union
#    as baseline so we can see what was in source.
uv run python3 ../aggregate_mean.py \
    --metric "Comment Coverage Ratio" comment_coverage_ratio.csv \
    --output ccr_mean.csv

uv run python3 ../plot_pct.py \
    --input ccr_mean.csv \
    --output ccr_mean.jpg \
    --ylabel-for "Comment Coverage Ratio" "Comment coverage ratio (avg over 4 datasets)" \
    --bar-fmt "%.2f"

# 3. New labels / new comments added by Our Solution
#    (annotations NOT present on the corresponding source entity, via reverse
#    relabeling_map alias normalization).
uv run python3 count_new_annotations.py new_annotations_os.csv

echo
echo "=== comment_coverage_ratio.csv (raw) ==="
cat comment_coverage_ratio.csv | column -t -s,
echo
echo "=== ccr_mean.csv ==="
cat ccr_mean.csv | column -t -s,
echo
echo "=== new_annotations_os.csv (Our Solution only) ==="
cat new_annotations_os.csv | column -t -s,
