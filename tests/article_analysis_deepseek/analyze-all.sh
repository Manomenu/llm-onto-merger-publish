#!/usr/bin/env bash
# Combined two-backend repeated-runs analysis — every chart/table from
# tests/article_analysis_gptoss/ EXTENDED with one extra method column:
#   ... AROM, CoMerger, Boomer, Proposed: gpt-oss, Proposed: deepseek-v4-flash
# reporting MEDIAN with MIN/MAX whiskers (bar height = median; min and max
# are marked on every bar; tables show "median [min; max]").
#
# DATA REUSE: everything that article_analysis_gptoss already resolves is
# taken from it, never recomputed here.  Step 0 delegates to
# ../article_analysis_gptoss/analyze-all.sh (same turns, --no-run passed
# through), which resolves the gpt-oss data (tests/analiza-variance tree
# first, own backfill second) and leaves:
#   - per-turn report views under article_analysis_gptoss/work/source/<turn>/
#     → source of the baseline columns + "Proposed: gpt-oss"
#   - per-turn OAEI CSVs under article_analysis_gptoss/domain_coherence/work/
# This folder only ADDS the deepseek side: per turn it ensures the s5
# (AML-input) / s6 (reference-input) OpenRouter deepseek-v4-flash runs exist
# under tests/article_scenarios/outputs/<turn>/ (granular backfill via
# s5.sh/s6.sh --label <turn> --only <dataset>), then aggregates the combined
# columns.
#
# Dataset lists (display labels).  All three carry a reference.rdf, so the same
# set is used everywhere (swo-union and cmt-edas were dropped):
#   s5 / core (all non-OAEI dims):   confOf-ekaw human-mouse swo-acm
#   s6 (reference-input):            confOf-ekaw human-mouse swo-acm
#   OAEI validation:                 confOf-ekaw human-mouse swo-acm — each has
#     both an AML-input (s5) and reference-input (s6) run, which oaei_rejection.py
#     requires (applied_stats.json) for the accepted-AML-FP measure.
#
# Usage:
#   bash analyze-all.sh                       # turns = turn1 turn2 turn3 (default)
#   bash analyze-all.sh turn1 turn2           # explicit turn list
#   bash analyze-all.sh --no-run              # never invoke any scenario script —
#                                              # turns with missing data are
#                                              # skipped (with a warning)
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
else
  TURNS=(turn1 turn2 turn3)
fi

echo "=== combined gpt-oss + deepseek repeated-runs analysis over turns: ${TURNS[*]} (no-run=$NO_RUN) ==="

OUTROOT="../article_scenarios/outputs"   # deepseek s5/s6 runs
GPTOSS="../article_analysis_gptoss"      # gpt-oss side (resolved data + OAEI CSVs)

# ── Step 0: gpt-oss side — delegate entirely to article_analysis_gptoss ─────
echo
echo "--- [0] gpt-oss side (delegated to $GPTOSS/analyze-all.sh) ---"
if [ "$NO_RUN" = "1" ]; then
  bash "$GPTOSS/analyze-all.sh" --no-run "${TURNS[@]}"
else
  bash "$GPTOSS/analyze-all.sh" "${TURNS[@]}"
fi

# Display labels as produced by s5.sh / s6.sh.
CORE_DATASETS=(confOf-ekaw human-mouse swo-acm)
S6_DATASETS=(confOf-ekaw human-mouse swo-acm)  # reference-input runs (same 3)
# Execution order for the backfill runs ONLY (cheapest first, human-mouse — the
# expensive one, ~95% of the API cost — LAST, so early failures cost pennies).
# Aggregation/chart series order stays CORE_DATASETS for consistency with the
# gpt-oss figures.
RUN_ORDER=(confOf-ekaw swo-acm human-mouse)

DATASETS=("${CORE_DATASETS[@]}")

# Output-dir tags as computed by s5.sh/s6.sh with default flags
# (limit 15000, parallel 1000, model deepseek/deepseek-v4-flash).
MODEL_TAG="deepseek_deepseek-v4-flash"
S5_TAG="aml_15000c_p1000_${MODEL_TAG}"
S6_TAG="ref_15000c_p1000_${MODEL_TAG}"

