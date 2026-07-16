#!/usr/bin/env bash
# Scenario #6: fixed reference-alignment batch run, high concurrency, optional
# OpenRouter model.
#
# Like scenario_3, feeds the OAEI REFERENCE alignment (gold standard) instead
# of AML as input — measures how a *selective* method treats correspondences
# it KNOWS to be correct (see scenario_3.sh's header for the Domain-Coherence
# rationale).  Unlike scenario_3 (single dataset, parallel-llm-request-count=24,
# tuned for a local GPU box), scenario_6 batches over every dataset that HAS a
# reference.rdf, and — like scenario_5 — defaults to 1000 concurrent
# merge-environment requests, meant for a cloud LLM endpoint (OpenRouter) that
# can actually absorb that concurrency.
#
# Fixed dataset list (only datasets with tests/inputs/<name>/reference.rdf):
#   conference (labelled "cmt-edas" in all outputs), confOf-ekaw, human-mouse
#
# Usage:
#   tests/scenarios/scenario_6.sh                                  # default backend (.env), 1000 parallel, 15000-char envs
#   tests/scenarios/scenario_6.sh --model                          # OpenRouter, default model (deepseek/deepseek-v4-flash)
#   tests/scenarios/scenario_6.sh --model openai/gpt-4o-mini        # OpenRouter, explicit model
#   tests/scenarios/scenario_6.sh --limit 20000                    # override max-env-chars (default 15000)
#   tests/scenarios/scenario_6.sh --skip-mine                      # reuse existing LLM outputs, rerun baselines + report
#   tests/scenarios/scenario_6.sh --skip-all                       # reuse ALL caches, only regenerate reports
#
# Flags:
#   --model [NAME]   Route the LLM merger through OpenRouter.  Omit entirely to
#                     keep using the default Ollama/vLLM backend from .env.
#                     Pass with no value for the default OpenRouter model
#                     (deepseek/deepseek-v4-flash), or with a name for a
#                     specific OpenRouter model.  Requires OPENROUTER_API_KEY
#                     in .env.
#   --limit N        max-env-chars per MergeEnvironment (default 15000).
#   --skip-mine      skip the LLM merger step (reuse existing merged_ontology.owl).
#   --skip-all       also skip Boomer / AROM / CoMerger — reuse ALL caches.
#
# Boomer uses the dedicated thirdparty/boomer/boomer_s3.sh wrapper (builds its
# ptable from the reference alignment instead of running a matcher) — same as
# scenario_3.  AROM / CoMerger take the reference.rdf as their 4th positional
# arg (alignment file) instead of computing AML themselves.
#
# Outputs (under tests/scenarios/outputs/s6/<label>/ — gitignored), one per
# dataset, where <label> is the dataset's display label (cmt-edas for
# conference, else same as the tests/inputs/ folder name):
#   <label>_ref_<limit>c_p1000_<model-tag>/   LLM merger output + boomer/arom/comerger
#   .boomer_ref/  .arom_ref/  .comerger_ref/  .applied_ref/   cached baseline outputs
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
# Only datasets with a reference.rdf.  "conference" is labelled "cmt-edas" in
# every output artifact (dirs, report filenames, echoed banners) — same
# display-only rename as tests/analiza/ and scenario_5.sh.
DATASETS=(
  "conference  cmt-edas"
  "confOf-ekaw confOf-ekaw"
  "human-mouse human-mouse"
)

# ── Hardcoded config ─────────────────────────────────────────────────────────
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
      echo "Unexpected positional argument: $1 (scenario_6 always runs its fixed dataset list)" >&2
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

TAG="ref_${LIMIT}c_p${PARALLEL}_${MODEL_TAG}"

