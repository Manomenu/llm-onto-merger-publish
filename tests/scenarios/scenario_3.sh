#!/usr/bin/env bash
# Scenario #3: feed the OAEI REFERENCE alignment (gold standard) instead of AML.
#
# Purpose: Domain-Coherence validation against ground truth.  By giving every
# method the reference alignment as input we can measure how a *selective* method
# treats correspondences it KNOWS to be correct:
#   - "rejected reference"  (negative measure) — how many gold pairs it drops.
# The complementary positive measure ("rejected AML false-positives") is computed
# from the existing scenario_2 (AML-input) run.  Both are turned into a chart by
#   tests/analiza/domain_coherence/analyze.sh  (oaei_rejection.py).
#
# Only datasets with tests/inputs/<dataset>/reference.rdf are valid here
# (conference, human-mouse).  AML is NOT invoked anywhere in this scenario.
#
# Usage:
#   tests/scenarios/scenario_3.sh                          # prompts for dataset
#   tests/scenarios/scenario_3.sh conference               # explicit dataset
#   tests/scenarios/scenario_3.sh --skip-mine human-mouse  # reuse LLM, rerun baselines
#   tests/scenarios/scenario_3.sh --skip-all human-mouse   # reuse all caches
#   tests/scenarios/scenario_3.sh --label turn1 conference # nest outputs under an extra <label>/ folder
#
# Outputs under tests/scenarios/outputs/<dataset>-s3/ (gitignored).  The `-s3`
# suffix keeps these separate from scenario_2's `-s2` outputs for the same data.
# With --label <name>, outputs go under tests/scenarios/outputs/<name>/<dataset>-s3/
# instead (useful for storing multiple independent runs of the same dataset,
# e.g. a variance / repeated-runs study).
#
# Boomer uses the dedicated thirdparty/boomer/boomer_s3.sh wrapper, which builds
# its ptable from the reference alignment (via generate_inputs.py --alignment-file)
# instead of running a matcher.  Note: Boomer (like AROM/CoMerger) does not emit a
# per-pair rejection log, so the two OAEI-rejection MEASURES remain computable only
# for the proposed method; Boomer's merged ontology here is for completeness / any
# other metric run under reference input.

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

# ── Hardcoded config (mirrors scenario_2) ──────────────────────────────────
MAX_CHARS=15000
PARALLEL=24
TAG="ref_15k_p24"

# ── Arg parsing ─────────────────────────────────────────────────────────────
SKIP_MINE=0
SKIP_ALL=0
ONLY_BOOMER=0
LABEL=""
DATASET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-mine) SKIP_MINE=1; shift ;;
    --skip-all)  SKIP_MINE=1; SKIP_ALL=1; shift ;;
    # Run ONLY Boomer (reference input) — skip the LLM merger and the other
    # baselines.  Used to populate the missing boomer_stats.json in an existing
    # s3 dir without re-running the expensive LLM merge.
    --only-boomer) ONLY_BOOMER=1; SKIP_MINE=1; shift ;;
    --label)     LABEL="$2"; shift 2 ;;
    --help|-h)   sed -n '2,/^$/p' "$0" | sed 's/^# *//' >&2; exit 0 ;;
    -*)          echo "Unknown option: $1" >&2; exit 1 ;;
    *)
      if [ -z "$DATASET" ]; then DATASET="$1"; else
        echo "Too many positional arguments (got '$1' after '$DATASET')" >&2; exit 1
      fi
      shift ;;
  esac
done