_s5_report_exists() {  # turn, display label
  [ -f "$OUTROOT/$1/s5/$2/m_i_raport_$2.csv" ]
}

_s6_report_exists() {  # turn, display label
  [ -f "$OUTROOT/$1/s6/$2/m_i_raport_$2.csv" ]
}

_gptoss_view_exists() {  # turn, display label — step 0 built this view
  [ -f "$GPTOSS/work/source/$1/$2/m_i_raport_$2.csv" ]
}

_input_for() {  # display label -> tests/inputs folder name
  echo "$1"
}

# ── Granular backfill: look INSIDE the dataset dir and run only what's missing.
# The report CSV is written last, so its absence says nothing about how far the
# run got — never re-pay the LLM cost when merged_ontology.owl already exists.
_baselines_complete() {  # run dir — all four baseline outputs copied in
  [ -f "$1/applied_alignments.owl" ] && [ -f "$1/boomer_ontology.owl" ] \
    && [ -f "$1/arom_ontology.owl" ] && [ -f "$1/comerger_ontology.owl" ]
}

_backfill() {  # scenario (s5|s6), turn, display label
  local scen="$1" T="$2" ds="$3" tag out
  case "$scen" in
    s5) tag="$S5_TAG" ;;
    s6) tag="$S6_TAG" ;;
  esac
  out="$OUTROOT/$T/$scen/$ds/${ds}_${tag}"
  if [ -f "$out/merged_ontology.owl" ]; then
    if _baselines_complete "$out"; then
      echo "  [$T] $scen/$ds: LLM output + baselines present, report missing — regenerating report only"
      "../article_scenarios/$scen.sh" --label "$T" --only "$ds" --skip-all
    else
      echo "  [$T] $scen/$ds: LLM output present, baselines incomplete — rerunning baselines + report (LLM skipped)"
      "../article_scenarios/$scen.sh" --label "$T" --only "$ds" --skip-mine
    fi
  else
    echo "  [$T] $scen/$ds: no LLM output — full run"
    "../article_scenarios/$scen.sh" --label "$T" --only "$ds"
  fi
}

# ── Step 1: deepseek side — per-turn existence check + auto-run backfill ────
echo
echo "--- [1] deepseek side (s5/s6 runs under $OUTROOT/<turn>/) ---"
for T in "${TURNS[@]}"; do
  # One dataset fully (s5 then s6) before the next, so the expensive
  # human-mouse pair runs entirely last and any pipeline problem surfaces
  # on the cheap datasets first.
  for ds in "${RUN_ORDER[@]}"; do
    if ! _s5_report_exists "$T" "$ds"; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: missing deepseek s5 report for '$ds' and --no-run is set — skipping where needed."
      else
        _backfill s5 "$T" "$ds"
      fi
    fi
    if ! _s6_report_exists "$T" "$ds"; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: missing deepseek s6 report for '$ds' and --no-run is set — skipping where needed."
      else
        _backfill s6 "$T" "$ds"
      fi
    fi
  done
done

# ── Active turns for the "core" dimensions: each needs BOTH sides complete
# for all 3 core datasets (gpt-oss view from step 0 + deepseek s5 report). ──
CORE_TURNS=()
for T in "${TURNS[@]}"; do
  ok=1
  for ds in "${CORE_DATASETS[@]}"; do
    { _gptoss_view_exists "$T" "$ds" && _s5_report_exists "$T" "$ds"; } || ok=0
  done
  if [ "$ok" = "1" ]; then
    CORE_TURNS+=("$T")
  else
    echo "  WARNING: turn '$T' is missing core (3-dataset) gpt-oss and/or deepseek data — excluded from all core-dimension aggregates."
  fi
done

