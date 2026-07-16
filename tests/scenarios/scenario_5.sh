#!/usr/bin/env bash
# Scenario #5: fixed 5-dataset batch run, high concurrency, optional OpenRouter model.
#
# Runs the same single-config pipeline as scenario_2 (LLM merger + applied
# alignments / Boomer / AROM / CoMerger baselines + combined report) for a
# FIXED list of datasets in one invocation:
#   acm-union, conference (labelled "cmt-edas" in all outputs), confOf-ekaw,
#   human-mouse, swo-union
#
# Unlike scenario_2 (parallel-llm-request-count=24, tuned for a single local
# GPU box), scenario_5 defaults to 1000 concurrent merge-environment requests
# — meant for a cloud LLM endpoint (OpenRouter) that can actually absorb that
# concurrency, not the self-hosted Ollama/vLLM backend.
#
# Usage:
#   tests/scenarios/scenario_5.sh                                  # default backend (.env), 1000 parallel, 15000-char envs
#   tests/scenarios/scenario_5.sh --model                          # OpenRouter, default model (deepseek/deepseek-v4-flash)
#   tests/scenarios/scenario_5.sh --model openai/gpt-4o-mini        # OpenRouter, explicit model
#   tests/scenarios/scenario_5.sh --limit 20000                    # override max-env-chars (default 15000)
#   tests/scenarios/scenario_5.sh --skip-mine                      # reuse existing LLM outputs, rerun baselines + report
#   tests/scenarios/scenario_5.sh --skip-all                       # reuse ALL caches, only regenerate reports
#
# Flags:
#   --model [NAME]   Route the LLM merger through OpenRouter.  Omit entirely to
#                     keep using the default Ollama/vLLM backend from .env.
#                     Pass with no value for the default OpenRouter model
#                     (deepseek/deepseek-v4-flash), or with a name for a
#                     specific OpenRouter model.  Requires OPENROUTER_API_KEY
#                     in .env (same as the underlying --model flag on
#                     llm-onto-merger).
#   --limit N        max-env-chars per MergeEnvironment (default 15000).
#   --skip-mine      skip the LLM merger step (reuse existing merged_ontology.owl).
#   --skip-all       also skip Boomer / AROM / CoMerger — reuse ALL caches.
#
# Outputs (under tests/scenarios/outputs/s5/<label>/ — gitignored), one per
# dataset, where <label> is the dataset's display label (cmt-edas for
# conference, else same as the tests/inputs/ folder name):
#   <label>_aml_<limit>c_p1000_<model-tag>/   LLM merger output + boomer/arom/comerger
#   .boomer_aml/  .arom/  .comerger/  .applied_aml/    cached baseline outputs
#   m_i_raport_<label>.html / .csv / .log

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

# ── Fixed dataset batch: (tests/inputs folder, display label) ───────────────
# "conference" is labelled "cmt-edas" in every output artifact (dirs, report
# filenames, echoed banners) — same display-only rename as tests/analiza/.
DATASETS=(
  "acm-union   acm-union"
  "conference  cmt-edas"
  "confOf-ekaw confOf-ekaw"
  "human-mouse human-mouse"
  "swo-union   swo-union"
)

# ── Hardcoded config ─────────────────────────────────────────────────────────
TOOL="aml"
PARALLEL=1000

# ── Arg parsing ──────────────────────────────────────────────────────────────
MODEL_FLAG_SET=0
MODEL_VALUE=""
LIMIT=15000
SKIP_MINE=0
SKIP_ALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --model)
      MODEL_FLAG_SET=1
      # Optional value (mirrors llm-onto-merger's own --model nargs='?'):
      # only consume $2 if present and it doesn't look like another flag.
      if [ $# -ge 2 ] && [[ "$2" != -* ]]; then
        MODEL_VALUE="$2"
        shift 2
      else
        MODEL_VALUE=""
        shift
      fi
      ;;
    --limit)
      LIMIT="$2"
      shift 2
      ;;
    --skip-mine)
      SKIP_MINE=1
      shift
      ;;
    --skip-all)
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
      echo "Unexpected positional argument: $1 (scenario_5 always runs its fixed dataset list)" >&2
      exit 1
      ;;
  esac
