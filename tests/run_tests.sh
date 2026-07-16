#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck source=../.env
  source "$ROOT/.env"
  set +a
fi

run_merge() {
    local name="$1"; shift
    echo ""
    echo "========================================"
    echo "  Merging: $name"
    echo "========================================"
    uv run --python .venv/bin/python -m llm_onto_merger.main "$@"
    echo "  Done: $name"
}

run_merge "human-mouse" \
    --base    tests/inputs/human-mouse/human.owl \
    --candidate tests/inputs/human-mouse/mouse.owl \
    --alignment-tool aml \
    --output  tests/outputs/human-mouse \
    --max-env-chars 100000

run_merge "hp-mp" \
    --base    tests/inputs/hp-mp/hp.owl \
    --candidate tests/inputs/hp-mp/mp.owl \
    --alignment-tool aml \
    --output  tests/outputs/hp-mp \
    --max-env-chars 60000

run_merge "conference" \
    --base    tests/inputs/conference/cmt.owl \
    --candidate tests/inputs/conference/edas.owl \
    --alignment-tool aml \
    --output  tests/outputs/conference \
    --max-env-chars 10000
