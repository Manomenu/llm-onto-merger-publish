#!/bin/bash
# Domain Coherence analysis.
# Flags:
#   --fresh-s3          force a full re-run of scenario_3 (reference-input) for
#                       the OAEI datasets, even if outputs already exist.  Use
#                       after fixing the merge pipeline (alignment-orientation
#                       fix) to discard stale scenario_3 results.
#   --fresh-boomer-s3   re-run ONLY Boomer in scenario_3 (no LLM merger, no other
#                       baselines).  Cheap way to populate the missing
#                       boomer_stats.json for measure 1 without the long LLM run.
#   --ekaw-only         compute the OAEI validation scenarios (all methods, AML +
#                       reference runs) ONLY for the confOf-ekaw dataset; the other
#                       OAEI datasets reuse their existing outputs.  The adjusted
#                       chart is still drawn over all available OAEI datasets.
set -euo pipefail
cd "$(dirname "$0")"

FRESH_S3=0
FRESH_BOOMER_S3=0
EKAW_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --fresh-s3) FRESH_S3=1 ;;
    --fresh-boomer-s3) FRESH_BOOMER_S3=1 ;;
    --ekaw-only) EKAW_ONLY=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)
# For D/R metrics we only consider datasets with rdfs:domain/rdfs:range
# present on BOTH input sides (otherwise the metric is trivially 0 or measures
# unrelated LLM-hallucination, see acm-union with 0 D/R on acm.owl side).
DR_DATASETS=(conference-s2 swo-union-s2)

# 1. Raw per-metric CSVs
uv run python3 ../extract_metric.py \
    --metric applied_alignments \
    --datasets "${DATASETS[@]}" \
    --output applied_alignments.csv

uv run python3 ../extract_metric.py \
    --metric multi_domain_range_count \
    --datasets "${DR_DATASETS[@]}" \
    --output multi_domain_range_count.csv

uv run python3 ../extract_metric.py \
    --metric multi_domain_range_change_per_alignment \
    --datasets "${DR_DATASETS[@]}" \
    --output multi_domain_range_change_per_alignment.csv

# 2. Applied Alignments — % change vs Applied Alignments baseline
uv run python3 ../aggregate_pct.py \
    --metric "Applied Alignments" applied_alignments.csv \
    --baseline "Applied Alignments" \
    --exclude-method "Naive Union" \
    --exclude-method "Applied Alignments" \
    --output applied_alignments_pct_change.csv

# 3. Multi D/R Change per Alignment — średnia surowych wartości metryki
uv run python3 ../aggregate_mean.py \
    --metric "Multi D/R Change per Alignment" multi_domain_range_change_per_alignment.csv \
    --exclude-method "Naive Union" \
    --exclude-method "Applied Alignments" \
    --output multi_dr_change_per_alignment_mean.csv

# 4. Merge into one CSV → one chart, two subplots side by side
uv run python3 ../merge_csvs.py \
    --input applied_alignments_pct_change.csv \
    --input multi_dr_change_per_alignment_mean.csv \
    --output domain_coherence_combined.csv

uv run python3 ../plot_pct.py \
    --input domain_coherence_combined.csv \
    --output domain_coherence_combined.jpg \
    --ylabel-for "Applied Alignments" "% change vs Applied Alignments" \
    --ylabel-for "Multi D/R Change per Alignment" "Multi D/R Δ per alignment" \
    --bar-fmt-for "Applied Alignments" "%+.1f%%" \
    --bar-fmt-for "Multi D/R Change per Alignment" "%+.2f"

echo
echo "=== applied_alignments.csv (raw) ==="
cat applied_alignments.csv | column -t -s,
echo
echo "=== multi_domain_range_change_per_alignment.csv (raw) ==="
cat multi_domain_range_change_per_alignment.csv | column -t -s,
echo
echo "=== domain_coherence_combined.csv ==="
cat domain_coherence_combined.csv | column -t -s,

# 5. OAEI reference-alignment validation (Domain Coherence vs ground truth) — ADJUSTED.
#    Measure 1 (rejected correct, lower=better)        ← scenario_3 (reference input).
#    Measure 2 (accepted AML false-positives, lower=better) ← scenario_2 (AML input).
#    ADJUSTED: Boomer's reference ptable uses a REALISTIC p_equiv = the mean AML
#    confidence for that dataset (instead of hard 1.0) — no unfair certainty, and
#    the solver doesn't choke.  Self-provisioning: missing scenario outputs are
#    produced automatically.  --ekaw-only scopes that (expensive) compute to
#    confOf-ekaw; the chart is still drawn over all available OAEI datasets.
S2_TAG="aml_15k_p24"
S3_TAG="ref_15k_p24"
SCENARIOS_DIR="../../scenarios"

