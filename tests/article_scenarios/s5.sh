#!/usr/bin/env bash
# tests/article_scenarios/s5.sh — fixed 4-dataset batch run against an
# OpenRouter model (default deepseek/deepseek-v4-flash), labellable for
# repeated-measurement studies.
#
# Article variant of tests/scenarios/scenario_5.sh: the same single-config
# pipeline (LLM merger + applied-alignments / Boomer / AROM / CoMerger
# baselines + combined report) over a fixed dataset list, but the LLM backend
# is ALWAYS OpenRouter, and --label nests every output under a per-run folder
# so N independent repetitions of the same datasets can coexist.
#
# Fixed dataset batch (tests/inputs folders):
#   swo-acm, confOf-ekaw, human-mouse
# (all three carry a reference.rdf, so the same set is used under the
# reference-alignment input, i.e. s6.sh.)
#
# Usage:
#   tests/article_scenarios/s5.sh                             # all 3 datasets
#   tests/article_scenarios/s5.sh --label turn1               # outputs under outputs/turn1/s5/
#   tests/article_scenarios/s5.sh --label turn1 --only swo-acm  # single dataset backfill
#   tests/article_scenarios/s5.sh --model openai/gpt-4o-mini  # other OpenRouter model
#   tests/article_scenarios/s5.sh --limit 20000               # override max-env-chars
#   tests/article_scenarios/s5.sh --skip-mine                 # reuse LLM outputs, rerun baselines + report
#   tests/article_scenarios/s5.sh --skip-all                  # reuse ALL caches, only regenerate reports
#
# Flags:
#   --label NAME     Nest outputs under tests/article_scenarios/outputs/NAME/s5/
#                    instead of tests/article_scenarios/outputs/s5/.  NAME is
#                    also mixed into the merger's --run-nonce, so repeated runs
#                    of the same dataset under different labels share no LLM
#                    prompt prefix (provider-side prompt caches are defeated
#                    and every run is sampled independently).
#   --only LABEL     Run only the dataset with this display label (repeatable).
#   --model NAME     OpenRouter model (default: deepseek/deepseek-v4-flash).
#   --limit N        max-env-chars per MergeEnvironment (default 15000).
#   --skip-mine      skip the LLM merger step (reuse existing merged_ontology.owl).
#   --skip-all       also skip Boomer / AROM / CoMerger — reuse ALL caches.
#
# Requires OPENROUTER_API_KEY in .env.
#
# Outputs (under tests/article_scenarios/outputs/[<label>/]s5/<ds-label>/ —
# gitignored), one per dataset:
#   <ds-label>_aml_<limit>c_p1000_<model-tag>/   LLM merger output + baselines
#   m_i_raport_<ds-label>.html / .csv / .log
# Baselines (Boomer/AROM/CoMerger/applied) are deterministic, so they are
# computed ONCE per dataset into the label-independent shared cache
# outputs/.baseline_cache/aml/<ds-label>/ and reused by every label (and by
# s2.sh).  Delete that dir to force recomputation.

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
DATASETS=(
  "swo-acm     swo-acm"
  "confOf-ekaw confOf-ekaw"
  "human-mouse human-mouse"
)

# ── Hardcoded config ─────────────────────────────────────────────────────────
TOOL="aml"
PARALLEL=1000
DEFAULT_MODEL="deepseek/deepseek-v4-flash"

