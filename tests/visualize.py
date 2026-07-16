"""Visualize a single OWL file as an interactive HTML graph using pyvis.

Usage:
    uv run python tests/visualize.py path/to/ontology.owl
    uv run python tests/visualize.py path/to/ontology.owl --output my_graph.html
"""

import argparse
import sys
from pathlib import Path

from rdflib import Graph

sys.path.insert(0, str(Path(__file__).parent))
from visualize_pyvis import visualize_graph

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize an OWL ontology as an interactive HTML graph")
    parser.add_argument("owl_path", help="Path to the OWL file")
    parser.add_argument("--output", help="Output HTML file path (default: <owl_name>.html)")
    args = parser.parse_args()

    owl_path = Path(args.owl_path)
    if not owl_path.exists():
        parser.error(f"File not found: {owl_path}")

    output_path = args.output or str(owl_path.with_suffix(".html"))

    onto = Graph().parse(str(owl_path))
    empty = Graph()
    visualize_graph(onto, empty, output_path)