if [[ "$LABEL" == */* ]]; then
  echo "Error: --label must be a simple folder name (no slashes), got: $LABEL" >&2
  exit 1
fi

if [ -z "$DATASET" ]; then
  echo "Datasets with a reference alignment:"
  for d in tests/inputs/*/; do
    [ -f "$d/reference.rdf" ] && echo "  - $(basename "$d")"
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
REFERENCE="$INPUT_DIR/reference.rdf"
if [ ! -f "$REFERENCE" ]; then
  echo "Error: no reference alignment at $REFERENCE — scenario_3 requires one." >&2
  echo "       Valid datasets: those with tests/inputs/<dataset>/reference.rdf" >&2
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

# ── Output paths (`-s3` suffix) ─────────────────────────────────────────────
DATASET_S3="${DATASET}-s3"
if [ -n "$LABEL" ]; then
  # --label nests an extra folder above <dataset>-s3 (for repeated/variance runs).
  SCENARIO_DIR="tests/scenarios/outputs/$LABEL/$DATASET_S3"
else
  SCENARIO_DIR="tests/scenarios/outputs/$DATASET_S3"
fi
OUT_DIR="$SCENARIO_DIR/${DATASET_S3}_$TAG"
AROM_CACHE="$SCENARIO_DIR/.arom_ref"
COMERGER_CACHE="$SCENARIO_DIR/.comerger_ref"
APPLIED_CACHE="$SCENARIO_DIR/.applied_ref"
mkdir -p "$OUT_DIR"

echo "========================================"
echo "  Scenario 3 / ${DATASET_S3}_$TAG  (REFERENCE alignment, no AML)"
echo "    base:       $BASE"
echo "    candidate:  $CANDIDATE"
echo "    reference:  $REFERENCE"
echo "    output dir: $OUT_DIR"
echo "    skip-mine:  $([ "$SKIP_MINE" = "1" ] && echo yes || echo no)"
echo "    skip-all:   $([ "$SKIP_ALL" = "1" ] && echo yes || echo no)"
echo "========================================"

# ── LLM merger (proposed) — reference as input via --alignment-file ─────────
if [ "$SKIP_MINE" = "1" ]; then
  if [ -f "$OUT_DIR/alignment_stats.json" ]; then
    echo "  --skip-mine: $OUT_DIR/alignment_stats.json exists — skipping LLM merger"
  else
    echo "  WARNING: --skip-mine set but $OUT_DIR/alignment_stats.json missing —" \
         "measure 1 (rejected reference) will be unavailable"
  fi
else
  set +o pipefail
  uv run llm-onto-merger \
    --base "$BASE" \
    --candidate "$CANDIDATE" \
    --alignment-file "$REFERENCE" \
    --output "$OUT_DIR" \
    --max-env-chars "$MAX_CHARS" \
    --parallel-llm-request-count "$PARALLEL" \
    2>&1 \
    | tee "$OUT_DIR/run.log" \
    | { grep --line-buffered -E "Merged environment|Alignment application summary|alignment NOT applied|ERROR" || true; }
  merger_rc="${PIPESTATUS[0]}"
  set -o pipefail
  if [ "$merger_rc" -ne 0 ]; then
    echo "  WARNING: llm-onto-merger exited with code $merger_rc — see $OUT_DIR/run.log" >&2
    exit "$merger_rc"
  fi
fi

# ── Applied Alignments baseline (reference as input) ────────────────────────
if [ "$ONLY_BOOMER" != "1" ] && [ "$SKIP_ALL" != "1" ]; then
  echo "  → running applied alignments (reference) → $APPLIED_CACHE"
  mkdir -p "$APPLIED_CACHE"
  if ! uv run python tests/generate_applied_alignments.py \
      --onto1 "$BASE" --onto2 "$CANDIDATE" \
      --output "$APPLIED_CACHE" --alignment-file "$REFERENCE" \
      >"$APPLIED_CACHE/run.log" 2>&1; then
    echo "  WARNING: generate_applied_alignments failed — see $APPLIED_CACHE/run.log"
  fi
fi
[ -f "$APPLIED_CACHE/applied_alignments.owl" ] && \
  cp "$APPLIED_CACHE/applied_alignments.owl" "$OUT_DIR/applied_alignments.owl"
[ -f "$APPLIED_CACHE/applied_stats.json" ] && \
  cp "$APPLIED_CACHE/applied_stats.json" "$OUT_DIR/applied_stats.json"

# ── AROM (reference as 4th-arg alignment file) ──────────────────────────────
if [ "$ONLY_BOOMER" != "1" ] && [ "$SKIP_ALL" != "1" ]; then
  echo "  → running AROM (reference) → $AROM_CACHE"
  mkdir -p "$AROM_CACHE"
  if ! ./thirdparty/arom/arom.sh "$BASE" "$CANDIDATE" "$AROM_CACHE" "$REFERENCE" \
      >"$AROM_CACHE/run.log" 2>&1; then
    echo "  WARNING: AROM failed — see $AROM_CACHE/run.log"
  fi
fi
[ -f "$AROM_CACHE/arom_ontology.owl" ] && \
  cp "$AROM_CACHE/arom_ontology.owl" "$OUT_DIR/arom_ontology.owl"
[ -f "$AROM_CACHE/arom_stats.json" ] && \
  cp "$AROM_CACHE/arom_stats.json" "$OUT_DIR/arom_stats.json"

# ── CoMerger (reference as 4th-arg alignment file) ──────────────────────────
if [ "$ONLY_BOOMER" != "1" ] && [ "$SKIP_ALL" != "1" ]; then
  if [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
    echo "  → cached CoMerger TIMEOUT at $COMERGER_CACHE — skipping 3-min re-run; comerger column will be absent"
  else
    echo "  → running CoMerger (reference) → $COMERGER_CACHE"
    mkdir -p "$COMERGER_CACHE"
    if ! ./thirdparty/CoMerger-1.2/comerger.sh "$BASE" "$CANDIDATE" "$COMERGER_CACHE" "$REFERENCE" \
        >"$COMERGER_CACHE/run.log" 2>&1; then
      if [ -f "$COMERGER_CACHE/comerger_timeout.txt" ]; then
        echo "  WARNING: CoMerger timed out (3 min) — see $COMERGER_CACHE/run.log"
      else
        echo "  WARNING: CoMerger failed — see $COMERGER_CACHE/run.log"
      fi
    fi
  fi
fi
[ -f "$COMERGER_CACHE/merged_ontology.owl" ] && \
  cp "$COMERGER_CACHE/merged_ontology.owl" "$OUT_DIR/comerger_ontology.owl"
[ -f "$COMERGER_CACHE/comerger_stats.json" ] && \
  cp "$COMERGER_CACHE/comerger_stats.json" "$OUT_DIR/comerger_stats.json"
[ -f "$COMERGER_CACHE/comerger_timeout.txt" ] && \
  cp "$COMERGER_CACHE/comerger_timeout.txt" "$OUT_DIR/comerger_timeout.txt"

# ── Boomer (reference via dedicated boomer_s3.sh wrapper) ───────────────────
BOOMER_CACHE="$SCENARIO_DIR/.boomer_ref"
if [ "$ONLY_BOOMER" = "1" ] || [ "$SKIP_ALL" != "1" ]; then
  echo "  → running Boomer (reference) → $BOOMER_CACHE"
  mkdir -p "$BOOMER_CACHE"
  if ! ./thirdparty/boomer/boomer_s3.sh "$BASE" "$CANDIDATE" "$BOOMER_CACHE" "$REFERENCE" \
      >"$BOOMER_CACHE/run.log" 2>&1; then
    echo "  WARNING: Boomer failed — see $BOOMER_CACHE/run.log"
  fi
fi
[ -f "$BOOMER_CACHE/merged_ontology.owl" ] && \
  cp "$BOOMER_CACHE/merged_ontology.owl" "$OUT_DIR/boomer_ontology.owl"
[ -f "$BOOMER_CACHE/boomer_stats.json" ] && \
  cp "$BOOMER_CACHE/boomer_stats.json" "$OUT_DIR/boomer_stats.json"

echo
echo "Done. Proposed-method alignment stats: $OUT_DIR/alignment_stats.json"
echo "Compute the two OAEI-rejection measures + chart with:"
echo "  tests/analiza/domain_coherence/analyze.sh"
