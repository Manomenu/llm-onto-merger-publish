#!/usr/bin/env bash
# tests/analiza-deepseek/analyze-all.sh
#
# Extended, side-by-side version of tests/analiza/ comparing the two LLM
# backends used for "Proposed" (the merger method):
#   - "Proposed gpt-oss-20b"        — original tests/analiza data (vLLM, per .env)
#   - "Proposed deepseek-v4-flash"  — scenario_5 (AML-input) / scenario_6
#                                     (reference-input) OpenRouter runs
#
# IMPORTANT: this script does NOT regenerate any scenario data — no
# scenario_*.sh, no metrics_and_insights_raport.py, no AROM/Boomer/CoMerger/
# LLM re-runs.  It only:
#   1. copies tests/analiza/'s already-computed CSVs/JPGs as a starting point
#   2. renames "Our Solution" -> "Proposed gpt-oss-20b" in every raw CSV
#   3. adds a "Proposed deepseek-v4-flash" column, read from scenario_5's /
#      scenario_6's already-computed m_i_raport_<label>.csv files
#   4. re-runs the existing generic aggregate/normalize/merge/plot scripts
#      (unchanged) against the augmented raw CSVs to regenerate every derived
#      CSV + chart, mirroring each tests/analiza/*/analyze.sh's own pipeline
#      one-for-one, minus its "step 1" extraction (already covered by step 3).
#
# Requires: tests/analiza/ populated (gpt-oss-20b data), and scenario_5.sh /
# scenario_6.sh already run to completion (deepseek-v4-flash data) under
# tests/scenarios/outputs/s5/ and .../s6/.
#
# Usage:
#   tests/analiza-deepseek/analyze-all.sh

set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
REPO_ROOT="$(cd ../.. && pwd)"

echo "========================================"
echo "  analiza-deepseek / analyze-all.sh"
echo "========================================"

# ── 0. Fresh copy of tests/analiza/ as the gpt-oss-20b baseline ─────────────
echo
echo "[0] Copying tests/analiza/ -> tests/analiza-deepseek/ (baseline data)"
rsync -a --exclude='__pycache__' --exclude='logs' \
  --exclude='add_deepseek_column.py' \
  --exclude='analyze-all.sh' \
  --exclude='understandability/new_annotations_by_model.py' \
  --exclude='domain_coherence/oaei_rejection_deepseek.py' \
  --exclude='errors/error_rate_deepseek.py' \
  --exclude='errors/error_rate_by_model.csv' \
  --exclude='errors/error_rate_by_model.jpg' \
  --exclude='summary/compute_radar_scores.py' \
  --exclude='summary/plot_radar.py' \
  "$REPO_ROOT/tests/analiza/" "$HERE/"

# Normalize any stale "cmt-edas" label back to "conference" (tests/analiza
# itself never uses that rename; only scenario_5/6 output DIRECTORIES do).
grep -rl "cmt-edas" "$HERE" --include="*.csv" 2>/dev/null | while read -r f; do
  python3 -c "
import pathlib, sys
p = pathlib.Path(sys.argv[1])
p.write_text(p.read_text().replace('cmt-edas', 'conference'))
" "$f"
done

# ── 1. accuracy ──────────────────────────────────────────────────────────────
echo
echo "[1] accuracy"
uv run python3 add_deepseek_column.py --metric triple_preservation_ratio \
  --input accuracy/triple_preservation_ratio.csv --output accuracy/triple_preservation_ratio.csv
uv run python3 aggregate_mean.py \
  --metric "Triple Preservation Ratio" accuracy/triple_preservation_ratio.csv \
  --exclude-method "Naive Union" \
  --output accuracy/tpr_mean.csv
uv run python3 plot_pct.py \
  --input accuracy/tpr_mean.csv --output accuracy/tpr_mean.jpg \
  --ylabel-for "Triple Preservation Ratio" "Triple preservation ratio (avg over 4 datasets)" \
  --bar-fmt "%.2f"

