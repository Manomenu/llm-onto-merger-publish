#!/usr/bin/env bash
# tests/article_analysis_gptoss/extend.sh — grow the gpt-oss repeated-runs
# analysis to N turns.
#
# For --number N: builds the turn list turn1..turnN, then delegates straight
# to analyze-all.sh with that explicit list.  analyze-all.sh ALREADY does
# everything the growth needs, per turn:
#   - resolves each dataset's s2 (swo-acm/confOf-ekaw/human-mouse/swo-union)
#     and s3 (cmt-edas/confOf-ekaw/human-mouse) data from the
#     tests/analiza-variance run tree
#     (tests/scenarios/outputs/<turn>/<name>-s2|-s3/ — already-computed
#     data is NEVER recomputed), then from
#     tests/article_scenarios/outputs/<turn>/
#   - only when NEITHER exists, runs tests/article_scenarios/s2.sh / s3.sh
#     --label turnK --only <dataset> to backfill it (slow — invokes the
#     default-backend LLM merger; each turn gets its own --run-nonce via
#     --label, so no two turns can share a prompt cache)
#   - then aggregates the N per-turn results into median [min; max] tables and
#     charts (bar = median, min and max marked on every bar) via the shared
#     ../article_analysis_deepseek/ helpers
#
# extend.sh's only job is turning a plain <number> into that turn list; no
# logic is duplicated from analyze-all.sh.
#
# Usage:
#   tests/article_analysis_gptoss/extend.sh 5   # ensure turn1..turn5 exist
#                                               # (reuse variance data, backfill
#                                               # the rest), then aggregate
#                                               # median/min/max
#   tests/article_analysis_gptoss/extend.sh --cdc 5   # clear the deterministic
#                                               # baseline cache + all measure
#                                               # reports first (see --cdc
#                                               # below), then run as above
#   tests/article_analysis_gptoss/extend.sh --cdc     # clear only, no run
#
# --cdc ("clear deterministic cache"): after a tests/metrics_def.py fix, every
# cached measure report is stale and must be recomputed WITHOUT re-running the
# (expensive) LLM merger.  When passed, before anything else this:
#   1. deletes the shared deterministic-baseline cache (Boomer/AROM/CoMerger/
#      Applied Alignments outputs) so the next run recomputes those methods;
#   2. deletes the per-label copies of those baseline outputs inside every s2/
#      s3 run dir, so analyze-all.sh's granular backfill (_baselines_complete)
#      actually re-triggers baseline recomputation instead of reusing them;
#   3. deletes every m_i_raport_*.{csv,html,log} + charts/ (all methods,
#      including the proposed one — cheap to recompute from the cached OWLs).
# It NEVER touches merged_ontology.owl, run.log, cost_stats.json,
# relabeling_map.json, alignment_stats.json, insights.csv/.html, debug_*.html,
# env_diff_*.txt or onto_*_leftover.html — the proposed/LLM method's own
# outputs, whose presence is exactly what lets the backfill skip the LLM call.
# Nor does it touch tests/scenarios/outputs/** (the read-only variance tree —
# nothing reachable from this script ever recomputes it) or tests/inputs/**.
# Set CDC_DRY_RUN=1 to preview what would be removed without removing it.
# The shared cache is also used by the deepseek driver's s5/s6 — clearing it
# here forces a deterministic-method recompute on that side's next run too.
set -euo pipefail
cd "$(dirname "$0")"