# ── Arg parsing ──────────────────────────────────────────────────────────────
MODEL="$DEFAULT_MODEL"
LABEL=""
ONLY=()
LIMIT=15000
SKIP_MINE=0
SKIP_ALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --only)
      ONLY+=("$2")
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
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
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "$LABEL" == */* ]]; then
  echo "Error: --label must be a simple folder name (no slashes), got: $LABEL" >&2
  exit 1
fi
if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "Error: OPENROUTER_API_KEY is not set (required — s5 always runs via OpenRouter)." >&2
  exit 1
fi

_selected() {  # display label — true when no --only given or label is listed
  [ ${#ONLY[@]} -eq 0 ] && return 0
  local o
  for o in "${ONLY[@]}"; do
    [ "$o" = "$1" ] && return 0
  done
  return 1
}

MODEL_TAG="$(printf '%s' "$MODEL" | tr '/:' '__')"
TAG="${TOOL}_${LIMIT}c_p${PARALLEL}_${MODEL_TAG}"
OUTPUTS_ROOT="tests/article_scenarios/outputs"
if [ -n "$LABEL" ]; then
  OUTPUTS_ROOT="$OUTPUTS_ROOT/$LABEL"
fi

echo "========================================"
echo "  s5 / batch run (AML input, OpenRouter)"
echo "    datasets:    swo-acm, confOf-ekaw, human-mouse"
echo "    only:        $([ ${#ONLY[@]} -gt 0 ] && echo "${ONLY[*]}" || echo "(all)")"
echo "    alignment:   $TOOL"
echo "    max chars:   $LIMIT"
echo "    parallel:    $PARALLEL"
echo "    model:       $MODEL (OpenRouter)"
echo "    label:       ${LABEL:-(none)}"
echo "    skip-mine:   $([ "$SKIP_MINE" = "1" ] && echo yes || echo no)"
echo "    skip-all:    $([ "$SKIP_ALL" = "1" ] && echo yes || echo no)"
echo "    tag:         $TAG"
echo "========================================"

for spec in "${DATASETS[@]}"; do
  read -r INPUT_NAME DS_LABEL <<< "$spec"
  _selected "$DS_LABEL" || continue

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

  SCENARIO_DIR="$OUTPUTS_ROOT/s5/$DS_LABEL"
  OUT_DIR="$SCENARIO_DIR/${DS_LABEL}_$TAG"
  REPORT_HTML="$SCENARIO_DIR/m_i_raport_${DS_LABEL}.html"
  REPORT_LOG="$SCENARIO_DIR/m_i_raport_${DS_LABEL}.log"
  # Baselines are deterministic (same inputs → same outputs), so their caches
  # live OUTSIDE the per-label tree: one cache per dataset, shared by every
  # label and by the s2.sh/s5.sh pair (identical baseline inputs).  Only the
  # LLM merger is recomputed per label.  Delete a dataset's cache dir to force
  # recomputation.
  BASELINE_CACHE="tests/article_scenarios/outputs/.baseline_cache/$TOOL/$DS_LABEL"
  BOOMER_CACHE="$BASELINE_CACHE/boomer"
  AROM_CACHE="$BASELINE_CACHE/arom"
  COMERGER_CACHE="$BASELINE_CACHE/comerger"
  APPLIED_CACHE="$BASELINE_CACHE/applied"
  # Unique per (label, scenario, dataset): repeated turns of the same dataset
  # never share a prompt prefix, so nothing can be served from a prompt cache.
  RUN_NONCE="${LABEL:-single}:s5:$DS_LABEL"

  mkdir -p "$OUT_DIR"

  echo
  echo "========================================"
  echo "  [s5/${LABEL:+$LABEL/}$DS_LABEL] base: $BASE | candidate: $CANDIDATE"
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
      --model "$MODEL" \
      --run-nonce "$RUN_NONCE" \
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

  # ── Applied alignments baseline (deterministic — shared cache) ──────────────
  if [ -f "$APPLIED_CACHE/applied_alignments.owl" ]; then
    echo "  → reusing cached applied alignments ($TOOL) from $APPLIED_CACHE"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $APPLIED_CACHE/applied_alignments.owl missing — applied_alignments column will be absent"
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

  # ── Boomer (deterministic — shared cache) ───────────────────────────────────
  if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
    echo "  → reusing cached Boomer ($TOOL) from $BOOMER_CACHE"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $BOOMER_CACHE/merged_ontology.owl missing — Boomer column will be absent"
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

  # ── AROM (deterministic — shared cache) ─────────────────────────────────────
  if [ -f "$AROM_CACHE/arom_ontology.owl" ]; then
    echo "  → reusing cached AROM from $AROM_CACHE"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $AROM_CACHE/arom_ontology.owl missing — AROM column will be absent"
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

  # ── CoMerger (deterministic — shared cache) ─────────────────────────────────
  if [ -f "$COMERGER_CACHE/merged_ontology.owl" ]; then
    echo "  → reusing cached CoMerger from $COMERGER_CACHE"
  elif [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
    echo "  → reusing cached CoMerger TIMEOUT from $COMERGER_CACHE — comerger column will be absent"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $COMERGER_CACHE/merged_ontology.owl missing — CoMerger column will be absent"
  else
    echo "  → running CoMerger → $COMERGER_CACHE"
    mkdir -p "$COMERGER_CACHE"
    if ! ./thirdparty/CoMerger-1.2/comerger.sh "$BASE" "$CANDIDATE" "$COMERGER_CACHE" \
        >"$COMERGER_CACHE/run.log" 2>&1; then
      if [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
        echo "  WARNING: CoMerger timed out (3 min) — comerger column will be absent. See $COMERGER_CACHE/run.log"
      else
        echo "  WARNING: CoMerger failed — comerger column will be absent. See $COMERGER_CACHE/run.log"
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

  # ── Report (single-scenario: metrics + insights + baselines) ────────────────
  echo
  echo "  → generating report → $REPORT_HTML"
  uv run python tests/metrics_and_insights_raport.py \
    --inputs "$INPUT_DIR" \
    --output "$REPORT_HTML" \
    "$OUT_DIR" \
    >"$REPORT_LOG" 2>&1
  echo "  Done [s5/${LABEL:+$LABEL/}$DS_LABEL]. Report: $REPORT_HTML"
done

echo
echo "========================================"
echo "  s5 batch complete."
echo "========================================"
