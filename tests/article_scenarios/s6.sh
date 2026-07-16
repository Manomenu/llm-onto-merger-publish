#!/usr/bin/env bash
# tests/article_scenarios/s6.sh — fixed reference-alignment batch run against
# an OpenRouter model (default deepseek/deepseek-v4-flash), labellable for
# repeated-measurement studies.
#
# Article variant of tests/scenarios/scenario_6.sh: feeds the OAEI REFERENCE
# alignment (gold standard) instead of AML as input — measures how a
# *selective* method treats correspondences it KNOWS to be correct (see
# tests/scenarios/scenario_3.sh's header for the Domain-Coherence rationale).
# The LLM backend is ALWAYS OpenRouter, and --label nests every output under a
# per-run folder so N independent repetitions can coexist.
#
# Fixed dataset batch (only datasets with tests/inputs/<name>/reference.rdf;
# tests/inputs folder → display label):
#   swo-acm, confOf-ekaw, human-mouse
#
# Usage:
#   tests/article_scenarios/s6.sh                             # all 3 datasets
#   tests/article_scenarios/s6.sh --label turn1               # outputs under outputs/turn1/s6/
#   tests/article_scenarios/s6.sh --label turn1 --only swo-acm  # single dataset backfill
#   tests/article_scenarios/s6.sh --model openai/gpt-4o-mini  # other OpenRouter model
#   tests/article_scenarios/s6.sh --limit 20000               # override max-env-chars
#   tests/article_scenarios/s6.sh --skip-mine                 # reuse LLM outputs, rerun baselines + report
#   tests/article_scenarios/s6.sh --skip-all                  # reuse ALL caches, only regenerate reports
#
# Flags:
#   --label NAME     Nest outputs under tests/article_scenarios/outputs/NAME/s6/
#                    instead of tests/article_scenarios/outputs/s6/.  NAME is
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
# Boomer uses the dedicated thirdparty/boomer/boomer_s3.sh wrapper (builds its
# ptable from the reference alignment instead of running a matcher).  AROM /
# CoMerger take the reference.rdf as their 4th positional arg (alignment file)
# instead of computing AML themselves.
#
# Outputs (under tests/article_scenarios/outputs/[<label>/]s6/<ds-label>/ —
# gitignored), one per dataset:
#   <ds-label>_ref_<limit>c_p1000_<model-tag>/   LLM merger output + baselines
#   m_i_raport_<ds-label>.html / .csv / .log
# Baselines (Boomer/AROM/CoMerger/applied) are deterministic, so they are
# computed ONCE per dataset into the label-independent shared cache
# outputs/.baseline_cache/ref/<ds-label>/ and reused by every label (and by
# s3.sh).  Delete that dir to force recomputation.

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
  echo "Error: OPENROUTER_API_KEY is not set (required — s6 always runs via OpenRouter)." >&2
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
TAG="ref_${LIMIT}c_p${PARALLEL}_${MODEL_TAG}"
OUTPUTS_ROOT="tests/article_scenarios/outputs"
if [ -n "$LABEL" ]; then
  OUTPUTS_ROOT="$OUTPUTS_ROOT/$LABEL"
fi

echo "========================================"
echo "  s6 / batch run (REFERENCE alignment input, OpenRouter)"
echo "    datasets:    swo-acm, confOf-ekaw, human-mouse"
echo "    only:        $([ ${#ONLY[@]} -gt 0 ] && echo "${ONLY[*]}" || echo "(all)")"
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
  REFERENCE="$INPUT_DIR/reference.rdf"
  if [ ! -f "$REFERENCE" ]; then
    echo "Error: no reference alignment at $REFERENCE — s6 requires one." >&2
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

  SCENARIO_DIR="$OUTPUTS_ROOT/s6/$DS_LABEL"
  OUT_DIR="$SCENARIO_DIR/${DS_LABEL}_$TAG"
  REPORT_HTML="$SCENARIO_DIR/m_i_raport_${DS_LABEL}.html"
  REPORT_LOG="$SCENARIO_DIR/m_i_raport_${DS_LABEL}.log"
  # Baselines are deterministic (same inputs → same outputs), so their caches
  # live OUTSIDE the per-label tree: one cache per dataset, shared by every
  # label and by the s3.sh/s6.sh pair (identical baseline inputs).  Only the
  # LLM merger is recomputed per label.  Delete a dataset's cache dir to force
  # recomputation.
  BASELINE_CACHE="tests/article_scenarios/outputs/.baseline_cache/ref/$DS_LABEL"
  BOOMER_CACHE="$BASELINE_CACHE/boomer"
  AROM_CACHE="$BASELINE_CACHE/arom"
  COMERGER_CACHE="$BASELINE_CACHE/comerger"
  APPLIED_CACHE="$BASELINE_CACHE/applied"
  # Unique per (label, scenario, dataset): repeated turns of the same dataset
  # never share a prompt prefix, so nothing can be served from a prompt cache.
  RUN_NONCE="${LABEL:-single}:s6:$DS_LABEL"

  mkdir -p "$OUT_DIR"

  echo
  echo "========================================"
  echo "  [s6/${LABEL:+$LABEL/}$DS_LABEL] base: $BASE | candidate: $CANDIDATE"
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

  # ── Applied Alignments baseline (reference input; deterministic — shared cache)
  if [ -f "$APPLIED_CACHE/applied_alignments.owl" ]; then
    echo "  → reusing cached applied alignments (reference) from $APPLIED_CACHE"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $APPLIED_CACHE/applied_alignments.owl missing — applied_alignments column will be absent"
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

  # ── AROM (reference as 4th-arg alignment file; deterministic — shared cache) ─
  if [ -f "$AROM_CACHE/arom_ontology.owl" ]; then
    echo "  → reusing cached AROM (reference) from $AROM_CACHE"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $AROM_CACHE/arom_ontology.owl missing — AROM column will be absent"
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

  # ── CoMerger (reference as 4th-arg alignment file; deterministic — shared cache)
  if [ -f "$COMERGER_CACHE/merged_ontology.owl" ]; then
    echo "  → reusing cached CoMerger (reference) from $COMERGER_CACHE"
  elif [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
    echo "  → reusing cached CoMerger TIMEOUT from $COMERGER_CACHE — comerger column will be absent"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $COMERGER_CACHE/merged_ontology.owl missing — CoMerger column will be absent"
  else
    echo "  → running CoMerger (reference) → $COMERGER_CACHE"
    mkdir -p "$COMERGER_CACHE"
    if ! ./thirdparty/CoMerger-1.2/comerger.sh "$BASE" "$CANDIDATE" "$COMERGER_CACHE" "$REFERENCE" \
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

  # ── Boomer (reference via boomer_s3.sh wrapper; deterministic — shared cache) ─
  if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
    echo "  → reusing cached Boomer (reference) from $BOOMER_CACHE"
  elif [ "$SKIP_ALL" = "1" ]; then
    echo "  WARNING: --skip-all but $BOOMER_CACHE/merged_ontology.owl missing — Boomer column will be absent"
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
  echo "  Done [s6/${LABEL:+$LABEL/}$DS_LABEL]. Report: $REPORT_HTML"
done

echo
echo "========================================"
echo "  s6 batch complete."
echo "========================================"
