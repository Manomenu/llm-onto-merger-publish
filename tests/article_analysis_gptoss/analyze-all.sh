#!/usr/bin/env bash
# Repeated-runs analysis for the default-backend pipeline (gpt-oss-20b) —
# the gpt-oss counterpart of tests/article_analysis_deepseek/: same dataset
# lists, same dimensions, same MEDIAN [min; max] statistic (bar height =
# median; min and max marked on every bar), reusing that folder's
# combine_turns.py / plot_turns.py / plot_grouped.py / oaei_to_agg.py helpers.
#
# DATA REUSE (checked in this order, per turn × dataset):
#   1. tests/scenarios/outputs/<turn>/<name>-s2|-s3/ — the tests/analiza-variance
#      run tree (scenario_2/scenario_3 --label <turn>).  Already-computed
#      variance data is NEVER recomputed.
#   2. tests/article_scenarios/outputs/<turn>/s2|s3/<label>/ — data produced
#      by this folder's own backfill.
#   3. Fallback: run tests/article_scenarios/s2.sh / s3.sh --label <turn>
#      --only <dataset> (slow — invokes the default-backend LLM merger) —
#      UNLESS --no-run is given, in which case the turn (or just the affected
#      dataset) is skipped instead.
#
# Dataset lists (display labels, same as article_analysis_deepseek).  All three
# carry a reference.rdf, so the same set is used everywhere (cmt-edas was
# dropped):
#   s2 / core (all non-OAEI dims):   confOf-ekaw human-mouse swo-acm
#   s3 (reference-input):            confOf-ekaw human-mouse swo-acm
#   OAEI validation:                 confOf-ekaw human-mouse swo-acm — each has
#     both an AML-input (s2) and reference-input (s3) run, which oaei_rejection.py
#     requires (applied_stats.json) for the accepted-AML-FP measure.
#
# Usage:
#   bash analyze-all.sh                       # turns = turn1..turn5 (default)
#   bash analyze-all.sh turn1 turn2           # explicit turn list
#   bash analyze-all.sh --no-run              # never invoke s2.sh/s3.sh
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
  TURNS=(turn1 turn2 turn3 turn4 turn5)
fi

echo "=== gpt-oss repeated-runs analysis over turns: ${TURNS[*]} (no-run=$NO_RUN) ==="

SCEN_OUT="../scenarios/outputs"          # analiza-variance run tree (primary)
ART_OUT="../article_scenarios/outputs"   # own backfill tree (secondary)
HELPERS="../article_analysis_deepseek"   # combine_turns.py / plot_turns.py / plot_grouped.py / oaei_to_agg.py

# Display labels, same as article_analysis_deepseek.
CORE_DATASETS=(confOf-ekaw human-mouse swo-acm)
S3_DATASETS=(confOf-ekaw human-mouse swo-acm)  # reference-input runs (same 3)

DATASETS=("${CORE_DATASETS[@]}")

# Output-dir tags: scenario_2/3 and s2.sh/s3.sh share the same scheme.
S2_TAG="aml_15k_p24"
S3_TAG="ref_15k_p24"

_legacy_names() {  # display label -> candidate legacy dataset basenames
  # For the current 3 datasets the display label == the variance-tree basename.
  echo "$1"
}

_input_for() {  # display label -> tests/inputs folder name
  echo "$1"
}

_s2_report() {  # turn, display label -> prints resolved m_i_raport CSV path
  local n
  for n in $(_legacy_names "$2"); do
    if [ -f "$SCEN_OUT/$1/${n}-s2/m_i_raport_${n}-s2.csv" ]; then
      echo "$SCEN_OUT/$1/${n}-s2/m_i_raport_${n}-s2.csv"
      return 0
    fi
  done
  if [ -f "$ART_OUT/$1/s2/$2/m_i_raport_$2.csv" ]; then
    echo "$ART_OUT/$1/s2/$2/m_i_raport_$2.csv"
    return 0
  fi
  return 1
}

_s2_dir() {  # turn, display label -> prints resolved s2 run dir (for OAEI)
  local n d
  for n in $(_legacy_names "$2"); do
    d="$SCEN_OUT/$1/${n}-s2/${n}-s2_${S2_TAG}"
    if [ -f "$d/applied_stats.json" ]; then
      echo "$d"
      return 0
    fi
  done
  d="$ART_OUT/$1/s2/$2/${2}_${S2_TAG}"
  if [ -f "$d/applied_stats.json" ]; then
    echo "$d"
    return 0
  fi
  return 1
}

