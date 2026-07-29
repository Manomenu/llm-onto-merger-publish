#!/usr/bin/env python3
"""Flag counted relations whose endpoints are not concepts of the input.

NCRC/NIRC attribute an entity to a source ontology by namespace, so an entity
the model *mints* inside a source namespace (e.g.
http://www.ebi.ac.uk/swo/version/Matlab_R14, absent from SWO) is attributed to
that source and its relations are counted as new knowledge about it.  That is a
different claim from "a new relation between two concepts of the inputs", so
the two cases are worth separating.

An endpoint counts as present in the input when its IRI occurs in the union, or
when its normalised name matches the normalised local name or rdfs:label of any
union entity — the second test absorbs the framework's renaming (NCI_C12814 →
Hippocampus) and case/separator changes.

Adds one column, `endpoint_minted`: 1 when at least one endpoint fails both
tests, else 0.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import URIRef
from rdflib.namespace import RDFS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics_def import _load_graph  # noqa: E402

INPUTS = {
    "confOf-ekaw": "tests/inputs/confOf-ekaw",
    "human-mouse": "tests/inputs/human-mouse",
    "swo-acm": "tests/inputs/swo-acm",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _local(uri: str) -> str:
    return uri.split("#")[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


def index(inputs_dir: str) -> tuple[set[str], set[str]]:
    iris: set[str] = set()
    names: set[str] = set()
    for owl in sorted(Path(inputs_dir).glob("*.owl")):
        g = _load_graph(str(owl))
        for s, p, o in g:
            for node in (s, o):
                if isinstance(node, URIRef):
                    iris.add(str(node))
                    names.add(_norm(_local(str(node))))
            if p == RDFS.label:
                names.add(_norm(str(o)))
    return iris, names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classified", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.classified, encoding="utf-8")))
    idx = {ds: index(path) for ds, path in INPUTS.items()}

    stats: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        iris, names = idx[r["dataset"]]

        def present(uri: str, label: str) -> bool:
            return (
                uri in iris
                or _norm(_local(uri)) in names
                or (bool(label) and _norm(label) in names)
            )

        minted = not (
            present(r["subject"], r["subject_label"])
            and present(r["object"], r["object_label"])
        )
        r["endpoint_minted"] = "1" if minted else "0"
        k = (r["dataset"], r["measure"])
        stats[k][0] += 1
        stats[k][1] += int(minted)

    for k in sorted(stats):
        tot, m = stats[k]
        print(f"  {k[0]:12s} {k[1]}  n={tot:6d}  minted endpoint: {m:5d}  {100 * m / tot:5.1f}%")

    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
