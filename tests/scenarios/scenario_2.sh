#!/usr/bin/env bash
# Scenario #2: single-config run for any large dataset (no grid).
#
# Designed for big ontology pairs (anatomy, large bio) where the 2x2 grid in
# scenario_1 would burn through the LLM budget for marginal insight.  Runs ONE
# configuration and produces a metrics + insights report comparing it against
# applied_alignments / AROM / Boomer / CoMerger baselines.
#
# Hardcoded config (same for any dataset):
#   alignment tool:             aml
#   max env chars:              15000
#   parallel llm request count: 24
#
# Usage:
#   tests/scenarios/scenario_2.sh                          # prompts for dataset
#   tests/scenarios/scenario_2.sh human-mouse              # explicit dataset
#   tests/scenarios/scenario_2.sh --skip-mine human-mouse  # reuse LLM, rerun Boomer/AROM/CoMerger
#   tests/scenarios/scenario_2.sh --skip-all human-mouse   # reuse ALL caches, only regenerate report+charts
#   tests/scenarios/scenario_2.sh --label turn1 human-mouse  # nest outputs under an extra <label>/ folder
#
# Outputs (under tests/scenarios/outputs/<dataset>-s2/ — gitignored).
# With --label <name>, outputs go under tests/scenarios/outputs/<name>/<dataset>-s2/
# instead (useful for storing multiple independent runs of the same dataset,
# e.g. a variance / repeated-runs study).
# The `-s2` suffix keeps scenario_2 results separate from scenario_1's outputs
# for the same dataset (so you can run both side-by-side on the same data).
#   <dataset>-s2_aml_15k_p24/   LLM merger output + boomer/arom/comerger + insights
#   .boomer_aml/  .arom/  .comerger/   cached baseline outputs
#   m_i_raport_<dataset>-s2.html / .csv / .log

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

# ── Hardcoded config (NOT dataset — that's parametric) ─────────────────────
TOOL="aml"
MAX_CHARS=15000
PARALLEL=24
TAG="aml_15k_p24"

# ── Arg parsing (mirrors scenario_1.sh: --skip-mine / --skip-all + DATASET) ──
SKIP_MINE=0
SKIP_ALL=0
LABEL=""
DATASET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-mine)
      SKIP_MINE=1
      shift
      ;;
    --skip-all)
      # Implies --skip-mine: don't run LLM, Boomer, AROM, or CoMerger.
      # Just regenerate the report + charts from cached outputs.
      SKIP_MINE=1
      SKIP_ALL=1
      shift
      ;;
    --label)
      LABEL="$2"
      shift 2
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

