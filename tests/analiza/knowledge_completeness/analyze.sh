#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)

# 1. Raw per-metric CSVs
uv run python3 ../extract_metric.py \
    --metric corc_per_applied_alignment \
    --datasets "${DATASETS[@]}" \
    --output corc_per_applied_alignment.csv

uv run python3 ../extract_metric.py \
    --metric cross_onto_subclassof_count \
    --datasets "${DATASETS[@]}" \
    --output cross_onto_subclassof_count.csv

uv run python3 ../extract_metric.py \
    --metric new_cross_onto_relations_count \
    --datasets "${DATASETS[@]}" \
    --output new_cross_onto_relations_count.csv

uv run python3 ../extract_metric.py \
    --metric applied_alignments \
    --datasets "${DATASETS[@]}" \
    --output applied_alignments.csv

uv run python3 ../extract_metric.py \
    --metric new_intra_onto_relations_count \
    --datasets "${DATASETS[@]}" \
    --output new_intra_onto_relations_count.csv

uv run python3 ../extract_metric.py \
    --metric triple_count_delta \
    --datasets "${DATASETS[@]}" \
    --output triple_count_delta.csv

# 2. Derived: COSC per applied alignment (raw CSV, per-cell division)
uv run python3 ../normalize_metric.py \
    --numerator cross_onto_subclassof_count.csv \
    --denominator applied_alignments.csv \
    --output cosc_per_applied_alignment.csv

# 3. Aggregated mean (NU excluded; swo excluded only from COSC/applied
#    because of Boomer's meta-hub merge artefact in that dataset)
uv run python3 ../aggregate_mean.py \
    --metric "NCRC" new_cross_onto_relations_count.csv \
    --metric "NIRC" new_intra_onto_relations_count.csv \
    --exclude-method "Naive Union" \
    --output ncrc_nirc_mean.csv

uv run python3 ../aggregate_mean.py \
    --metric "Triples Count Change" triple_count_delta.csv \
    --exclude-method "Naive Union" \
    --output tcc_mean.csv

# 4. Charts
uv run python3 ../plot_pct.py \
    --input ncrc_nirc_mean.csv \
    --output ncrc_nirc_mean.jpg \
    --ylabel-for "NCRC" "New cross-onto relations (avg, log)" \
    --ylabel-for "NIRC" "New intra-onto relations (avg, log)" \
    --log-for "NCRC" \
    --log-for "NIRC" \
    --bar-fmt "%.1f"

uv run python3 ../plot_pct.py \
    --input tcc_mean.csv \
    --output tcc_mean.jpg \
    --ylabel-for "Triples Count Change" "Triples count change (avg)" \
    --bar-fmt "%+.0f"

echo
echo "=== corc_per_applied_alignment.csv (raw — reference) ==="
cat corc_per_applied_alignment.csv | column -t -s,
echo
echo "=== cross_onto_subclassof_count.csv (raw) ==="
cat cross_onto_subclassof_count.csv | column -t -s,
echo
echo "=== cosc_per_applied_alignment.csv (derived) ==="
cat cosc_per_applied_alignment.csv | column -t -s,
echo
echo "=== new_intra_onto_relations_count.csv (raw) ==="
cat new_intra_onto_relations_count.csv | column -t -s,
echo
echo "=== triple_count_delta.csv (raw) ==="
cat triple_count_delta.csv | column -t -s,
echo
echo "=== new_cross_onto_relations_count.csv (raw) ==="
cat new_cross_onto_relations_count.csv | column -t -s,
echo
echo "=== ncrc_nirc_mean.csv ==="
cat ncrc_nirc_mean.csv | column -t -s,
echo
echo "=== tcc_mean.csv ==="
cat tcc_mean.csv | column -t -s,
