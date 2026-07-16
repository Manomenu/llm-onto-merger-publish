#!/bin/bash
# Repeated-runs VARIANCE analysis — mirrors every chart/table in tests/analiza/
# but aggregates across N repeated runs ("turns"), reporting mean ± sample-std
# (error bars on charts, "mean ± std" in tables).  Answers a thesis reviewer's
# "single-seed anecdote" concern.
#
# Each dimension below follows tests/analiza/<dim>/analyze.sh exactly (same
# metric names, dataset lists, aggregation type, exclusions, plot flags) — the
# only difference is that aggregation happens once PER TURN, and the N
# per-turn aggregate CSVs are then combined (mean ± std across turns) via
# combine_turns.py / plot_variance.py instead of being charted directly.
#
# Usage:
#   bash analyze-all.sh                       # turns = turn1 turn2 turn3 (default)
#   TURNS="turn1 turn2" bash analyze-all.sh   # override via env var
#   bash analyze-all.sh turn1 turn2           # override via positional args
#   bash analyze-all.sh --no-run              # never invoke scenario_2/3.sh —
#                                              # turns with missing data are
#                                              # skipped (with a warning)
#
# EXISTENCE CHECK + AUTO-RUN: before aggregating, every turn is checked for the
# report/output files each dimension needs.  Missing data triggers
# tests/scenarios/scenario_2.sh / scenario_3.sh --label <turn> <dataset> to
# produce it — UNLESS --no-run is given, in which case the turn (or just the
# affected dataset, where the checks are per-dataset) is skipped instead.
set -euo pipefail
cd "$(dirname "$0")"

NO_RUN=0
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --no-run) NO_RUN=1 ;;
    -*) echo "Unknown option: $arg" >&2; exit 1 ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