# OAEI datasets that have a reference alignment → one chart row each.
OAEI_ALL=(conference human-mouse confOf-ekaw)
if [ "$EKAW_ONLY" = "1" ]; then COMPUTE=(confOf-ekaw); else COMPUTE=("${OAEI_ALL[@]}"); fi

# Mean AML confidence for a dataset's two ontologies → realistic Boomer p_equiv.
aml_mean() {
  uv run python3 - "$1" "$2" <<'PY'
import asyncio, statistics, sys
from llm_onto_merger.alignment import AmlAlignmentModule
al = asyncio.run(AmlAlignmentModule().create_alignment(sys.argv[1], sys.argv[2]))
print(f"{statistics.mean([a.measure for a in al]):.4f}" if al else "0.95")
PY
}
in_list() { local x="$1"; shift; for e in "$@"; do [ "$e" = "$x" ] && return 0; done; return 1; }

OAEI_ARGS=()
for ds in "${OAEI_ALL[@]}"; do
  REF="../../inputs/$ds/reference.rdf"
  INPUT_DIR="../../inputs/$ds"
  S2_DIR="../../scenarios/outputs/${ds}-s2/${ds}-s2_${S2_TAG}"
  S3_DIR="../../scenarios/outputs/${ds}-s3/${ds}-s3_${S3_TAG}"
  [ -f "$REF" ] || { echo "  (skip '$ds': no reference.rdf)"; continue; }

  if in_list "$ds" "${COMPUTE[@]}"; then
    OWLS=( $(ls "$INPUT_DIR"/*.owl | sort) )
    BASE="${OWLS[0]}"; CAND="${OWLS[1]}"

    # scenario_2 (AML run): cheap --skip-all if a cache exists, else a full run.
    if [ ! -f "$S2_DIR/applied_stats.json" ]; then
      if [ -d "../../scenarios/outputs/${ds}-s2" ]; then
        echo "  → '$ds': scenario_2 sidecars missing — scenario_2.sh --skip-all"
        "$SCENARIOS_DIR/scenario_2.sh" --skip-all "$ds" || echo "  WARNING: scenario_2 --skip-all $ds failed"
      else
        echo "  → '$ds': no scenario_2 yet — full scenario_2.sh (LLM merger + baselines)"
        "$SCENARIOS_DIR/scenario_2.sh" "$ds" || echo "  WARNING: scenario_2 $ds failed"
      fi
    fi

    # scenario_3 (reference run).
    if [ "$FRESH_S3" = "1" ] || [ ! -f "$S3_DIR/alignment_stats.json" ]; then
      echo "  → '$ds': scenario_3.sh (reference run; LLM merger + baselines)"
      "$SCENARIOS_DIR/scenario_3.sh" "$ds" || echo "  WARNING: scenario_3 $ds failed"
    fi

    # Adjusted Boomer: (re)run Boomer in scenario_3 with realistic mean-AML p_equiv
    # when its s3 stats are missing or a Boomer/full refresh was requested.
    if [ "$FRESH_S3" = "1" ] || [ "$FRESH_BOOMER_S3" = "1" ] || [ ! -f "$S3_DIR/boomer_stats.json" ]; then
      P=$(aml_mean "$BASE" "$CAND" || echo 0.95)
      echo "  → '$ds': Boomer (reference) with realistic p_equiv=$P (mean AML)"
      BOOMER_REF_P_EQUIV="$P" "$SCENARIOS_DIR/scenario_3.sh" --only-boomer "$ds" \
        || echo "  WARNING: scenario_3 --only-boomer $ds failed"
    fi
  fi

  if [ -f "$S2_DIR/applied_stats.json" ]; then
    OAEI_ARGS+=( --dataset "$ds" "$REF" "$S2_DIR" "$S3_DIR" "$INPUT_DIR" )
  else
    echo "  (skip '$ds' in chart: scenario_2 applied_stats.json missing)"
  fi
done

if [ ${#OAEI_ARGS[@]} -gt 0 ]; then
  uv run python3 oaei_rejection.py \
    "${OAEI_ARGS[@]}" \
    --no-flag \
    --title "Adjusted OAEI reference-alignment validation (Domain Coherence)" \
    --out-csv adjusted_oaei_rejection.csv \
    --out-jpg adjusted_oaei_rejection.jpg
  echo
  echo "=== adjusted_oaei_rejection.csv ==="
  cat adjusted_oaei_rejection.csv | column -t -s,
else
  echo "  OAEI validation skipped — no dataset with reference.rdf + scenario_2 applied_stats.json."
fi
