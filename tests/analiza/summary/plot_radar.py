#!/usr/bin/env python3
"""Render a radar (spider) chart from radar_scores.csv.

Each method becomes a polygon on a 7-axis polar plot, scale 0-5.
"""

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# Distinct, thesis-friendly muted colors
COLORS = {
    "AROM":         "#3498db",  # blue
    "CoMerger":     "#9b59b6",  # purple
    "Boomer":       "#e67e22",  # orange
    "Our Solution": "#27ae60",  # green
}

DIM_FULL_NAMES = {
    "SC":  "Structural Coherence",
    "HIQ": "Hierarchy Integration",
    "KC":  "Knowledge Completeness",
    "C":   "Conciseness",
    "A":   "Accuracy",
    "DC":  "Domain Coherence",
    "U":   "Understandability",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open() as fh:
        r = list(csv.reader(fh))
    header = r[0]
    dim_keys = header[1:]
    dim_labels = [DIM_FULL_NAMES.get(k, k) for k in dim_keys]
    methods_data = [(row[0], [float(v) for v in row[1:]]) for row in r[1:]]

    n = len(dim_keys)
    angles = [i * 2 * math.pi / n for i in range(n)]
    angles_closed = angles + [angles[0]]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(math.pi / 2)  # start at top
    ax.set_theta_direction(-1)         # clockwise

    for method, scores in methods_data:
        vals = scores + [scores[0]]
        color = COLORS.get(method, "#888")
        ax.plot(angles_closed, vals, color=color, linewidth=2, label=method)
        ax.fill(angles_closed, vals, color=color, alpha=0.15)
        # value labels on each vertex
        for ang, val in zip(angles, scores):
            ax.text(ang, val + 0.18, f"{val:.1f}", color=color,
                    fontsize=8, ha="center", va="center", weight="bold")

    ax.set_xticks(angles)
    ax.set_xticklabels(dim_labels, fontsize=10)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=8)
    ax.set_ylim(0, 5.3)
    ax.grid(True, alpha=0.4)
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.10), fontsize=10)

    plt.tight_layout()
    plt.savefig(args.output, dpi=150, format="jpg" if args.output.suffix == ".jpg" else None)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
