#!/usr/bin/env bash
# Scenario #1: max-env-chars × alignment-tool grid (4 runs) + Boomer for any dataset.
#
# Usage:
#   tests/scenarios/scenario_1.sh                          # prompts for dataset name
#   tests/scenarios/scenario_1.sh conference               # uses tests/inputs/conference
#   tests/scenarios/scenario_1.sh --skip-mine conference   # reuse existing LLM outputs, just rerun Boomer + report
#
# Flags:
#   --skip-mine    skip the LLM merger step (reuse existing merged_ontology.owl
#                  in each scenario dir).  Still runs Boomer / AROM / CoMerger
#                  and regenerates the combined report + charts.
#   --skip-all     also skip Boomer / AROM / CoMerger — reuse ALL caches.
#                  Regenerates only the combined report (HTML/CSV) + chart JPGs.
#                  Fast path when you only changed the report/chart code.
#
# Runs (per dataset <name>):
#   <name>_10k_aml       max-env-chars=10000  alignment-tool=aml      (LLM)
#   <name>_20k_aml       max-env-chars=20000  alignment-tool=aml      (LLM)
#   <name>_10k_logmap    max-env-chars=10000  alignment-tool=logmap   (LLM)
#   <name>_20k_logmap    max-env-chars=20000  alignment-tool=logmap   (LLM)
#
# Boomer runs once per unique alignment tool (aml, logmap) — same Boomer output
# is copied into every scenario folder that uses that tool, as boomer_ontology.owl.
#
# Inputs (same for all runs):
#   tests/inputs/<name>/*.owl     (exactly 2 ontologies, sorted alphabetically)
#
# Outputs (all under tests/scenarios/outputs/ — gitignored):
#   tests/scenarios/outputs/<name>/<name>_<tag>/         merged_ontology.owl + insights + boomer_ontology.owl + …
#   tests/scenarios/outputs/<name>/.boomer_<tool>/       Boomer's own output (cache, reused across scenarios)
#   tests/scenarios/outputs/<name>/m_i_raport_<name>_1.html   combined report
#   tests/scenarios/outputs/<name>/m_i_raport_<name>_1.csv

set -euo pipefail
shopt -s nullglob

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck source=../../.env
  source "$REPO_ROOT/.env"
  set +a
fi