# ── --cdc: clear deterministic-method caches + measure reports ─────────────
_cdc_clear() {
  local art_out="../article_scenarios/outputs"
  local shared_cache="$art_out/.baseline_cache"
  local dry="${CDC_DRY_RUN:-0}"
  local tag=""
  [ "$dry" = "1" ] && tag="[DRY RUN] "
  local n_cache=0 n_sidecar=0 n_report=0
  local p

  echo "=== --cdc: clearing deterministic-method caches + measure reports ==="
  [ "$dry" = "1" ] && echo "    (CDC_DRY_RUN=1 — nothing will actually be removed)"

  # 1. Shared deterministic-method cache: one dir per (aml|ref, dataset),
  #    holding Boomer/AROM/CoMerger/Applied Alignments outputs.  Shared across
  #    every label and with the deepseek driver's s5/s6 (see s2.sh/s3.sh).
  echo "--- [1/3] shared baseline cache ($shared_cache) ---"
  if [ -e "$shared_cache" ]; then
    while IFS= read -r p; do
      echo "  ${tag}removing: $p"
      n_cache=$((n_cache + 1))
    done < <(find "$shared_cache" -mindepth 3 -maxdepth 3 -type d 2>/dev/null)
    [ "$dry" = "1" ] || rm -rf -- "$shared_cache"
  fi

  # 2. Per-label copies of the baseline outputs inside each s2/s3 run dir.
  #    Their presence is what _baselines_complete() in analyze-all.sh checks
  #    to decide --skip-all vs --skip-mine — so these must go too, or the
  #    granular backfill would never re-invoke the deterministic tools even
  #    with the shared cache gone.
  local SIDECARS=(applied_alignments.owl applied_stats.json \
                   boomer_ontology.owl boomer_stats.json \
                   arom_ontology.owl arom_stats.json \
                   comerger_ontology.owl comerger_stats.json comerger_timeout.txt)
  echo "--- [2/3] per-label baseline sidecars (s2 / s3 run dirs) ---"
  local scen_dir ds_dir run_dir f
  while IFS= read -r scen_dir; do
    for ds_dir in "$scen_dir"/*/; do
      [ -d "$ds_dir" ] || continue
      for run_dir in "$ds_dir"*/; do
        [ -d "$run_dir" ] || continue
        for f in "${SIDECARS[@]}"; do
          p="${run_dir}${f}"
          [ -e "$p" ] || continue
          echo "  ${tag}removing: $p"
          [ "$dry" = "1" ] || rm -f -- "$p"
          n_sidecar=$((n_sidecar + 1))
        done
      done
    done
  done < <(find "$art_out" -type d \( -name s2 -o -name s3 \) 2>/dev/null)

  # 3. Measure reports for ALL methods (incl. the proposed one) — cheap to
  #    recompute from the cached OWLs, so always cleared regardless of #1/#2.
  echo "--- [3/3] measure reports (m_i_raport_* + charts/, s2 / s3) ---"
  while IFS= read -r scen_dir; do
    for ds_dir in "$scen_dir"/*/; do
      [ -d "$ds_dir" ] || continue
      for p in "$ds_dir"m_i_raport_*.csv "$ds_dir"m_i_raport_*.html \
               "$ds_dir"m_i_raport_*.log "${ds_dir}charts"; do
        [ -e "$p" ] || continue
        echo "  ${tag}removing: $p"
        [ "$dry" = "1" ] || rm -rf -- "$p"
        n_report=$((n_report + 1))
      done
    done
  done < <(find "$art_out" -type d \( -name s2 -o -name s3 \) 2>/dev/null)

  echo
  echo "=== --cdc summary: baseline-cache dirs=$n_cache  per-label sidecars=$n_sidecar  report files=$n_report ==="
  [ "$dry" = "1" ] && echo "    (dry run — nothing was actually removed; unset CDC_DRY_RUN to apply)"
}

CDC=0
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --cdc) CDC=1 ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

if [ "$CDC" = "1" ]; then
  _cdc_clear
fi

N="${POSITIONAL[0]:-}"
if [ -z "$N" ]; then
  if [ "$CDC" = "1" ]; then
    echo "=== --cdc: clear-only invocation (no turn count given) — exiting without running ==="
    exit 0
  fi
  echo "Usage: extend.sh [--cdc] <number-of-turns>   (e.g. extend.sh 5 for turn1..turn5)" >&2
  exit 1
fi
case "$N" in
  *[!0-9]*)
    echo "Usage: extend.sh [--cdc] <number-of-turns>   (e.g. extend.sh 5 for turn1..turn5)" >&2
    exit 1
    ;;
esac
if [ "$N" -lt 1 ]; then
  echo "Error: <number> must be >= 1, got '$N'" >&2
  exit 1
fi

TURNS=()
for i in $(seq 1 "$N"); do
  TURNS+=("turn$i")
done

echo "=== extend.sh: growing gpt-oss repeated-runs analysis to n=$N turns (${TURNS[*]}) ==="
exec bash analyze-all.sh "${TURNS[@]}"