if [ ${#POSITIONAL[@]} -gt 0 ]; then
  TURNS=("${POSITIONAL[@]}")
elif [ -n "${TURNS:-}" ]; then
  # Support both a proper space-separated string (TURNS="turn1 turn2") and the
  # literal "(turn1 turn2)" text that `TURNS=(turn1) cmd` produces — bash
  # arrays can't cross the exec/environment boundary, so that prefix-assignment
  # syntax exports the parenthesised text verbatim rather than a real array.
  _turns_raw="${TURNS#\(}"
  _turns_raw="${_turns_raw%\)}"
  read -r -a TURNS <<< "$_turns_raw"
else
  TURNS=(turn1 turn2 turn3)
fi

echo "=== Variance analysis over turns: ${TURNS[*]} (no-run=$NO_RUN) ==="

OUTROOT="../scenarios/outputs"

# Base dataset names (no -s2/-s3 suffix) used to invoke scenario_2.sh/scenario_3.sh.
MAIN_DATASETS=(conference human-mouse acm-union swo-union)
OAEI_EXTRA_S2=(confOf-ekaw)                       # OAEI needs this extra dataset's s2 run
REF_DATASETS=(conference human-mouse confOf-ekaw) # OAEI needs these datasets' s3 (reference) run

# -s2-suffixed dataset lists, as used by extract_metric.py (mirrors each
# analyze.sh's own DATASETS/SUR_DATASETS/DR_DATASETS arrays).
DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)
SUR_DATASETS=(conference-s2 swo-union-s2)
DR_DATASETS=(conference-s2 swo-union-s2)

S2_TAG="aml_15k_p24"
S3_TAG="ref_15k_p24"

_s2_report_exists() {  # turn, base-dataset-name (no suffix)
  [ -f "$OUTROOT/$1/${2}-s2/m_i_raport_${2}-s2.csv" ]
}

_s3_outputs_exist() {  # turn, base-dataset-name (no suffix)
  local dir="$OUTROOT/$1/${2}-s3/${2}-s3_${S3_TAG}"
  [ -f "$dir/alignment_stats.json" ] || [ -f "$dir/arom_ontology.owl" ]
}

# ── Per-turn existence check + auto-run (guarded by --no-run) ──────────────
# Ensures every turn has: s2 reports for the 4 main datasets + confOf-ekaw
# (used by the OAEI dimension), and s3 (reference-input) outputs for the 3
# OAEI reference datasets.  If turn1 (the test fixture) already has all of
# this, nothing is run regardless of --no-run.
for T in "${TURNS[@]}"; do
  for ds in "${MAIN_DATASETS[@]}" "${OAEI_EXTRA_S2[@]}"; do
    if ! _s2_report_exists "$T" "$ds"; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: missing s2 report for '$ds' and --no-run is set — skipping where needed."
      else
        echo "  [$T] missing s2 report for '$ds' — running scenario_2.sh --label $T $ds"
        ../scenarios/scenario_2.sh --label "$T" "$ds"
      fi
    fi
  done
  for ds in "${REF_DATASETS[@]}"; do
    if ! _s3_outputs_exist "$T" "$ds"; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: missing s3 outputs for '$ds' and --no-run is set — skipping where needed."
      else
        echo "  [$T] missing s3 outputs for '$ds' — running scenario_3.sh --label $T $ds"
        ../scenarios/scenario_3.sh --label "$T" "$ds"
      fi
    fi
  done
done

# ── Active turns for the "core" dimensions (need all 4 main datasets' s2) ──
CORE_TURNS=()
for T in "${TURNS[@]}"; do
  ok=1
  for ds in "${MAIN_DATASETS[@]}"; do
    _s2_report_exists "$T" "$ds" || ok=0
  done
  if [ "$ok" = "1" ]; then
    CORE_TURNS+=("$T")
  else
    echo "  WARNING: turn '$T' is missing core (4-dataset) s2 data — excluded from all core-dimension variance."
  fi
done

if [ ${#CORE_TURNS[@]} -eq 0 ]; then
  echo "ERROR: no turn has complete core s2 data — nothing to aggregate. Re-run without --no-run, or check $OUTROOT." >&2
  exit 1
fi
echo "Core turns (4-dataset s2 complete): ${CORE_TURNS[*]}"
N_CORE=${#CORE_TURNS[@]}

# ═══════════════════════════════════════════════════════════════════════════
# accuracy — triple_preservation_ratio (aggregate_mean, exclude Naive Union)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- accuracy ---"
DIM=accuracy
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric triple_preservation_ratio --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_triple_preservation_ratio.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Triple Preservation Ratio" "$DIM/work/$T/raw_triple_preservation_ratio.csv" \
      --exclude-method "Naive Union" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/tpr_var.csv" --pm-output "$DIM/tpr_pm.csv"
uv run python3 plot_variance.py \
    --input "$DIM/tpr_var.csv" --output "$DIM/tpr_var.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Triple Preservation Ratio" "Triple preservation ratio (avg over 4 datasets)" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# conciseness — syntactic_uniqueness_ratio (2 ds) + structural_redundancy (4 ds)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- conciseness ---"
DIM=conciseness
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric syntactic_uniqueness_ratio --datasets "${SUR_DATASETS[@]}" \
      --output "$DIM/work/$T/raw_syntactic_uniqueness_ratio.csv"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric structural_redundancy --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_structural_redundancy.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Syntactic Uniqueness Ratio" "$DIM/work/$T/raw_syntactic_uniqueness_ratio.csv" \
      --metric "Structural Redundancy" "$DIM/work/$T/raw_structural_redundancy.csv" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/conciseness_var.csv" --pm-output "$DIM/conciseness_pm.csv"
uv run python3 plot_variance.py \
    --input "$DIM/conciseness_var.csv" --output "$DIM/conciseness_var.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Syntactic Uniqueness Ratio" "Syntactic uniqueness ratio (avg)" \
    --ylabel-for "Structural Redundancy" "Structural redundancy (avg)" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# structural_coherence — cycle_count (aggregate_mean, all 4 ds).  NO chart in
# the original (raw per-dataset only) — for variance we still need ONE number
# per method to compare across turns, so we take the same mean-across-datasets
# aggregate_mean.py uses elsewhere, but only emit the pm TABLE (no _var.jpg).
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- structural_coherence ---"
DIM=structural_coherence
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric cycle_count --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_cycle_count.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Cycle Count" "$DIM/work/$T/raw_cycle_count.csv" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/cycle_count_var.csv" --pm-output "$DIM/cycle_count_pm.csv"
echo "(no chart for structural_coherence — mirrors the original's table-only output)"

# ═══════════════════════════════════════════════════════════════════════════
# knowledge_completeness — NCRC+NIRC (aggregate_mean, exclude Naive Union,
# log-scale plot) and TCC (aggregate_mean, exclude Naive Union)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- knowledge_completeness ---"
DIM=knowledge_completeness
mkdir -p "$DIM"
NCRC_INPUTS=(); TCC_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric new_cross_onto_relations_count --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_ncrc.csv"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric new_intra_onto_relations_count --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_nirc.csv"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric triple_count_delta --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_tcc.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "NCRC" "$DIM/work/$T/raw_ncrc.csv" \
      --metric "NIRC" "$DIM/work/$T/raw_nirc.csv" \
      --exclude-method "Naive Union" \
      --output "$DIM/work/$T/agg_ncrc_nirc.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Triples Count Change" "$DIM/work/$T/raw_tcc.csv" \
      --exclude-method "Naive Union" \
      --output "$DIM/work/$T/agg_tcc.csv"
  NCRC_INPUTS+=(--input "$DIM/work/$T/agg_ncrc_nirc.csv")
  TCC_INPUTS+=(--input "$DIM/work/$T/agg_tcc.csv")
done
uv run python3 combine_turns.py "${NCRC_INPUTS[@]}" \
    --output "$DIM/ncrc_nirc_var.csv" --pm-output "$DIM/ncrc_nirc_pm.csv"
uv run python3 plot_variance.py \
    --input "$DIM/ncrc_nirc_var.csv" --output "$DIM/ncrc_nirc_var.jpg" --n-turns "$N_CORE" \
    --ylabel-for "NCRC" "New cross-onto relations (avg, log)" \
    --ylabel-for "NIRC" "New intra-onto relations (avg, log)" \
    --log-for "NCRC" \
    --log-for "NIRC" \
    --bar-fmt "%.1f"
uv run python3 combine_turns.py "${TCC_INPUTS[@]}" \
    --output "$DIM/tcc_var.csv" --pm-output "$DIM/tcc_pm.csv"
uv run python3 plot_variance.py \
    --input "$DIM/tcc_var.csv" --output "$DIM/tcc_var.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Triples Count Change" "Triples count change (avg)" \
    --bar-fmt "%+.0f"

# ═══════════════════════════════════════════════════════════════════════════
# hierarchy_integration_quality — average_depth/ARC/average_breadth/max_breadth
# (aggregate_pct, exclude dataset swo-union-s2; max_depth dropped as in original)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- hierarchy_integration_quality ---"
DIM=hierarchy_integration_quality
mkdir -p "$DIM"
HIQ_METRICS=(ARC average_depth max_depth average_breadth max_breadth)
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  for METRIC in "${HIQ_METRICS[@]}"; do
    uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
        --metric "$METRIC" --datasets "${DATASETS[@]}" \
        --output "$DIM/work/$T/raw_${METRIC}.csv"
  done
  uv run python3 ../analiza/aggregate_pct.py \
      --metric average_depth "$DIM/work/$T/raw_average_depth.csv" \
      --metric ARC "$DIM/work/$T/raw_ARC.csv" \
      --metric average_breadth "$DIM/work/$T/raw_average_breadth.csv" \
      --metric max_breadth "$DIM/work/$T/raw_max_breadth.csv" \
      --exclude swo-union-s2 \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/hiq_pct_change_var.csv" --pm-output "$DIM/hiq_pct_change_pm.csv"
uv run python3 plot_variance.py \
    --input "$DIM/hiq_pct_change_var.csv" --output "$DIM/hiq_pct_change_var.jpg" --n-turns "$N_CORE"

# ═══════════════════════════════════════════════════════════════════════════
# understandability — comment_coverage_ratio (aggregate_mean, no excludes)
# (count_new_annotations.py sub-step skipped — not a variance chart)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- understandability ---"
DIM=understandability
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric comment_coverage_ratio --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_comment_coverage_ratio.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Comment Coverage Ratio" "$DIM/work/$T/raw_comment_coverage_ratio.csv" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/ccr_var.csv" --pm-output "$DIM/ccr_pm.csv"
uv run python3 plot_variance.py \
    --input "$DIM/ccr_var.csv" --output "$DIM/ccr_var.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Comment Coverage Ratio" "Comment coverage ratio (avg over 4 datasets)" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# domain_coherence (a) — non-OAEI: Applied Alignments %-change + Multi D/R mean
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- domain_coherence (non-OAEI) ---"
DIM=domain_coherence
mkdir -p "$DIM"
AA_INPUTS=(); MDR_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric applied_alignments --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_applied_alignments.csv"
  uv run python3 ../analiza/extract_metric.py --outputs-root "$OUTROOT/$T" \
      --metric multi_domain_range_change_per_alignment --datasets "${DR_DATASETS[@]}" \
      --output "$DIM/work/$T/raw_multi_dr.csv"
  uv run python3 ../analiza/aggregate_pct.py \
      --metric "Applied Alignments" "$DIM/work/$T/raw_applied_alignments.csv" \
      --baseline "Applied Alignments" \
      --exclude-method "Naive Union" \
      --exclude-method "Applied Alignments" \
      --output "$DIM/work/$T/agg_applied_alignments.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Multi D/R Change per Alignment" "$DIM/work/$T/raw_multi_dr.csv" \
      --exclude-method "Naive Union" \
      --exclude-method "Applied Alignments" \
      --output "$DIM/work/$T/agg_multi_dr.csv"
  AA_INPUTS+=(--input "$DIM/work/$T/agg_applied_alignments.csv")
  MDR_INPUTS+=(--input "$DIM/work/$T/agg_multi_dr.csv")
done
uv run python3 combine_turns.py "${AA_INPUTS[@]}" \
    --output "$DIM/applied_alignments_var.csv" --pm-output "$DIM/applied_alignments_pm.csv"
uv run python3 combine_turns.py "${MDR_INPUTS[@]}" \
    --output "$DIM/multi_dr_var.csv" --pm-output "$DIM/multi_dr_pm.csv"
# Combined chart (mirrors the original's merge_csvs.py → one plot_pct.py call).
uv run python3 ../analiza/merge_csvs.py \
    --input "$DIM/applied_alignments_var.csv" \
    --input "$DIM/multi_dr_var.csv" \
    --output "$DIM/domain_coherence_combined_var.csv"
uv run python3 plot_variance.py \
    --input "$DIM/domain_coherence_combined_var.csv" \
    --output "$DIM/domain_coherence_combined_var.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Applied Alignments" "% change vs Applied Alignments" \
    --ylabel-for "Multi D/R Change per Alignment" "Multi D/R Δ per alignment" \
    --bar-fmt-for "Applied Alignments" "%+.1f%%" \
    --bar-fmt-for "Multi D/R Change per Alignment" "%+.2f"

# ═══════════════════════════════════════════════════════════════════════════
# domain_coherence (b) — OAEI reference-alignment validation (adjusted)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- domain_coherence (OAEI validation) ---"
OAEI_DATASETS=(conference human-mouse confOf-ekaw)
mkdir -p "$DIM/work"
OAEI_PM_INPUTS=()
N_OAEI_TURNS=0
for T in "${TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  OAEI_ARGS=()
  for ds in "${OAEI_DATASETS[@]}"; do
    REF="../inputs/$ds/reference.rdf"
    INPUT_DIR="../inputs/$ds"
    S2_DIR="$OUTROOT/$T/${ds}-s2/${ds}-s2_${S2_TAG}"
    S3_DIR="$OUTROOT/$T/${ds}-s3/${ds}-s3_${S3_TAG}"
    if [ -f "$S2_DIR/applied_stats.json" ]; then
      OAEI_ARGS+=(--dataset "$ds" "$REF" "$S2_DIR" "$S3_DIR" "$INPUT_DIR")
    else
      echo "  [$T] skip OAEI dataset '$ds': $S2_DIR/applied_stats.json missing"
    fi
  done
  if [ ${#OAEI_ARGS[@]} -gt 0 ]; then
    uv run python3 ../analiza/domain_coherence/oaei_rejection.py \
        "${OAEI_ARGS[@]}" \
        --no-flag \
        --out-csv "$DIM/work/$T/oaei.csv" --out-jpg "$DIM/work/$T/oaei.jpg"
    OAEI_PM_INPUTS+=(--input "$DIM/work/$T/oaei.csv")
    N_OAEI_TURNS=$((N_OAEI_TURNS + 1))
  else
    echo "  [$T] no OAEI datasets available for this turn — skipped for OAEI variance."
  fi
done
if [ "$N_OAEI_TURNS" -gt 0 ]; then
  uv run python3 combine_oaei.py "${OAEI_PM_INPUTS[@]}" \
      --pm-output "$DIM/adjusted_oaei_rejection_pm.csv" \
      --jpg-output "$DIM/adjusted_oaei_rejection_var.jpg" \
      --n-turns "$N_OAEI_TURNS"
else
  echo "  OAEI variance skipped entirely — no turn had any OAEI dataset data."
fi

echo
echo "=== Done. Variance outputs under tests/analiza-variance/<dim>/ ==="