done

DEFAULT_OPENROUTER_MODEL="deepseek/deepseek-v4-flash"
MODEL_ARGS=()
if [ "$MODEL_FLAG_SET" = "1" ]; then
  if [ -n "$MODEL_VALUE" ]; then
    EFFECTIVE_MODEL="$MODEL_VALUE"
  else
    EFFECTIVE_MODEL="$DEFAULT_OPENROUTER_MODEL"
  fi
  MODEL_ARGS=( --model "$EFFECTIVE_MODEL" )
  MODEL_TAG="$(echo "$EFFECTIVE_MODEL" | tr '/:' '__')"
else
  EFFECTIVE_MODEL=""
  MODEL_TAG="default"
fi

TAG="aml_${LIMIT}c_p${PARALLEL}_${MODEL_TAG}"

echo "========================================"
echo "  Scenario 5 / batch run"
echo "    datasets:    ${#DATASETS[@]} (acm-union, conference→cmt-edas, confOf-ekaw, human-mouse, swo-union)"
echo "    alignment:   $TOOL"
echo "    max chars:   $LIMIT"
echo "    parallel:    $PARALLEL"
echo "    backend:     $([ -n "$EFFECTIVE_MODEL" ] && echo "OpenRouter ($EFFECTIVE_MODEL)" || echo "default (.env Ollama/vLLM)")"
echo "    skip-mine:   $([ "$SKIP_MINE" = "1" ] && echo yes || echo no)"
echo "    skip-all:    $([ "$SKIP_ALL" = "1" ] && echo yes || echo no)"
echo "    tag:         $TAG"
echo "========================================"