_s3_dir() {  # turn, display label -> prints resolved s3 run dir (for OAEI)
  local n d
  for n in $(_legacy_names "$2"); do
    d="$SCEN_OUT/$1/${n}-s3/${n}-s3_${S3_TAG}"
    if [ -f "$d/alignment_stats.json" ] || [ -f "$d/arom_ontology.owl" ]; then
      echo "$d"
      return 0
    fi
  done
  d="$ART_OUT/$1/s3/$2/${2}_${S3_TAG}"
  if [ -f "$d/alignment_stats.json" ] || [ -f "$d/arom_ontology.owl" ]; then
    echo "$d"
    return 0
  fi
  return 1
}

# ── Granular backfill: look INSIDE the dataset dir and run only what's missing.
# Applies to the article tree (the only tree we ever write to; the variance
# tree is read-only for this analysis).  The report CSV is written last, so
# its absence says nothing about how far the run got — never re-pay the LLM
# cost when merged_ontology.owl already exists.
_baselines_complete() {  # run dir — all four baseline outputs copied in
  [ -f "$1/applied_alignments.owl" ] && [ -f "$1/boomer_ontology.owl" ] \
    && [ -f "$1/arom_ontology.owl" ] && [ -f "$1/comerger_ontology.owl" ]
}

_backfill() {  # scenario (s2|s3), turn, display label
  local scen="$1" T="$2" ds="$3" tag out
  case "$scen" in
    s2) tag="$S2_TAG" ;;
    s3) tag="$S3_TAG" ;;
  esac
  out="$ART_OUT/$T/$scen/$ds/${ds}_${tag}"
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

# ── Per-turn existence check + auto-run fallback (guarded by --no-run) ──────
for T in "${TURNS[@]}"; do
  for ds in "${CORE_DATASETS[@]}"; do
    if ! _s2_report "$T" "$ds" >/dev/null; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: no s2 data for '$ds' (variance tree nor article tree) and --no-run is set — skipping where needed."
      else
        _backfill s2 "$T" "$ds"
      fi
    fi
  done
  for ds in "${S3_DATASETS[@]}"; do
    if ! _s3_dir "$T" "$ds" >/dev/null; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: no s3 data for '$ds' (variance tree nor article tree) and --no-run is set — skipping where needed."
      else
        _backfill s3 "$T" "$ds"
      fi
    else
      # s3 dir exists but may lack the baseline-method outputs (then OAEI
      # rejected_correct stays blank for those methods).  Only ever backfill
      # the ARTICLE-tree dir that already has the LLM output — never a
      # variance-tree resolution (a full re-run there would cost LLM calls).
      d="$(_s3_dir "$T" "$ds")"
      art_d="$ART_OUT/$T/s3/$ds/${ds}_${S3_TAG}"
      if [ "$d" = "$art_d" ] && [ -f "$d/merged_ontology.owl" ] \
         && ! { [ -f "$d/applied_alignments.owl" ] && [ -f "$d/boomer_ontology.owl" ] \
                && [ -f "$d/arom_ontology.owl" ] \
                && { [ -f "$d/comerger_ontology.owl" ] || [ -f "$d/comerger_timeout.txt" ]; }; }; then
        if [ "$NO_RUN" = "1" ]; then
          echo "  [$T] WARNING: s3/$ds baselines incomplete and --no-run set — OAEI rejected_correct stays blank for baseline methods."
        else
          _backfill s3 "$T" "$ds"
        fi
      fi
    fi
  done
done

# ── Active turns for the "core" dimensions (need AT LEAST ONE core dataset's
# s2 data).  A turn missing data for only SOME datasets (e.g. a run that is
# still in flight for one dataset) is still included: extract_metric.py /
# aggregate_mean.py treat a missing (turn, dataset) cell as NaN and drop it
# from that cell's own aggregate (see combine_turns.py's NaN-skip), so the
# turn's OTHER, complete datasets are not penalised by dropping the whole
# turn from every aggregate.
CORE_TURNS=()
for T in "${TURNS[@]}"; do
  any=0
  for ds in "${CORE_DATASETS[@]}"; do
    if _s2_report "$T" "$ds" >/dev/null; then
      any=1
    else
      echo "  WARNING: [$T] no s2 data for '$ds' — that cell will be blank in aggregates (this turn's other datasets are unaffected)."
    fi
  done
  if [ "$any" = "1" ]; then
    CORE_TURNS+=("$T")
  else
    echo "  WARNING: turn '$T' has NO core s2 data for any dataset — excluded entirely."
  fi
done