# ── 2. structural_coherence ─────────────────────────────────────────────────
echo
echo "[2] structural_coherence"
uv run python3 add_deepseek_column.py --metric cycle_count \
  --input structural_coherence/cycle_count.csv --output structural_coherence/cycle_count.csv

# ── 3. conciseness ───────────────────────────────────────────────────────────
echo
echo "[3] conciseness"
uv run python3 add_deepseek_column.py --metric syntactic_uniqueness_ratio \
  --input conciseness/syntactic_uniqueness_ratio.csv --output conciseness/syntactic_uniqueness_ratio.csv
uv run python3 add_deepseek_column.py --metric structural_redundancy \
  --input conciseness/structural_redundancy.csv --output conciseness/structural_redundancy.csv
uv run python3 aggregate_mean.py \
  --metric "Syntactic Uniqueness Ratio" conciseness/syntactic_uniqueness_ratio.csv \
  --metric "Structural Redundancy" conciseness/structural_redundancy.csv \
  --output conciseness/conciseness_mean.csv
uv run python3 plot_pct.py \
  --input conciseness/conciseness_mean.csv --output conciseness/conciseness_mean.jpg \
  --ylabel-for "Syntactic Uniqueness Ratio" "Syntactic uniqueness ratio (avg)" \
  --ylabel-for "Structural Redundancy" "Structural redundancy (avg)" \
  --bar-fmt "%.2f"

# ── 4. knowledge_completeness ───────────────────────────────────────────────
echo
echo "[4] knowledge_completeness"
KC=knowledge_completeness
for m in corc_per_applied_alignment cross_onto_subclassof_count new_cross_onto_relations_count \
         applied_alignments new_intra_onto_relations_count triple_count_delta; do
  uv run python3 add_deepseek_column.py --metric "$m" --input "$KC/$m.csv" --output "$KC/$m.csv"
done
uv run python3 normalize_metric.py \
  --numerator "$KC/cross_onto_subclassof_count.csv" \
  --denominator "$KC/applied_alignments.csv" \
  --output "$KC/cosc_per_applied_alignment.csv"
uv run python3 aggregate_mean.py \
  --metric "NCRC" "$KC/new_cross_onto_relations_count.csv" \
  --metric "NIRC" "$KC/new_intra_onto_relations_count.csv" \
  --exclude-method "Naive Union" \
  --output "$KC/ncrc_nirc_mean.csv"
uv run python3 aggregate_mean.py \
  --metric "Triples Count Change" "$KC/triple_count_delta.csv" \
  --exclude-method "Naive Union" \
  --output "$KC/tcc_mean.csv"
uv run python3 plot_pct.py \
  --input "$KC/ncrc_nirc_mean.csv" --output "$KC/ncrc_nirc_mean.jpg" \
  --ylabel-for "NCRC" "New cross-onto relations (avg, log)" \
  --ylabel-for "NIRC" "New intra-onto relations (avg, log)" \
  --log-for "NCRC" --log-for "NIRC" --bar-fmt "%.1f"
uv run python3 plot_pct.py \
  --input "$KC/tcc_mean.csv" --output "$KC/tcc_mean.jpg" \
  --ylabel-for "Triples Count Change" "Triples count change (avg)" \
  --bar-fmt "%+.0f"

# ── 5. understandability ────────────────────────────────────────────────────
echo
echo "[5] understandability"
U=understandability
uv run python3 add_deepseek_column.py --metric comment_coverage_ratio \
  --input "$U/comment_coverage_ratio.csv" --output "$U/comment_coverage_ratio.csv"
uv run python3 aggregate_mean.py \
  --metric "Comment Coverage Ratio" "$U/comment_coverage_ratio.csv" \
  --output "$U/ccr_mean.csv"