if [[ "$LABEL" == */* ]]; then
  echo "Error: --label must be a simple folder name (no slashes), got: $LABEL" >&2
  exit 1
fi

if [ -z "$DATASET" ]; then
  echo "Available input folders:"
  for d in tests/inputs/*/; do
    echo "  - $(basename "$d")"
  done
  echo
  read -r -p "Dataset name: " DATASET
fi

# ── Resolve inputs ──────────────────────────────────────────────────────────
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

# ── Output paths (`-s2` suffix keeps scenario_2 separate from scenario_1) ──
DATASET_S2="${DATASET}-s2"
if [ -n "$LABEL" ]; then
  # --label nests an extra folder above <dataset>-s2 (for repeated/variance runs).
  SCENARIO_DIR="tests/scenarios/outputs/$LABEL/$DATASET_S2"
else
  SCENARIO_DIR="tests/scenarios/outputs/$DATASET_S2"
fi
OUT_DIR="$SCENARIO_DIR/${DATASET_S2}_$TAG"
REPORT_HTML="$SCENARIO_DIR/m_i_raport_${DATASET_S2}.html"
REPORT_LOG="$SCENARIO_DIR/m_i_raport_${DATASET_S2}.log"
BOOMER_CACHE="$SCENARIO_DIR/.boomer_$TOOL"
AROM_CACHE="$SCENARIO_DIR/.arom"
COMERGER_CACHE="$SCENARIO_DIR/.comerger"
APPLIED_CACHE="$SCENARIO_DIR/.applied_$TOOL"

mkdir -p "$OUT_DIR"

echo "========================================"
echo "  Scenario 2 / ${DATASET_S2}_$TAG"
echo "    base:                       $BASE"
echo "    candidate:                  $CANDIDATE"
echo "    alignment tool:             $TOOL"
echo "    max env chars:              $MAX_CHARS"
echo "    parallel llm request count: $PARALLEL"
echo "    output dir:                 $OUT_DIR"
echo "    log:                        $OUT_DIR/run.log"
echo "    skip-mine:                  $([ "$SKIP_MINE" = "1" ] && echo yes || echo no)"
echo "    skip-all:                   $([ "$SKIP_ALL" = "1" ] && echo yes || echo no)"
echo "========================================"

# ── LLM merger ──────────────────────────────────────────────────────────────
if [ "$SKIP_MINE" = "1" ]; then
  if [ -f "$OUT_DIR/merged_ontology.owl" ]; then
    echo "  --skip-mine: $OUT_DIR/merged_ontology.owl exists — skipping LLM merger"
  else
    echo "  WARNING: --skip-mine set but $OUT_DIR/merged_ontology.owl missing —" \
         "report will be incomplete"
  fi
else
  # Stream progress (per-env merge completions) to console while still capturing
  # full log to file.  grep --line-buffered keeps progress visible in real time;
  # PIPESTATUS preserves the merger's exit code (tee/grep would otherwise mask it).
  set +o pipefail
  uv run llm-onto-merger \
    --base "$BASE" \
    --candidate "$CANDIDATE" \
    --alignment-tool "$TOOL" \
    --output "$OUT_DIR" \
    --max-env-chars "$MAX_CHARS" \
    --parallel-llm-request-count "$PARALLEL" \
    2>&1 \
    | tee "$OUT_DIR/run.log" \
    | { grep --line-buffered -E "Merged environment|Alignment application summary|env [0-9]+: alignment NOT applied|env [0-9]+: LLM response could not be parsed|ERROR" || true; }
  merger_rc="${PIPESTATUS[0]}"
  set -o pipefail
  if [ "$merger_rc" -ne 0 ]; then
    echo "  WARNING: llm-onto-merger exited with code $merger_rc — see $OUT_DIR/run.log" >&2
    exit "$merger_rc"
  fi
fi

# ── Applied alignments baseline (cached per tool, independent of LLM run) ──
if [ "$SKIP_ALL" = "1" ]; then
  if [ -f "$APPLIED_CACHE/applied_alignments.owl" ]; then
    echo "  → --skip-all: reusing cached applied alignments ($TOOL) from $APPLIED_CACHE"
  else
    echo "  WARNING: --skip-all but $APPLIED_CACHE/applied_alignments.owl missing — applied_alignments column will be absent"
  fi
else
  echo "  → running applied alignments ($TOOL) → $APPLIED_CACHE"
  mkdir -p "$APPLIED_CACHE"
  if ! uv run python tests/generate_applied_alignments.py \
      --onto1 "$BASE" --onto2 "$CANDIDATE" \
      --output "$APPLIED_CACHE" --tool "$TOOL" \
      >"$APPLIED_CACHE/run.log" 2>&1; then
    echo "  WARNING: generate_applied_alignments failed (exit $?) — applied column will be absent. See $APPLIED_CACHE/run.log"
  fi
fi
if [ -f "$APPLIED_CACHE/applied_alignments.owl" ]; then
  cp "$APPLIED_CACHE/applied_alignments.owl" "$OUT_DIR/applied_alignments.owl"
  echo "  → applied_alignments.owl ← $APPLIED_CACHE/applied_alignments.owl"
  if [ -f "$APPLIED_CACHE/applied_stats.json" ]; then
    cp "$APPLIED_CACHE/applied_stats.json" "$OUT_DIR/applied_stats.json"
  fi
fi

# ── Boomer (cached per tool) ────────────────────────────────────────────────
if [ "$SKIP_ALL" = "1" ]; then
  if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
    echo "  → --skip-all: reusing cached Boomer ($TOOL) from $BOOMER_CACHE"
  else
    echo "  WARNING: --skip-all but $BOOMER_CACHE/merged_ontology.owl missing — Boomer column will be absent"
  fi
else
  echo "  → running Boomer ($TOOL) → $BOOMER_CACHE"
  mkdir -p "$BOOMER_CACHE"
  if ! ./thirdparty/boomer/boomer.sh "$BASE" "$CANDIDATE" "$BOOMER_CACHE" "$TOOL" \
      >"$BOOMER_CACHE/run.log" 2>&1; then
    echo "  WARNING: Boomer ($TOOL) failed (exit $?) — boomer column will be absent. See $BOOMER_CACHE/run.log"
  fi
fi
if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
  cp "$BOOMER_CACHE/merged_ontology.owl" "$OUT_DIR/boomer_ontology.owl"
  if [ -f "$BOOMER_CACHE/boomer_stats.json" ]; then
    cp "$BOOMER_CACHE/boomer_stats.json" "$OUT_DIR/boomer_stats.json"
  fi
  echo "  → boomer_ontology.owl ← $BOOMER_CACHE/merged_ontology.owl"
fi

# ── AROM (cached) ──────────────────────────────────────────────────────────
if [ "$SKIP_ALL" = "1" ]; then
  if [ -f "$AROM_CACHE/arom_ontology.owl" ]; then
    echo "  → --skip-all: reusing cached AROM from $AROM_CACHE"
  else
    echo "  WARNING: --skip-all but $AROM_CACHE/arom_ontology.owl missing — AROM column will be absent"
  fi
else
  echo "  → running AROM → $AROM_CACHE"
  mkdir -p "$AROM_CACHE"
  if ! ./thirdparty/arom/arom.sh "$BASE" "$CANDIDATE" "$AROM_CACHE" \
      >"$AROM_CACHE/run.log" 2>&1; then
    echo "  WARNING: AROM failed (exit $?) — arom column will be absent. See $AROM_CACHE/run.log"
  fi
fi
if [ -f "$AROM_CACHE/arom_ontology.owl" ]; then
  cp "$AROM_CACHE/arom_ontology.owl" "$OUT_DIR/arom_ontology.owl"
  if [ -f "$AROM_CACHE/arom_stats.json" ]; then
    cp "$AROM_CACHE/arom_stats.json" "$OUT_DIR/arom_stats.json"
  fi
  echo "  → arom_ontology.owl ← $AROM_CACHE/arom_ontology.owl"
fi

# ── CoMerger (cached) ──────────────────────────────────────────────────────
if [ "$SKIP_ALL" = "1" ]; then
  if [ -f "$COMERGER_CACHE/merged_ontology.owl" ]; then
    echo "  → --skip-all: reusing cached CoMerger from $COMERGER_CACHE"
  else
    echo "  WARNING: --skip-all but $COMERGER_CACHE/merged_ontology.owl missing — CoMerger column will be absent"
  fi
elif [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
  echo "  → cached CoMerger TIMEOUT at $COMERGER_CACHE — skipping 3-min re-run; comerger column will be absent"
else
  echo "  → running CoMerger → $COMERGER_CACHE"
  mkdir -p "$COMERGER_CACHE"
  if ! ./thirdparty/CoMerger-1.2/comerger.sh "$BASE" "$CANDIDATE" "$COMERGER_CACHE" \
      >"$COMERGER_CACHE/run.log" 2>&1; then
    if [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
      echo "  WARNING: CoMerger timed out (3 min) — comerger column will be absent. See $COMERGER_CACHE/run.log"
    else
      echo "  WARNING: CoMerger failed (exit $?) — comerger column will be absent. See $COMERGER_CACHE/run.log"
    fi
  fi
fi
if [ -f "$COMERGER_CACHE/merged_ontology.owl" ]; then
  cp "$COMERGER_CACHE/merged_ontology.owl" "$OUT_DIR/comerger_ontology.owl"
  if [ -f "$COMERGER_CACHE/comerger_stats.json" ]; then
    cp "$COMERGER_CACHE/comerger_stats.json" "$OUT_DIR/comerger_stats.json"
  fi
  echo "  → comerger_ontology.owl ← $COMERGER_CACHE/merged_ontology.owl"
elif [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
  cp "$COMERGER_CACHE/comerger_timeout.txt" "$OUT_DIR/comerger_timeout.txt"
  echo "  → comerger_timeout.txt ← $COMERGER_CACHE (CoMerger exceeded 3-min limit)"
fi

# ── Report (single-scenario: metrics + insights + Boomer column) ────────────
echo
echo "========================================"
echo "  Generating report"
echo "    inputs: $INPUT_DIR"
echo "    output: $REPORT_HTML"
echo "    log:    $REPORT_LOG"
echo "========================================"
uv run python tests/metrics_and_insights_raport.py \
  --inputs "$INPUT_DIR" \
  --output "$REPORT_HTML" \
  "$OUT_DIR" \
  >"$REPORT_LOG" 2>&1

echo
echo "Done. Report: $REPORT_HTML"