if [ ${#CORE_TURNS[@]} -eq 0 ]; then
  echo "ERROR: no turn has any core s2 data — nothing to aggregate. Re-run without --no-run, or check $SCEN_OUT / $ART_OUT." >&2
  exit 1
fi
echo "Core turns (>=1 core dataset present): ${CORE_TURNS[*]}"
N_CORE=${#CORE_TURNS[@]}

# ── Per-dataset grouped charts (NO averaging over datasets) ─────────────────
# At n=5 turns averaging datasets away hides the per-dataset story, so every
# dimension now produces ONE figure per metric with the datasets shown as
# coloured series (x = method), min/max whiskers across turns.
#
# _grouped <dim> <base> <agg_fn> <plot-args...>
#   For each dataset it calls <agg_fn> <turn> <dataset> <out.csv> per turn
#   (the caller's aggregation, restricted to that one dataset via --only),
#   combines the turns, then draws all datasets as series in one JPG at
#   <dim>/<base>.jpg.  Per-dataset intermediate CSVs live under <dim>/work/.
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
    uv run python3 "$HELPERS/combine_turns.py" "${DS_INPUTS[@]}" \
        --output "$dim/work/${base}_${ds}.csv" \
        --pm-output "$dim/work/${base}_pm_${ds}.csv"
    PLOT_DS+=(--dataset "$ds" "$dim/work/${base}_${ds}.csv")
  done
  uv run python3 "$HELPERS/plot_grouped.py" "${PLOT_DS[@]}" \
      --output "$dim/${base}.jpg" --n-turns "$N_CORE" "${plot_args[@]}"
}

# ── Unified per-turn source view ─────────────────────────────────────────────
# extract_metric.py expects <root>/<dataset>/m_i_raport_<dataset>.csv with one
# consistent dataset naming — but a turn's reports may live in the variance
# tree (legacy '<name>-s2' naming) or the article tree ('<label>' naming).
# Copy every resolved report into work/source/<turn>/<label>/ under the
# display-label name so extraction reads one uniform tree per turn.
echo
echo "--- building per-turn source view (work/source/<turn>/) ---"
for T in "${CORE_TURNS[@]}"; do
  for ds in "${DATASETS[@]}"; do
    if SRC="$(_s2_report "$T" "$ds")"; then
      mkdir -p "work/source/$T/$ds"
      cp -f "$SRC" "work/source/$T/$ds/m_i_raport_${ds}.csv"
      echo "  [$T/$ds] ← $SRC"
    else
      echo "  [$T/$ds] no s2 report — skipped (cell stays blank in aggregates)"
    fi
  done
done

# ── CoMerger 3-min timeout detection ─────────────────────────────────────────
# comerger.sh caps the holistic merge at 3 min (Pellet RBox automaton blow-up
# on SWO & co.) and drops a comerger_timeout.txt marker in the run dir instead
# of a merged ontology.  Collect every dataset that hit the cap so we can (a)
# annotate the aggregate charts/tables via COMERGER_TIMEOUT_NOTE and (b) write
# an errors.txt note in this folder (overwritten every run).  CoMerger's value
# is simply absent for such datasets, so the mean-over-datasets aggregators
# already drop them — this only makes the omission explicit.
echo
echo "--- CoMerger timeout check ---"
TIMEOUT_DS=()
_note_timeout() {  # dataset — record once
  local ds="$1"
  case " ${TIMEOUT_DS[*]-} " in *" $ds "*) ;; *) TIMEOUT_DS+=("$ds") ;; esac
}
for T in "${CORE_TURNS[@]}"; do
  for ds in "${DATASETS[@]}"; do
    if d="$(_s2_dir "$T" "$ds" 2>/dev/null)" && [ -f "$d/comerger_timeout.txt" ]; then
      _note_timeout "$ds"
    fi
  done
done
for T in "${TURNS[@]}"; do
  for ds in "${S3_DATASETS[@]}"; do
    if d="$(_s3_dir "$T" "$ds" 2>/dev/null)" && [ -f "$d/comerger_timeout.txt" ]; then
      _note_timeout "$ds"
    fi
  done
done

