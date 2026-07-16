#!/usr/bin/env bash
# tests/analiza-variance/extend.sh — grow the variance analysis to N turns.
#
# For --number N: builds the turn list turn1..turnN, then delegates straight
# to analyze-all.sh with that explicit list.  analyze-all.sh ALREADY does
# everything the growth needs, per turn:
#   - checks turnK has complete scenario_2 (AML, m_i_raport) data for the 4
#     main datasets + confOf-ekaw, and scenario_3 (reference-input) data for
#     conference/human-mouse/confOf-ekaw
#   - for anything missing, runs scenario_2.sh/scenario_3.sh --label turnK
#     <dataset> to backfill it (slow — invokes the LLM merger)
#   - then re-runs the exact tests/analiza/ pipeline once per turn and
#     combines the N per-turn aggregates into mean ± sample-std tables/charts
#     (combine_turns.py / plot_variance.py / combine_oaei.py) — same reporting
#     convention as the existing turn1-3 run, extended to n=N.
#
# extend.sh's only job is turning a plain <number> into that turn list; no
# logic is duplicated from analyze-all.sh.
#
# Usage:
#   tests/analiza-variance/extend.sh 5     # ensure turn1..turn5 exist (backfill
#                                           # any missing ones), then aggregate
#                                           # mean±std across all 5
set -euo pipefail
cd "$(dirname "$0")"

N="${1:-}"
case "$N" in
  ''|*[!0-9]*)
    echo "Usage: extend.sh <number-of-turns>   (e.g. extend.sh 5 for turn1..turn5)" >&2
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

echo "=== extend.sh: growing variance analysis to n=$N turns (${TURNS[*]}) ==="
exec bash analyze-all.sh "${TURNS[@]}"