uv run python3 plot_pct.py \
  --input "$U/ccr_mean.csv" --output "$U/ccr_mean.jpg" \
  --ylabel-for "Comment Coverage Ratio" "Comment coverage ratio (avg over 4 datasets)" \
  --bar-fmt "%.2f"
uv run python3 "$U/new_annotations_by_model.py" "$U/new_annotations_by_model.csv"

# ── 6. hierarchy_integration_quality ────────────────────────────────────────
echo
echo "[6] hierarchy_integration_quality"
HIQ=hierarchy_integration_quality
for m in ARC average_depth max_depth average_breadth max_breadth; do
  uv run python3 add_deepseek_column.py --metric "$m" --input "$HIQ/$m.csv" --output "$HIQ/$m.csv"
done
uv run python3 aggregate_pct.py \
  --metric average_depth "$HIQ/average_depth.csv" \
  --metric ARC "$HIQ/ARC.csv" \
  --metric average_breadth "$HIQ/average_breadth.csv" \
  --metric max_breadth "$HIQ/max_breadth.csv" \
  --exclude swo-union-s2 \
  --output "$HIQ/hiq_pct_change.csv"
uv run python3 plot_pct.py --input "$HIQ/hiq_pct_change.csv" --output "$HIQ/hiq_pct_change.jpg"

# ── 7. domain_coherence ──────────────────────────────────────────────────────
echo
echo "[7] domain_coherence"
DC=domain_coherence
uv run python3 add_deepseek_column.py --metric applied_alignments \
  --input "$DC/applied_alignments.csv" --output "$DC/applied_alignments.csv"
uv run python3 add_deepseek_column.py --metric multi_domain_range_count \
  --input "$DC/multi_domain_range_count.csv" --output "$DC/multi_domain_range_count.csv"
uv run python3 add_deepseek_column.py --metric multi_domain_range_change_per_alignment \
  --input "$DC/multi_domain_range_change_per_alignment.csv" --output "$DC/multi_domain_range_change_per_alignment.csv"
uv run python3 aggregate_pct.py \
  --metric "Applied Alignments" "$DC/applied_alignments.csv" \
  --baseline "Applied Alignments" \
  --exclude-method "Naive Union" --exclude-method "Applied Alignments" \
  --output "$DC/applied_alignments_pct_change.csv"
uv run python3 aggregate_mean.py \
  --metric "Multi D/R Change per Alignment" "$DC/multi_domain_range_change_per_alignment.csv" \
  --exclude-method "Naive Union" --exclude-method "Applied Alignments" \
  --output "$DC/multi_dr_change_per_alignment_mean.csv"
uv run python3 merge_csvs.py \
  --input "$DC/applied_alignments_pct_change.csv" \
  --input "$DC/multi_dr_change_per_alignment_mean.csv" \
  --output "$DC/domain_coherence_combined.csv"
uv run python3 plot_pct.py \
  --input "$DC/domain_coherence_combined.csv" --output "$DC/domain_coherence_combined.jpg" \
  --ylabel-for "Applied Alignments" "% change vs Applied Alignments" \
  --ylabel-for "Multi D/R Change per Alignment" "Multi D/R Δ per alignment" \
  --bar-fmt-for "Applied Alignments" "%+.1f%%" \
  --bar-fmt-for "Multi D/R Change per Alignment" "%+.2f"

# Special OAEI-reference measures (needs both s5=AML-input and s6=reference-input).
uv run python3 "$DC/oaei_rejection_deepseek.py"

# ── 8. errors ────────────────────────────────────────────────────────────────
echo
echo "[8] errors"
uv run python3 errors/error_rate_deepseek.py

# ── 9. summary (radar) ───────────────────────────────────────────────────────
echo
echo "[9] summary"
uv run python3 summary/compute_radar_scores.py summary/radar_scores.csv
uv run python3 summary/plot_radar.py --input summary/radar_scores.csv --output summary/radar.jpg

echo
echo "========================================"
echo "  Done. See tests/analiza-deepseek/ for all CSVs/JPGs."
echo "========================================"