# ── Arg parsing ──────────────────────────────────────────────────────────────
SKIP_MINE=0
SKIP_ALL=0
DATASET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-mine)
      SKIP_MINE=1
      shift
      ;;
    --skip-all)
      # Implies --skip-mine: don't run LLM, Boomer, AROM, or CoMerger.
      # Just regenerate the combined report + charts from cached outputs.
      SKIP_MINE=1
      SKIP_ALL=1
      shift
      ;;
    --help|-h)
      sed -n '2,/^$/p' "$0" | sed 's/^# *//' >&2
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [ -z "$DATASET" ]; then
        DATASET="$1"
      else
        echo "Too many positional arguments (got '$1' after '$DATASET')" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [ -z "$DATASET" ]; then
  echo "Available input folders:"
  for d in tests/inputs/*/; do
    echo "  - $(basename "$d")"
  done
  echo
  read -r -p "Dataset name: " DATASET
fi

INPUT_DIR="tests/inputs/$DATASET"
if [ ! -d "$INPUT_DIR" ]; then
  echo "Error: directory not found: $INPUT_DIR" >&2
  exit 1
fi

OWL_FILES=( "$INPUT_DIR"/*.owl )
if [ ${#OWL_FILES[@]} -ne 2 ]; then
  echo "Error: expected exactly 2 .owl files in $INPUT_DIR, found ${#OWL_FILES[@]}" >&2
  exit 1
fi
IFS=$'\n' OWL_SORTED=( $(printf '%s\n' "${OWL_FILES[@]}" | sort) )
unset IFS
BASE="${OWL_SORTED[0]}"
CANDIDATE="${OWL_SORTED[1]}"

SCENARIO_DIR="tests/scenarios/outputs/$DATASET"
OUT_BASE="$SCENARIO_DIR"
REPORT_HTML="$SCENARIO_DIR/m_i_raport_${DATASET}_1.html"
mkdir -p "$OUT_BASE"

# Tag, max-env-chars, alignment-tool
SCENARIOS=(
  "10k_aml     10000  aml"
  "20k_aml     20000  aml"
  "10k_logmap  10000  logmap"
  "20k_logmap  20000  logmap"
)

# ── Applied alignments per-tool cache ────────────────────────────────────────
APPLIED_AML_DIR=""
APPLIED_LOGMAP_DIR=""

run_applied_once() {
  local tool="$1"
  local cache_dir="$OUT_BASE/.applied_$tool"
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$cache_dir/applied_alignments.owl" ]; then
      echo "  → --skip-all: reusing cached applied alignments ($tool) from $cache_dir"
    else
      echo "  WARNING: --skip-all but $cache_dir/applied_alignments.owl missing — applied column will be absent"
    fi
  else
    echo "  → running applied alignments ($tool) → $cache_dir"
    mkdir -p "$cache_dir"
    if ! uv run python tests/generate_applied_alignments.py \
        --onto1 "$BASE" --onto2 "$CANDIDATE" \
        --output "$cache_dir" --tool "$tool" \
        >"$cache_dir/run.log" 2>&1; then
      echo "  WARNING: generate_applied_alignments ($tool) failed (exit $?) — applied column will be absent. See $cache_dir/run.log"
    fi
  fi
  case "$tool" in
    aml)    APPLIED_AML_DIR="$cache_dir" ;;
    logmap) APPLIED_LOGMAP_DIR="$cache_dir" ;;
  esac
}

# ── Boomer per-tool cache (avoids running Boomer 4x when only 2 tools are used) ──
BOOMER_AML_DIR=""
BOOMER_LOGMAP_DIR=""

run_boomer_once() {
  local tool="$1"
  local cache_dir="$OUT_BASE/.boomer_$tool"
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$cache_dir/merged_ontology.owl" ]; then
      echo "  → --skip-all: reusing cached Boomer ($tool) from $cache_dir"
    else
      echo "  WARNING: --skip-all but $cache_dir/merged_ontology.owl missing — Boomer column will be absent"
    fi
  else
    echo "  → running Boomer ($tool) → $cache_dir"
    mkdir -p "$cache_dir"
    if ! ./thirdparty/boomer/boomer.sh "$BASE" "$CANDIDATE" "$cache_dir" "$tool" \
        >"$cache_dir/run.log" 2>&1; then
      echo "  WARNING: Boomer ($tool) failed (exit $?) — boomer column will be absent. See $cache_dir/run.log"
    fi
  fi
  case "$tool" in
    aml)    BOOMER_AML_DIR="$cache_dir" ;;
    logmap) BOOMER_LOGMAP_DIR="$cache_dir" ;;
  esac
}

# ── AROM cache (single run per dataset — alignment always from AML) ──
AROM_DIR_CACHE="$OUT_BASE/.arom"
run_arom_once() {
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$AROM_DIR_CACHE/arom_ontology.owl" ]; then
      echo "  → --skip-all: reusing cached AROM from $AROM_DIR_CACHE"
    else
      echo "  WARNING: --skip-all but $AROM_DIR_CACHE/arom_ontology.owl missing — AROM column will be absent"
    fi
  else
    echo "  → running AROM → $AROM_DIR_CACHE"
    mkdir -p "$AROM_DIR_CACHE"
    if ! ./thirdparty/arom/arom.sh "$BASE" "$CANDIDATE" "$AROM_DIR_CACHE" \
        >"$AROM_DIR_CACHE/run.log" 2>&1; then
      echo "  WARNING: AROM failed (exit $?) — arom column will be absent. See $AROM_DIR_CACHE/run.log"
    fi
  fi
}
run_arom_once

# ── CoMerger cache (single run per dataset — alignment from AML) ──
COMERGER_DIR_CACHE="$OUT_BASE/.comerger"
run_comerger_once() {
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$COMERGER_DIR_CACHE/merged_ontology.owl" ]; then
      echo "  → --skip-all: reusing cached CoMerger from $COMERGER_DIR_CACHE"
    else
      echo "  WARNING: --skip-all but $COMERGER_DIR_CACHE/merged_ontology.owl missing — CoMerger column will be absent"
    fi
  else
    echo "  → running CoMerger → $COMERGER_DIR_CACHE"
    mkdir -p "$COMERGER_DIR_CACHE"
    if ! ./thirdparty/CoMerger-1.2/comerger.sh "$BASE" "$CANDIDATE" "$COMERGER_DIR_CACHE" \
        >"$COMERGER_DIR_CACHE/run.log" 2>&1; then
      echo "  WARNING: CoMerger failed (exit $?) — comerger column will be absent. See $COMERGER_DIR_CACHE/run.log"
    fi
  fi
}
run_comerger_once

OUT_DIRS=()
for spec in "${SCENARIOS[@]}"; do
  read -r tag chars tool <<< "$spec"
  out="$OUT_BASE/${DATASET}_$tag"
  OUT_DIRS+=( "$out" )
  mkdir -p "$out"
  log_file="$out/run.log"

  echo
  echo "========================================"
  echo "  Scenario: ${DATASET}_$tag"
  echo "    base:           $BASE"
  echo "    candidate:      $CANDIDATE"
  echo "    alignment tool: $tool"
  echo "    max env chars:  $chars"
  echo "    output dir:     $out"
  echo "    log:            $log_file"
  echo "    skip-mine:      $([ "$SKIP_MINE" = "1" ] && echo yes || echo no)"
  echo "    skip-all:       $([ "$SKIP_ALL" = "1" ] && echo yes || echo no)"
  echo "========================================"

  # ── LLM merger ──────────────────────────────────────────────────────────
  if [ "$SKIP_MINE" = "1" ]; then
    if [ -f "$out/merged_ontology.owl" ]; then
      echo "  --skip-mine: $out/merged_ontology.owl exists — skipping LLM merger"
    else
      echo "  WARNING: --skip-mine set but $out/merged_ontology.owl missing —" \
           "scenario will be incomplete (no LLM data for report)"
    fi
  else
    uv run llm-onto-merger \
      --base "$BASE" \
      --candidate "$CANDIDATE" \
      --alignment-tool "$tool" \
      --output "$out" \
      --max-env-chars "$chars" \
      >"$log_file" 2>&1
  fi

  # ── Applied alignments (per-tool cache, copied into each scenario dir) ──
  run_applied_once "$tool"
  case "$tool" in
    aml)    applied_cache_dir="$APPLIED_AML_DIR" ;;
    logmap) applied_cache_dir="$APPLIED_LOGMAP_DIR" ;;
  esac
  if [ -f "$applied_cache_dir/applied_alignments.owl" ]; then
    cp "$applied_cache_dir/applied_alignments.owl" "$out/applied_alignments.owl"
    echo "  → applied_alignments.owl ← $applied_cache_dir/applied_alignments.owl"
  fi

  # ── Boomer (per-tool cache, copied into each scenario dir) ──────────────
  run_boomer_once "$tool"
  case "$tool" in
    aml)    cache_dir="$BOOMER_AML_DIR" ;;
    logmap) cache_dir="$BOOMER_LOGMAP_DIR" ;;
  esac
  if [ -f "$cache_dir/merged_ontology.owl" ]; then
    cp "$cache_dir/merged_ontology.owl" "$out/boomer_ontology.owl"
    if [ -f "$cache_dir/boomer_stats.json" ]; then
      cp "$cache_dir/boomer_stats.json" "$out/boomer_stats.json"
    fi
    echo "  → boomer_ontology.owl ← $cache_dir/merged_ontology.owl"
  else
    echo "  WARNING: Boomer output missing at $cache_dir/merged_ontology.owl — skipping copy"
  fi

  # ── AROM (single cache, same for every scenario) ───────────────────────
  if [ -f "$AROM_DIR_CACHE/arom_ontology.owl" ]; then
    cp "$AROM_DIR_CACHE/arom_ontology.owl" "$out/arom_ontology.owl"
    if [ -f "$AROM_DIR_CACHE/arom_stats.json" ]; then
      cp "$AROM_DIR_CACHE/arom_stats.json" "$out/arom_stats.json"
    fi
    echo "  → arom_ontology.owl ← $AROM_DIR_CACHE/arom_ontology.owl"
  fi

  # ── CoMerger (single cache, same for every scenario) ───────────────────
  if [ -f "$COMERGER_DIR_CACHE/merged_ontology.owl" ]; then
    cp "$COMERGER_DIR_CACHE/merged_ontology.owl" "$out/comerger_ontology.owl"
    if [ -f "$COMERGER_DIR_CACHE/comerger_stats.json" ]; then
      cp "$COMERGER_DIR_CACHE/comerger_stats.json" "$out/comerger_stats.json"
    fi
    echo "  → comerger_ontology.owl ← $COMERGER_DIR_CACHE/merged_ontology.owl"
  fi
done

# ── Combined report (always runs) ────────────────────────────────────────────
REPORT_LOG="$SCENARIO_DIR/m_i_raport_${DATASET}_1.log"
echo
echo "========================================"
echo "  Generating combined report"
echo "    inputs:  $INPUT_DIR"
echo "    output:  $REPORT_HTML"
echo "    log:     $REPORT_LOG"
echo "========================================"
uv run python tests/metrics_and_insights_raport.py \
  --inputs "$INPUT_DIR" \
  --output "$REPORT_HTML" \
  "${OUT_DIRS[@]}" \
  >"$REPORT_LOG" 2>&1

echo
echo "Done. Report: $REPORT_HTML"