echo "========================================"
echo "  Scenario 6 / batch run (REFERENCE alignment, no AML)"
echo "    datasets:    ${#DATASETS[@]} (conference→cmt-edas, confOf-ekaw, human-mouse)"
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
  REFERENCE="$INPUT_DIR/reference.rdf"
  if [ ! -f "$REFERENCE" ]; then
    echo "Error: no reference alignment at $REFERENCE — scenario_6 requires one." >&2
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

  SCENARIO_DIR="tests/scenarios/outputs/s6/$LABEL"
  OUT_DIR="$SCENARIO_DIR/${LABEL}_$TAG"
  REPORT_HTML="$SCENARIO_DIR/m_i_raport_${LABEL}.html"
  REPORT_LOG="$SCENARIO_DIR/m_i_raport_${LABEL}.log"
  BOOMER_CACHE="$SCENARIO_DIR/.boomer_ref"
  AROM_CACHE="$SCENARIO_DIR/.arom_ref"
  COMERGER_CACHE="$SCENARIO_DIR/.comerger_ref"
  APPLIED_CACHE="$SCENARIO_DIR/.applied_ref"

  mkdir -p "$OUT_DIR"

  echo
  echo "========================================"
  echo "  [s6/$LABEL] base: $BASE | candidate: $CANDIDATE"
  echo "    reference:  $REFERENCE"
  echo "    output dir: $OUT_DIR"
  echo "========================================"

  # ── LLM merger (proposed) — reference as input via --alignment-file ────────
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
      --alignment-file "$REFERENCE" \
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

  # ── Applied Alignments baseline (reference as input) ────────────────────────
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$APPLIED_CACHE/applied_alignments.owl" ]; then
      echo "  → --skip-all: reusing cached applied alignments (reference) from $APPLIED_CACHE"
    else
      echo "  WARNING: --skip-all but $APPLIED_CACHE/applied_alignments.owl missing — applied_alignments column will be absent"
    fi
  else
    echo "  → running applied alignments (reference) → $APPLIED_CACHE"
    mkdir -p "$APPLIED_CACHE"
    if ! uv run python tests/generate_applied_alignments.py \
        --onto1 "$BASE" --onto2 "$CANDIDATE" \
        --output "$APPLIED_CACHE" --alignment-file "$REFERENCE" \
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

  # ── AROM (reference as 4th-arg alignment file) ──────────────────────────────
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$AROM_CACHE/arom_ontology.owl" ]; then
      echo "  → --skip-all: reusing cached AROM (reference) from $AROM_CACHE"
    else
      echo "  WARNING: --skip-all but $AROM_CACHE/arom_ontology.owl missing — AROM column will be absent"
    fi
  else
    echo "  → running AROM (reference) → $AROM_CACHE"
    mkdir -p "$AROM_CACHE"
    if ! ./thirdparty/arom/arom.sh "$BASE" "$CANDIDATE" "$AROM_CACHE" "$REFERENCE" \
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

  # ── CoMerger (reference as 4th-arg alignment file) ──────────────────────────
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$COMERGER_CACHE/merged_ontology.owl" ]; then
      echo "  → --skip-all: reusing cached CoMerger (reference) from $COMERGER_CACHE"
    else
      echo "  WARNING: --skip-all but $COMERGER_CACHE/merged_ontology.owl missing — CoMerger column will be absent"
    fi
  else
    echo "  → running CoMerger (reference) → $COMERGER_CACHE"
    mkdir -p "$COMERGER_CACHE"
    if ! ./thirdparty/CoMerger-1.2/comerger.sh "$BASE" "$CANDIDATE" "$COMERGER_CACHE" "$REFERENCE" \
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

  # ── Boomer (reference via dedicated boomer_s3.sh wrapper) ───────────────────
  if [ "$SKIP_ALL" = "1" ]; then
    if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
      echo "  → --skip-all: reusing cached Boomer (reference) from $BOOMER_CACHE"
    else
      echo "  WARNING: --skip-all but $BOOMER_CACHE/merged_ontology.owl missing — Boomer column will be absent"
    fi
  else
    echo "  → running Boomer (reference) → $BOOMER_CACHE"
    mkdir -p "$BOOMER_CACHE"
    if ! ./thirdparty/boomer/boomer_s3.sh "$BASE" "$CANDIDATE" "$BOOMER_CACHE" "$REFERENCE" \
        >"$BOOMER_CACHE/run.log" 2>&1; then
      echo "  WARNING: Boomer failed — boomer column will be absent. See $BOOMER_CACHE/run.log"
    fi
  fi
  if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
    cp "$BOOMER_CACHE/merged_ontology.owl" "$OUT_DIR/boomer_ontology.owl"
    if [ -f "$BOOMER_CACHE/boomer_stats.json" ]; then
      cp "$BOOMER_CACHE/boomer_stats.json" "$OUT_DIR/boomer_stats.json"
    fi
    echo "  → boomer_ontology.owl ← $BOOMER_CACHE/merged_ontology.owl"
  fi

  # ── Report (single-scenario: metrics + insights + baselines) ─────────────────
  echo
  echo "  → generating report → $REPORT_HTML"
  uv run python tests/metrics_and_insights_raport.py \
    --inputs "$INPUT_DIR" \
    --output "$REPORT_HTML" \
    "$OUT_DIR" \
    >"$REPORT_LOG" 2>&1
  echo "  Done [s6/$LABEL]. Report: $REPORT_HTML"
done

echo
echo "========================================"
echo "  Scenario 6 batch complete (${#DATASETS[@]} datasets)."
echo "========================================"