for spec in "${DATASETS[@]}"; do
  read -r INPUT_NAME LABEL <<< "$spec"

  INPUT_DIR="tests/inputs/$INPUT_NAME"
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

  SCENARIO_DIR="tests/scenarios/outputs/s5/$LABEL"
  OUT_DIR="$SCENARIO_DIR/${LABEL}_$TAG"
  REPORT_HTML="$SCENARIO_DIR/m_i_raport_${LABEL}.html"
  REPORT_LOG="$SCENARIO_DIR/m_i_raport_${LABEL}.log"
  BOOMER_CACHE="$SCENARIO_DIR/.boomer_$TOOL"
  AROM_CACHE="$SCENARIO_DIR/.arom"
  COMERGER_CACHE="$SCENARIO_DIR/.comerger"
  APPLIED_CACHE="$SCENARIO_DIR/.applied_$TOOL"

  mkdir -p "$OUT_DIR"

  echo
  echo "========================================"
  echo "  [s5/$LABEL] base: $BASE | candidate: $CANDIDATE"
  echo "    output dir: $OUT_DIR"
  echo "========================================"

  # ── LLM merger ─────────────────────────────────────────────────────────────
  if [ "$SKIP_MINE" = "1" ]; then
    if [ -f "$OUT_DIR/merged_ontology.owl" ]; then
      echo "  --skip-mine: $OUT_DIR/merged_ontology.owl exists — skipping LLM merger"
    else
      echo "  WARNING: --skip-mine set but $OUT_DIR/merged_ontology.owl missing —" \
           "report will be incomplete"
    fi
  else
    set +o pipefail
    uv run llm-onto-merger \
      --base "$BASE" \
      --candidate "$CANDIDATE" \
      --alignment-tool "$TOOL" \
      --output "$OUT_DIR" \
      --max-env-chars "$LIMIT" \
      --parallel-llm-request-count "$PARALLEL" \
      "${MODEL_ARGS[@]}" \
      2>&1 \
      | tee "$OUT_DIR/run.log" \
      | { grep --line-buffered -E "Merged environment|Alignment application summary|env [0-9]+: alignment NOT applied|env [0-9]+: LLM response could not be parsed|Total LLM cost|ERROR" || true; }
    merger_rc="${PIPESTATUS[0]}"
    set -o pipefail
    if [ "$merger_rc" -ne 0 ]; then
      echo "  WARNING: llm-onto-merger exited with code $merger_rc — see $OUT_DIR/run.log" >&2
      exit "$merger_rc"
    fi
  fi

  # ── Applied alignments baseline (cached per tool) ───────────────────────────
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
      echo "  WARNING: generate_applied_alignments failed — applied column will be absent. See $APPLIED_CACHE/run.log"
    fi
  fi
  if [ -f "$APPLIED_CACHE/applied_alignments.owl" ]; then
    cp "$APPLIED_CACHE/applied_alignments.owl" "$OUT_DIR/applied_alignments.owl"
    echo "  → applied_alignments.owl ← $APPLIED_CACHE/applied_alignments.owl"
    if [ -f "$APPLIED_CACHE/applied_stats.json" ]; then
      cp "$APPLIED_CACHE/applied_stats.json" "$OUT_DIR/applied_stats.json"
    fi
  fi

  # ── Boomer (cached per tool) ─────────────────────────────────────────────────
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
      echo "  WARNING: Boomer ($TOOL) failed — boomer column will be absent. See $BOOMER_CACHE/run.log"
    fi
  fi
  if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
    cp "$BOOMER_CACHE/merged_ontology.owl" "$OUT_DIR/boomer_ontology.owl"
    if [ -f "$BOOMER_CACHE/boomer_stats.json" ]; then
      cp "$BOOMER_CACHE/boomer_stats.json" "$OUT_DIR/boomer_stats.json"
    fi
    echo "  → boomer_ontology.owl ← $BOOMER_CACHE/merged_ontology.owl"
  fi

  # ── AROM (cached) ────────────────────────────────────────────────────────────
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
      echo "  WARNING: AROM failed — arom column will be absent. See $AROM_CACHE/run.log"
    fi
  fi
  if [ -f "$AROM_CACHE/arom_ontology.owl" ]; then
    cp "$AROM_CACHE/arom_ontology.owl" "$OUT_DIR/arom_ontology.owl"
    if [ -f "$AROM_CACHE/arom_stats.json" ]; then
      cp "$AROM_CACHE/arom_stats.json" "$OUT_DIR/arom_stats.json"
    fi
    echo "  → arom_ontology.owl ← $AROM_CACHE/arom_ontology.owl"
  fi

  # ── CoMerger (cached) ────────────────────────────────────────────────────────
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$COMERGER_CACHE/merged_ontology.owl" ]; then
      echo "  → --skip-all: reusing cached CoMerger from $COMERGER_CACHE"
    else
      echo "  WARNING: --skip-all but $COMERGER_CACHE/merged_ontology.owl missing — CoMerger column will be absent"
    fi
  else
    echo "  → running CoMerger → $COMERGER_CACHE"
    mkdir -p "$COMERGER_CACHE"
    if ! ./thirdparty/CoMerger-1.2/comerger.sh "$BASE" "$CANDIDATE" "$COMERGER_CACHE" \
        >"$COMERGER_CACHE/run.log" 2>&1; then
      echo "  WARNING: CoMerger failed — comerger column will be absent. See $COMERGER_CACHE/run.log"
    fi
  fi
  if [ -f "$COMERGER_CACHE/merged_ontology.owl" ]; then
    cp "$COMERGER_CACHE/merged_ontology.owl" "$OUT_DIR/comerger_ontology.owl"
    if [ -f "$COMERGER_CACHE/comerger_stats.json" ]; then
      cp "$COMERGER_CACHE/comerger_stats.json" "$OUT_DIR/comerger_stats.json"
    fi
    echo "  → comerger_ontology.owl ← $COMERGER_CACHE/merged_ontology.owl"
  fi

  # ── Report (single-scenario: metrics + insights + baselines) ────────────────
  echo
  echo "  → generating report → $REPORT_HTML"
  uv run python tests/metrics_and_insights_raport.py \
    --inputs "$INPUT_DIR" \
    --output "$REPORT_HTML" \
    "$OUT_DIR" \
    >"$REPORT_LOG" 2>&1
  echo "  Done [s5/$LABEL]. Report: $REPORT_HTML"
done

echo
echo "========================================"
echo "  Scenario 5 batch complete (${#DATASETS[@]} datasets)."
echo "========================================"
