#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

uv run python3 compute_radar_scores.py radar_scores.csv
uv run python3 plot_radar.py --input radar_scores.csv --output radar.jpg

echo
echo "=== radar_scores.csv ==="
cat radar_scores.csv | column -t -s,