ERRORS_FILE="errors.txt"
rm -f "$ERRORS_FILE"          # overwritten every run — reflects THIS run only
unset COMERGER_TIMEOUT_NOTE
if [ ${#TIMEOUT_DS[@]} -gt 0 ]; then
  : > "$ERRORS_FILE"
  for ds in "${TIMEOUT_DS[@]}"; do
    echo "$ds: no CoMerger data, due to 3-minute timeout" >> "$ERRORS_FILE"
  done
  export COMERGER_TIMEOUT_NOTE="CoMerger: no data (3-min timeout) for: ${TIMEOUT_DS[*]}."
  echo "  CoMerger timeout for: ${TIMEOUT_DS[*]}"
  echo "  → wrote $(pwd)/$ERRORS_FILE; aggregate charts/tables will be annotated."
else
  echo "  (no CoMerger timeouts detected)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# accuracy — triple_preservation_ratio (aggregate_mean, exclude Naive Union)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- accuracy ---"
DIM=accuracy
mkdir -p "$DIM"
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric triple_preservation_ratio --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_triple_preservation_ratio.csv"
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
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric syntactic_uniqueness_ratio --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_syntactic_uniqueness_ratio.csv"
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric structural_redundancy --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_structural_redundancy.csv"
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
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric cycle_count --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_cycle_count.csv"
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
  uv run python3 "$HELPERS/combine_turns.py" "${CC_INPUTS[@]}" \
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
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric new_cross_onto_relations_count --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_ncrc.csv"
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric new_intra_onto_relations_count --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_nirc.csv"
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric triple_count_delta --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_tcc.csv"
done
# Absolute counts → wildly different magnitudes across datasets (human-mouse
# ~1300 vs confOf ~15), so these charts use a symlog Y so every dataset's bar
# stays visible (per-dataset, not averaged).
_agg_ncrc_nirc() {  # turn, only-dataset, out
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "NCRC" "$DIM/work/$1/raw_ncrc.csv" \
      --metric "NIRC" "$DIM/work/$1/raw_nirc.csv" \
      --exclude-method "Naive Union" --only "$2" --output "$3"
}
_grouped "$DIM" ncrc_nirc_med _agg_ncrc_nirc \
    --ylabel-for "NCRC" "New cross-onto relations (log)" \
    --ylabel-for "NIRC" "New intra-onto relations (log)" \
    --log-for "NCRC" --log-for "NIRC" --bar-fmt "%.0f"
_agg_tcc() {  # turn, only-dataset, out
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Triples Count Change" "$DIM/work/$1/raw_tcc.csv" \
      --exclude-method "Naive Union" --only "$2" --output "$3"
}
_grouped "$DIM" tcc_med _agg_tcc \
    --ylabel-for "Triples Count Change" "Triples count change (symlog)" \
    --log-for "Triples Count Change" --bar-fmt "%+.0f"

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
    uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
        --metric "$METRIC" --datasets "${DATASETS[@]}" \
        --output "$DIM/work/$T/raw_${METRIC}.csv"
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
# average_depth and ARC span very different %-changes across datasets (small
# values vanish next to large ones on a shared linear axis) → symlog Y.
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
  uv run python3 ../analiza/extract_metric.py --outputs-root "work/source/$T" --skip-missing \
      --metric comment_coverage_ratio --datasets "${DATASETS[@]}" \
      --output "$DIM/work/$T/raw_comment_coverage_ratio.csv"
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
# domain_coherence — OAEI reference-alignment validation (adjusted): needs
# both the s2 (AML-input) and s3 (reference-input) run of each dataset; all
# three datasets now have both, so all three are validated.  The applied-
# alignments %-change measure was dropped from the paper (symmetric count,
# superseded by these ground-truth OAEI measures — Multi D/R was dropped
# earlier for the same reason), so the OAEI validation is domain_coherence's
# only measure now, restyled to the same _grouped house style as every other
# dimension: per-dataset pm CSVs + ONE grouped JPG with datasets as series.
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- domain_coherence (OAEI validation) ---"
DIM=domain_coherence
mkdir -p "$DIM/work"
OAEI_DATASETS=(confOf-ekaw human-mouse swo-acm)
for T in "${TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  OAEI_ARGS=()
  for ds in "${OAEI_DATASETS[@]}"; do
    INPUT_NAME="$(_input_for "$ds")"
    REF="../inputs/$INPUT_NAME/reference.rdf"
    INPUT_DIR="../inputs/$INPUT_NAME"
    if S2_DIR="$(_s2_dir "$T" "$ds")"; then
      S3_DIR="$(_s3_dir "$T" "$ds" || true)"
      OAEI_ARGS+=(--dataset "$ds" "$REF" "$S2_DIR" "${S3_DIR:-/nonexistent}" "$INPUT_DIR")
    else
      echo "  [$T] skip OAEI dataset '$ds': no s2 run dir with applied_stats.json"
    fi
  done
  if [ ${#OAEI_ARGS[@]} -gt 0 ]; then
    uv run python3 ../analiza/domain_coherence/oaei_rejection.py \
        "${OAEI_ARGS[@]}" \
        --no-flag \
        --out-csv "$DIM/work/$T/oaei.csv" --out-jpg "$DIM/work/$T/oaei.jpg"
  else
    echo "  [$T] no OAEI datasets available for this turn — skipped for OAEI aggregation."
  fi
done
# _grouped (see above) reuses CORE_TURNS/DATASETS — a turn/dataset cell with no
# oaei.csv (or no row for that dataset) yields an empty per-turn agg CSV from
# oaei_to_agg.py, which combine_turns.py's NaN-skip already treats as "no data
# for that turn" without dropping the rest.
_agg_oaei() {  # turn, only-dataset, out
  uv run python3 "$HELPERS/oaei_to_agg.py" \
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

echo
echo "=== Done. Median/min/max outputs under tests/article_analysis_gptoss/<dim>/ ==="