if [ ${#CORE_TURNS[@]} -eq 0 ]; then
  echo "ERROR: no turn has complete core data on both sides — nothing to aggregate. Re-run without --no-run, or check $GPTOSS/work/source and $OUTROOT." >&2
  exit 1
fi
echo "Core turns (both sides complete): ${CORE_TURNS[*]}"
N_CORE=${#CORE_TURNS[@]}

# ── CoMerger timeout note ───────────────────────────────────────────────────
# article_analysis_gptoss/analyze-all.sh computes this too, but step 0 invokes
# it via `bash` — a separate process — so its `export` never reaches us.  Left
# unset, plot_grouped.py renders CoMerger's missing bar as an indistinguishable
# zero-height bar with no disclaimer.  Recompute it here, in OUR process.
echo
echo "--- CoMerger timeout check ---"
TIMEOUT_DS=()
for ds in "${CORE_DATASETS[@]}"; do
  found=0
  for T in "${CORE_TURNS[@]}"; do
    for sc in s2 s3 s5 s6; do
      for f in "$OUTROOT/$T/$sc/$ds"/*/comerger_timeout.txt; do
        [ -f "$f" ] && { found=1; break 3; }
      done
    done
  done
  [ "$found" = "1" ] && TIMEOUT_DS+=("$ds")
done
unset COMERGER_TIMEOUT_NOTE
if [ ${#TIMEOUT_DS[@]} -gt 0 ]; then
  export COMERGER_TIMEOUT_NOTE="CoMerger: no data (3-min timeout) for: ${TIMEOUT_DS[*]}."
  echo "  ${COMERGER_TIMEOUT_NOTE}"
else
  echo "  none"
fi

# Shorthand: combined two-backend extraction for one turn.
_extract() {  # turn, metric, output csv, datasets...
  local T="$1" metric="$2" out="$3"
  shift 3
  uv run python3 extract_metric_combined.py \
      --gptoss-root "$GPTOSS/work/source/$T" \
      --deepseek-root "$OUTROOT/$T/s5" \
      --metric "$metric" --datasets "$@" \
      --output "$out"
}

# ── Per-dataset grouped charts (NO averaging over datasets) ─────────────────
# One figure per metric with datasets as coloured series (x = method), min/max
# whiskers across turns — see article_analysis_gptoss/analyze-all.sh.
# _grouped <dim> <base> <agg_fn> <plot-args...>: <agg_fn> <turn> <dataset> <out>
# produces that dataset's aggregation (via --only); results are combined across
# turns and drawn as series in <dim>/<base>.jpg.
_grouped() {
  local dim="$1" base="$2" aggfn="$3"; shift 3
  local plot_args=("$@")
  local PLOT_DS=() ds T DS_INPUTS
  for ds in "${DATASETS[@]}"; do
    DS_INPUTS=()
    for T in "${CORE_TURNS[@]}"; do
      mkdir -p "$dim/work/$T"
      "$aggfn" "$T" "$ds" "$dim/work/$T/${base}_agg_${ds}.csv"
      DS_INPUTS+=(--input "$dim/work/$T/${base}_agg_${ds}.csv")
    done
    uv run python3 combine_turns.py "${DS_INPUTS[@]}" \
        --output "$dim/work/${base}_${ds}.csv" \
        --pm-output "$dim/work/${base}_pm_${ds}.csv"
    PLOT_DS+=(--dataset "$ds" "$dim/work/${base}_${ds}.csv")
  done
  uv run python3 plot_grouped.py "${PLOT_DS[@]}" \
      --output "$dim/${base}.jpg" --n-turns "$N_CORE" "${plot_args[@]}"
}

# ═══════════════════════════════════════════════════════════════════════════
# accuracy — triple_preservation_ratio (aggregate_mean, exclude Naive Union)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- accuracy ---"
DIM=accuracy
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" triple_preservation_ratio \
      "$DIM/work/$T/raw_triple_preservation_ratio.csv" "${DATASETS[@]}"
done
_agg_accuracy() {  # turn, only-dataset, out
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Triple Preservation Ratio" "$DIM/work/$1/raw_triple_preservation_ratio.csv" \
      --exclude-method "Naive Union" --only "$2" --output "$3"
}
_grouped "$DIM" tpr_med _agg_accuracy \
    --ylabel-for "Triple Preservation Ratio" "Triple preservation ratio" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# conciseness — syntactic_uniqueness_ratio (2 ds) + structural_redundancy (4 ds)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- conciseness ---"
DIM=conciseness
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" syntactic_uniqueness_ratio \
      "$DIM/work/$T/raw_syntactic_uniqueness_ratio.csv" "${DATASETS[@]}"
  _extract "$T" structural_redundancy \
      "$DIM/work/$T/raw_structural_redundancy.csv" "${DATASETS[@]}"
done
_agg_conciseness() {  # turn, only-dataset, out
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Syntactic Uniqueness Ratio" "$DIM/work/$1/raw_syntactic_uniqueness_ratio.csv" \
      --metric "Structural Redundancy" "$DIM/work/$1/raw_structural_redundancy.csv" \
      --only "$2" --output "$3"
}
_grouped "$DIM" conciseness_med _agg_conciseness \
    --ylabel-for "Syntactic Uniqueness Ratio" "Syntactic uniqueness ratio" \
    --ylabel-for "Structural Redundancy" "Structural redundancy" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# structural_coherence — cycle_count (aggregate_mean, all 3 ds).  Table only —
# mirrors tests/analiza-variance (the original has no chart for this metric).
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- structural_coherence ---"
DIM=structural_coherence
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" cycle_count "$DIM/work/$T/raw_cycle_count.csv" "${DATASETS[@]}"
done
# Table only (no chart, as in the original) — but per dataset, not averaged.
for ds in "${DATASETS[@]}"; do
  CC_INPUTS=()
  for T in "${CORE_TURNS[@]}"; do
    uv run python3 ../analiza/aggregate_mean.py \
        --metric "Cycle Count" "$DIM/work/$T/raw_cycle_count.csv" \
        --only "$ds" --output "$DIM/work/$T/cc_agg_${ds}.csv"
    CC_INPUTS+=(--input "$DIM/work/$T/cc_agg_${ds}.csv")
  done
  uv run python3 combine_turns.py "${CC_INPUTS[@]}" \
      --output "$DIM/work/cycle_count_med_${ds}.csv" \
      --pm-output "$DIM/cycle_count_pm_${ds}.csv"
done
echo "(no chart for structural_coherence — per-dataset table only)"

# ═══════════════════════════════════════════════════════════════════════════
# knowledge_completeness — NCRC+NIRC (aggregate_mean, exclude Naive Union,
# log-scale plot) and TCC (aggregate_mean, exclude Naive Union)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- knowledge_completeness ---"
DIM=knowledge_completeness
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" new_cross_onto_relations_count "$DIM/work/$T/raw_ncrc.csv" "${DATASETS[@]}"
  _extract "$T" new_intra_onto_relations_count "$DIM/work/$T/raw_nirc.csv" "${DATASETS[@]}"
  _extract "$T" triple_count_delta "$DIM/work/$T/raw_tcc.csv" "${DATASETS[@]}"
done
# Absolute counts → symlog Y so every dataset stays visible (per-dataset).
# Chart: NCRC + NIRC (the emergent-relations headline), stacked vertically.
_agg_kc() {  # turn, only-dataset, out
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "NCRC" "$DIM/work/$1/raw_ncrc.csv" \
      --metric "NIRC" "$DIM/work/$1/raw_nirc.csv" \
      --exclude-method "Naive Union" --only "$2" --output "$3"
}
_grouped "$DIM" kc_med _agg_kc \
    --ylabel-for "NCRC" "New cross-onto relations (log)" \
    --ylabel-for "NIRC" "New intra-onto relations (log)" \
    --log-for "NCRC" --log-for "NIRC" --bar-fmt "%.0f"
# TCC — reported as numbers only (no chart); per-dataset median[min;max] table.
for ds in "${DATASETS[@]}"; do
  TCC_INPUTS=()
  for T in "${CORE_TURNS[@]}"; do
    uv run python3 ../analiza/aggregate_mean.py \
        --metric "Triples Count Change" "$DIM/work/$T/raw_tcc.csv" \
        --exclude-method "Naive Union" --only "$ds" --output "$DIM/work/$T/tcc_agg_${ds}.csv"
    TCC_INPUTS+=(--input "$DIM/work/$T/tcc_agg_${ds}.csv")
  done
  uv run python3 combine_turns.py "${TCC_INPUTS[@]}" \
      --output "$DIM/work/tcc_med_${ds}.csv" --pm-output "$DIM/tcc_pm_${ds}.csv"
done

# ═══════════════════════════════════════════════════════════════════════════
# hierarchy_integration_quality — average_depth/ARC/average_breadth/max_breadth
# (aggregate_pct over all datasets; max_depth dropped as in original)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- hierarchy_integration_quality ---"
DIM=hierarchy_integration_quality
mkdir -p "$DIM"
HIQ_METRICS=(ARC average_depth max_depth average_breadth max_breadth)
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  for METRIC in "${HIQ_METRICS[@]}"; do
    _extract "$T" "$METRIC" "$DIM/work/$T/raw_${METRIC}.csv" "${DATASETS[@]}"
  done
done
_agg_hiq() {  # turn, only-dataset, out — %-change vs Naive Union, that dataset only
  uv run python3 ../analiza/aggregate_pct.py \
      --metric average_depth "$DIM/work/$1/raw_average_depth.csv" \
      --metric ARC "$DIM/work/$1/raw_ARC.csv" \
      --metric average_breadth "$DIM/work/$1/raw_average_breadth.csv" \
      --metric max_breadth "$DIM/work/$1/raw_max_breadth.csv" \
      --only "$2" --output "$3"
}
# average_depth and ARC span very different %-changes across datasets → symlog Y.
_grouped "$DIM" hiq_pct_change_med _agg_hiq --bar-fmt "%+.1f" \
    --log-for average_depth --log-for ARC

# ═══════════════════════════════════════════════════════════════════════════
# understandability — comment_coverage_ratio (aggregate_mean, no excludes)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- understandability ---"
DIM=understandability
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" comment_coverage_ratio \
      "$DIM/work/$T/raw_comment_coverage_ratio.csv" "${DATASETS[@]}"
done
_agg_understand() {  # turn, only-dataset, out
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Comment Coverage Ratio" "$DIM/work/$1/raw_comment_coverage_ratio.csv" \
      --only "$2" --output "$3"
}
_grouped "$DIM" ccr_med _agg_understand \
    --ylabel-for "Comment Coverage Ratio" "Comment coverage ratio" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# domain_coherence (a) — non-OAEI: Multi D/R mean.  (The applied-alignments
# %-change measure was dropped from the paper — symmetric count, superseded
# by the ground-truth OAEI measures below — so this dimension now has one
# non-OAEI metric instead of two, and no longer needs merge_csvs.py to
# combine two per-(turn,dataset) aggregates into one.)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- domain_coherence (non-OAEI) ---"
DIM=domain_coherence
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" multi_domain_range_change_per_alignment \
      "$DIM/work/$T/raw_multi_dr.csv" "${DATASETS[@]}"
done
_agg_dc() {  # turn, only-dataset, out
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Multi D/R Change per Alignment" "$DIM/work/$1/raw_multi_dr.csv" \
      --exclude-method "Naive Union" --exclude-method "Applied Alignments" \
      --only "$2" --output "$3"
}
_grouped "$DIM" domain_coherence_combined_med _agg_dc \
    --ylabel-for "Multi D/R Change per Alignment" "Multi D/R Δ per alignment" \
    --bar-fmt-for "Multi D/R Change per Alignment" "%+.2f"

# ═══════════════════════════════════════════════════════════════════════════
# domain_coherence (b) — OAEI reference-alignment validation (adjusted).
# The gpt-oss per-turn CSV comes straight from article_analysis_gptoss's step-0
# run; only the deepseek run of oaei_rejection.py happens here, and
# merge_oaei_runs.py grafts its "Proposed" row in as the extra method column.
# All three datasets have both an AML-input (s5) and reference-input (s6) run.
# Restyled to the same _grouped house style as every other dimension: per-
# dataset pm CSVs + ONE grouped JPG with datasets as series.
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- domain_coherence (OAEI validation) ---"
OAEI_DATASETS=(confOf-ekaw human-mouse swo-acm)
mkdir -p "$DIM/work"
for T in "${TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  GPTOSS_OAEI="$GPTOSS/domain_coherence/work/$T/oaei.csv"
  if [ ! -f "$GPTOSS_OAEI" ]; then
    echo "  [$T] no gpt-oss OAEI CSV ($GPTOSS_OAEI) — turn skipped for OAEI aggregation."
    continue
  fi
  OAEI_ARGS=()
  for ds in "${OAEI_DATASETS[@]}"; do
    INPUT_NAME="$(_input_for "$ds")"
    REF="../inputs/$INPUT_NAME/reference.rdf"
    INPUT_DIR="../inputs/$INPUT_NAME"
    S5_DIR="$OUTROOT/$T/s5/$ds/${ds}_${S5_TAG}"
    S6_DIR="$OUTROOT/$T/s6/$ds/${ds}_${S6_TAG}"
    if [ -f "$S5_DIR/applied_stats.json" ]; then
      OAEI_ARGS+=(--dataset "$ds" "$REF" "$S5_DIR" "$S6_DIR" "$INPUT_DIR")
    else
      echo "  [$T] skip deepseek OAEI dataset '$ds': $S5_DIR/applied_stats.json missing"
    fi
  done
  if [ ${#OAEI_ARGS[@]} -gt 0 ]; then
    uv run python3 ../analiza/domain_coherence/oaei_rejection.py \
        "${OAEI_ARGS[@]}" \
        --no-flag \
        --out-csv "$DIM/work/$T/oaei_deepseek.csv" --out-jpg "$DIM/work/$T/oaei_deepseek.jpg"
    uv run python3 merge_oaei_runs.py \
        --gptoss "$GPTOSS_OAEI" --deepseek "$DIM/work/$T/oaei_deepseek.csv" \
        --output "$DIM/work/$T/oaei.csv"
  else
    echo "  [$T] no deepseek OAEI datasets available for this turn — skipped for OAEI aggregation."
  fi
done
# _grouped reuses CORE_TURNS/DATASETS — a turn/dataset cell with no oaei.csv
# (or no row for that dataset) yields an empty per-turn agg CSV from
# oaei_to_agg.py, which combine_turns.py's NaN-skip already treats as "no
# data for that turn" without dropping the rest.
_agg_oaei() {  # turn, only-dataset, out
  uv run python3 oaei_to_agg.py \
      --input "$DIM/work/$1/oaei.csv" --dataset "$2" --output "$3" \
      --totals-output "$DIM/work/oaei_totals_${2}.txt"
}
_grouped "$DIM" adjusted_oaei_rejection_med _agg_oaei \
    --title "Adjusted OAEI reference-alignment validation" \
    --ylabel-for "Rejected Correct" "Rejected correct alignments (log, lower = better)" \
    --ylabel-for "Accepted AML FP" "Accepted AML false-positives (log, lower = better)" \
    --log-for "Rejected Correct" --log-for "Accepted AML FP" \
    --vertical --bar-fmt "%.0f"
# Prepend the deterministic reference_total/aml_total note (written by
# oaei_to_agg.py) to each dataset's pm CSV, mirroring combine_turns.py's own
# '# NOTE:' comment convention (e.g. the CoMerger-timeout note).
for ds in "${OAEI_DATASETS[@]}"; do
  NOTE="$DIM/work/oaei_totals_${ds}.txt"
  PM="$DIM/work/adjusted_oaei_rejection_med_pm_${ds}.csv"
  if [ -f "$NOTE" ] && [ -f "$PM" ]; then
    cat "$NOTE" "$PM" > "$PM.tmp" && mv "$PM.tmp" "$PM"
    rm -f "$NOTE"
  fi
done


# ═══════════════════════════════════════════════════════════════════════════
# cost — DeepSeek-v4-flash USD cost per dataset, read from cost_stats.json in
# the s5 (AML-input) run dir ONLY — s6 (reference-input) runs are explicitly
# excluded per the author's decision. MEAN with min/max whiskers across turns
# — NOT median like every other dimension above — because the author wants
# the average spend, not the typical-run figure. No method dimension: only
# the proposed LLM method has a recorded cost (baselines are free/local).
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- cost ---"
DIM=cost
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 extract_cost.py \
      --s5-root "$OUTROOT/$T/s5" --tag "$S5_TAG" \
      --datasets "${CORE_DATASETS[@]}" \
      --output "$DIM/work/$T/raw_cost.csv"
done
COST_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  COST_INPUTS+=(--input "$DIM/work/$T/raw_cost.csv")
done
uv run python3 plot_cost.py "${COST_INPUTS[@]}" \
    --pm-output "$DIM/cost_pm.csv" --jpg-output "$DIM/cost.jpg"

echo
echo "=== Done. Combined median/min/max outputs under tests/article_analysis_deepseek/<dim>/ ==="
