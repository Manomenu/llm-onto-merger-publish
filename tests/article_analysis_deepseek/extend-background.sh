#!/usr/bin/env bash
# extend-background.sh — launch extend.sh detached, sleep-inhibited, and logged.
#
# Wraps tests/article_analysis_deepseek/extend.sh so a long deepseek repeated-runs
# generation survives:
#   - terminal close / SSH drop  → nohup (ignores SIGHUP) + background (&)
#   - macOS idle / system sleep  → caffeinate -is (NATIVE /usr/bin/caffeinate,
#                                  ships with macOS — no npx/nix/brew needed)
# The launcher returns immediately; the real work runs in the background.
#
# Usage:
#   tests/article_analysis_deepseek/extend-background.sh [N]      # default N=3 turns
#   tests/article_analysis_deepseek/extend-background.sh 5
#   tests/article_analysis_deepseek/extend-background.sh --cdc 5  # pass-through flags
#
# After launch it prints the PID, the log path, and how to watch / stop it.
#
# CAVEAT (macOS): caffeinate can't beat closed-lid sleep on battery (hard
# clamshell mode).  For a lid-closed run you need AC power + an external display
# connected.  Safest: leave the lid open, on the charger, network stable.
set -euo pipefail
cd "$(dirname "$0")"

CAFFEINATE=/usr/bin/caffeinate
EXTEND=./extend.sh

# ── Preconditions ──────────────────────────────────────────────────────────
if [ ! -x "$CAFFEINATE" ]; then
  echo "Error: $CAFFEINATE not found — this wrapper targets macOS (caffeinate is built in)." >&2
  echo "       On this machine it appears missing; run extend.sh under nohup without it," >&2
  echo "       but the display/system may still sleep." >&2
  exit 1
fi
if [ ! -f "$EXTEND" ]; then
  echo "Error: $EXTEND not found next to this script." >&2
  exit 1
fi

# ── Don't stack two generations on the same output tree ────────────────────
if pgrep -f "extend\.sh" >/dev/null 2>&1; then
  echo "Refusing to start: an extend.sh process already appears to be running." >&2
  echo "  Check it:  pgrep -fl extend.sh" >&2
  echo "  Watch it:  tail -f $(pwd)/extend_deepseek_*.log" >&2
  echo "  Stop it :  pkill -f extend.sh" >&2
  exit 1
fi

# ── Launch ─────────────────────────────────────────────────────────────────
TS="$(date +%Y%m%d_%H%M%S)"
LOG="$(pwd)/extend_deepseek_${TS}.log"
PIDFILE="$(pwd)/extend_deepseek_${TS}.pid"

# caffeinate -i (no idle sleep) -m (no disk idle) -s (no system sleep, on AC).
# It holds the wake assertion exactly as long as its child (bash extend.sh)
# runs, then exits on its own — nothing to clean up.
nohup "$CAFFEINATE" -ims bash "$EXTEND" "$@" >"$LOG" 2>&1 &
PID=$!
echo "$PID" >"$PIDFILE"

echo "=== extend-background.sh: launched ==="
echo "  args      : ${*:-<none> (extend.sh default)}"
echo "  PID       : $PID   (also saved to $PIDFILE)"
echo "  log       : $LOG"
echo "  awake     : caffeinate -ims holds the Mac awake until the run finishes"
echo
echo "  watch     : tail -f \"$LOG\""
echo "  alive?    : pgrep -fl extend.sh"
echo "  stop      : pkill -f extend.sh        # (or: kill \$(cat \"$PIDFILE\"))"
echo
echo "  Safe to close this terminal now — the run keeps going."
