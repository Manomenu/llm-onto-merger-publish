#!/usr/bin/env python3
"""OAEI reference-alignment validation (Domain Coherence) — two complementary
measures, each from the run that makes it meaningful.  Both LOWER = better.

Measure 1 — rejected correct alignments  (needs scenario_3: REFERENCE as input)
    Feed the OAEI reference (gold) alignment to every method and count how many
    of those correct correspondences the method rejects:
        rejected_correct(method) = |R − accepted_under_reference(method)|
    Clean test over the FULL gold set (no AML-miss confound).

Measure 2 — accepted AML false-positives  (needs scenario_2: AML as input)
    From the AML-input run, count AML correspondences the method applied that are
    NOT in the reference (false-positives it failed to filter):
        accepted_aml_fp(method) = |accepted_under_aml(method) ∩ (A − R)|
    Inherently needs the AML run — the reference contains no AML false-positives.

A method's accepted-pair set is recovered identically in both runs:
    Applied Alignments / AROM → all input pairs            (apply-all)
    Proposed (merger)         → input − rejected_alignments (alignment_stats.json)
    Boomer                    → code_provenance            (boomer_stats.json)
    CoMerger                  → full input alignment when comerger_stats.json reports
                                applied == input (deterministic full merger); else a
                                fallback merged#-name reconstruction.
where input = reference (scenario_3) or AML candidate set A (scenario_2).
A is the provenance of Applied Alignments in scenario_2 (it applies ALL AML pairs).

Usage (one --dataset group per OAEI dataset):
    uv run python oaei_rejection.py \\
        --dataset conference  <reference.rdf> <s2_dir> <s3_dir> <tests/inputs/conference> \\
        --dataset human-mouse <reference.rdf> <s2_dir> <s3_dir> <tests/inputs/human-mouse> \\
        --out-csv oaei_rejection.csv --out-jpg oaei_rejection.jpg

If a dataset's scenario_3 dir is missing, measure 1 is skipped for it (with a
warning) and only measure 2 is reported — run tests/scenarios/scenario_3.sh first.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from rdflib import RDFS, Graph, Literal, URIRef

from llm_onto_merger.alignment.alignment import parse_oaei_alignment
from llm_onto_merger.alignment import AmlAlignmentModule

PairKey = frozenset
_MERGED_NS = "http://merged#"


def _local(uri: str) -> str:
    idx = max(uri.rfind("#"), uri.rfind("/"))
    return uri[idx + 1:] if idx >= 0 else uri


def _nsof(uri: str) -> str:
    idx = max(uri.rfind("#"), uri.rfind("/"))
    return uri[:idx + 1] if idx >= 0 else uri


# ── Entity identity: namespace-qualified (onto tag + local name) ──────────────
# A merge pair like cmt#Person ↔ edas#Person collapses to the SAME local name
# ("Person") — so identifying entities by local name alone conflates two distinct
# entities.  We qualify every entity as "<tag>::<local>", where tag is "1" for the
# base ontology (onto1) and "2" for the candidate (onto2), determined by namespace.
# This, combined with union-find over accepted pairs, makes the "pair preserved?"
# test correct under many-to-one references (one entity mapping to several) and
# under same-local-name pairs — the two sources of the earlier counting artifact.

def _main_ns(onto_path: Path) -> str:
    """Dominant entity namespace of an ontology (host of its subjects)."""
    g = Graph()
    g.parse(str(onto_path))
    counts: dict[str, int] = {}
    for s in g.subjects():
        if isinstance(s, URIRef):
            ns = _nsof(str(s))
            if ns.startswith(("http://www.w3.org/", "http://purl.org/dc/")):
                continue
            counts[ns] = counts.get(ns, 0) + 1
    return max(counts, key=counts.get) if counts else ""


class _UF:
    """Union-find over hashable elements."""
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)

    def same(self, a: str, b: str) -> bool:
        return a in self.parent and b in self.parent and self.find(a) == self.find(b)


def _tag(uri: str, base_ns: str, cand_ns: str) -> str:
    ns = _nsof(uri)
    return "1" if ns == base_ns else ("2" if ns == cand_ns else "?")


def _qual(uri: str, base_ns: str, cand_ns: str, inverse_relabel: dict[str, str] | None = None) -> str:
    loc = _local(uri)
    if inverse_relabel:
        loc = inverse_relabel.get(loc, loc)
    return f"{_tag(uri, base_ns, cand_ns)}::{loc}"


def _reference_qpairs(reference_path: Path, base_ns: str, cand_ns: str) -> list[tuple[str, str]]:
    return [
        (_qual(a.entity1, base_ns, cand_ns), _qual(a.entity2, base_ns, cand_ns))
        for a in parse_oaei_alignment(reference_path)
    ]


def _aml_qpairs(base_owl: Path, cand_owl: Path, base_ns: str, cand_ns: str) -> list[tuple[str, str]]:
    """Full AML candidate set as qualified pairs — computed directly from the raw
    AML alignment (deterministic).  We do NOT read it from applied_stats.json's
    code_provenance, because collapsing many-to-one correspondences into a single
    merged entity there drops some pairs (the same artifact fixed for measure 1) —
    which would under-count the AML false-positive denominator |A − R|."""
    import asyncio
    import os
    # Resolve inputs BEFORE chdir (relative paths are w.r.t. the current cwd).
    base_abs, cand_abs = base_owl.resolve(), cand_owl.resolve()
    # AML's jar path and output path are relative to the repo root; run from there.
    repo_root = Path(__file__).resolve().parents[3]
    prev = os.getcwd()
    try:
        os.chdir(repo_root)
        al = asyncio.run(AmlAlignmentModule().create_alignment(base_abs, cand_abs))
    finally:
        os.chdir(prev)
    return [(_qual(a.entity1, base_ns, cand_ns), _qual(a.entity2, base_ns, cand_ns)) for a in al]


def _load_inverse_relabel(d: Path) -> dict[str, str]:
    path = d / "relabeling_map.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {new: old for old, new in raw.items()}


def _local_names(onto_path: Path) -> set[str]:
    g = Graph()
    g.parse(str(onto_path))
    return {_local(str(s)) for s in g.subjects() if isinstance(s, URIRef)}


# ── Accepted-pair extractors (qualified) — one per method ────────────────────
def _prov_qpairs(stats_path: Path, base_ns: str, cand_ns: str) -> list[tuple[str, str]]:
    """From a *_stats.json code_provenance block (AROM sidecar, Boomer sidecar).
    Uses full URIs (1_uri/2_uri) when present → qualified by namespace; else the
    "1"/"2" onto-number keys (1=base, 2=candidate)."""
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for v in data.get("code_provenance", {}).values():
        u1, u2 = v.get("1_uri"), v.get("2_uri")
        if u1 and u2:
            out.append((_qual(u1, base_ns, cand_ns), _qual(u2, base_ns, cand_ns)))
        elif "1" in v and "2" in v:
            out.append((f"1::{v['1']}", f"2::{v['2']}"))
    return out


def _arom_cluster_qpairs(arom_owl: Path) -> list[tuple[str, str]]:
    """AROM tags each merged Code_N entity with rdfs:label '<n>. <local>' for every
    source member (n=1 base, 2 candidate).  Collecting ALL labels per Code_N gives
    the FULL merged cluster (the sidecar's dict overwrote same-onto members, losing
    many-to-one) → emit all internal pairs so union-find rebuilds the cluster."""
    g = Graph()
    g.parse(str(arom_owl))
    pat = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$")
    clusters: dict[str, set[str]] = {}
    for s, _, o in g.triples((None, RDFS.label, None)):
        if isinstance(s, URIRef) and "Code_" in str(s) and isinstance(o, Literal):
            m = pat.match(str(o))
            if m:
                clusters.setdefault(str(s), set()).add(f"{m.group(1)}::{m.group(2)}")
    out: list[tuple[str, str]] = []
    for members in clusters.values():
        ms = list(members)
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                out.append((ms[i], ms[j]))
    return out


def _comerger_applied_all(stats_path: Path) -> bool:
    """True iff CoMerger's own sidecar reports it applied EVERY input correspondence
    (applied_equiv_* == input_corresponding_*).  CoMerger is a deterministic full
    merger with GMR-consistency checking; on all our datasets it applies 100% of the
    input alignment (it does not selectively reject).  We use this authoritative
    signal instead of reconstructing the accepted set from merged# names, which is
    fragile (see _method_uf)."""
    d = json.loads(stats_path.read_text(encoding="utf-8"))
    kinds = ("classes", "object_properties", "data_properties")
    applied = sum(d.get(f"applied_equiv_{k}", 0) for k in kinds)
    inp = sum(d.get(f"input_corresponding_{k}", 0) for k in kinds)
    return inp > 0 and applied >= inp


def _comerger_cluster_qpairs(comerger_owl: Path, names1: set[str], names2: set[str]) -> list[tuple[str, str]]:
    """CoMerger collapses each accepted cluster into ONE merged# entity whose local
    name is the source names (internal '_' stripped) joined by '_'.  A same-local
    name (Person) present in both ontologies means the entity is the 1::/2:: pair;
    otherwise split the name into ALL member tokens (multi-way — handles many-to-one
    clusters like merged#NCIC.._MA.._NCIC..)."""
    g = Graph()
    g.parse(str(comerger_owl))
    strip1 = {n.replace("_", ""): n for n in names1}
    strip2 = {n.replace("_", ""): n for n in names2}
    merged_locals = {
        _local(str(t)) for t in g.all_nodes()
        if isinstance(t, URIRef) and str(t).startswith(_MERGED_NS)
    }
    out: list[tuple[str, str]] = []
    for m in merged_locals:
        if not m:
            continue
        members: set[str] = set()
        if m in names1:
            members.add(f"1::{m}")
        if m in names2:
            members.add(f"2::{m}")
        if not members:  # concatenated cluster: split and map each token
            for tok in m.split("_"):
                o1 = tok if tok in names1 else strip1.get(tok)
                o2 = tok if tok in names2 else strip2.get(tok)
                if o1:
                    members.add(f"1::{o1}")
                if o2:
                    members.add(f"2::{o2}")
        ms = list(members)
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                out.append((ms[i], ms[j]))
    return out


def _merger_rejected_qkeys(run_dir: Path, base_ns: str, cand_ns: str,
                           inverse_relabel: dict[str, str]) -> set[PairKey]:
    """Pairs the LLM merger explicitly rejected (alignment_stats.json), as qualified
    frozenset keys — used to derive Proposed's accepted set = input − rejected."""
    data = json.loads((run_dir / "alignment_stats.json").read_text(encoding="utf-8"))
    return {
        frozenset((_qual(r["entity1"], base_ns, cand_ns, inverse_relabel),
                   _qual(r["entity2"], base_ns, cand_ns, inverse_relabel)))
        for r in data.get("rejected_alignments", [])
    }


def _method_uf(run_dir: Path, input_qpairs: list[tuple[str, str]],
               base_ns: str, cand_ns: str, names1: set[str], names2: set[str],
               method: str) -> _UF | None:
    """Union-find of entities the method actually merged, for one run.  A gold pair
    (a,b) is PRESERVED iff uf.same(a,b)."""
    uf = _UF()
    if method == "AROM":
        # AROM has no rejection stage: it applies every input correspondence at/above
        # its threshold (default 0.0 → all).  The codebase's applied_alignments metric
        # treats it identically (accepted = total_align).  So the accepted set IS the
        # full input.  We do NOT reconstruct clusters from Code_N rdfs:label triples:
        # that recovery silently under-counts on some ontologies (e.g. swo-union, where
        # it recovered 1 of 5 accepted pairs) — the same class of output-reconstruction
        # fragility avoided for CoMerger.
        if not (run_dir / "arom_ontology.owl").exists():
            return None
        pairs = list(input_qpairs)
    elif method == "Boomer":
        p = run_dir / "boomer_stats.json"
        if not p.exists():
            return None
        pairs = _prov_qpairs(p, base_ns, cand_ns)
    elif method == "CoMerger":
        p = run_dir / "comerger_ontology.owl"
        if not p.exists():
            return None
        # CoMerger applies its full input alignment (its sidecar confirms applied ==
        # input on every dataset).  Recovering the accepted set by splitting merged#
        # names is fragile — it fails on source names containing '_' (Poster_Paper),
        # case differences (Social_event/Social_Event), and property merges that keep
        # one source name instead of a merged# IRI — each spuriously reporting an
        # APPLIED correspondence as "rejected".  When the sidecar confirms full
        # application, take the accepted set to be the entire input (as for AROM).
        stats = run_dir / "comerger_stats.json"
        if stats.exists() and _comerger_applied_all(stats):
            pairs = list(input_qpairs)
        else:
            pairs = _comerger_cluster_qpairs(p, names1, names2)
    elif method == "Proposed":
        p = run_dir / "alignment_stats.json"
        if not p.exists():
            return None
        rejected = _merger_rejected_qkeys(run_dir, base_ns, cand_ns,
                                          _load_inverse_relabel(run_dir))
        pairs = [(a, b) for a, b in input_qpairs if frozenset((a, b)) not in rejected]
    else:
        return None
    for a, b in pairs:
        uf.union(a, b)
    return uf


_METHODS = ["AROM", "CoMerger", "Boomer", "Proposed"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dataset", action="append", nargs=5, required=True,
        metavar=("NAME", "REFERENCE", "S2_DIR", "S3_DIR", "INPUT_DIR"),
        help="name, reference.rdf, scenario_2 dir (AML run), scenario_3 dir "
             "(reference run), tests/inputs/<name> dir (source ontologies).",
    )
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-jpg", type=Path, required=True)
    parser.add_argument("--title",
                        default="OAEI reference-alignment validation (Domain Coherence)",
                        help="Figure suptitle.")
    parser.add_argument("--no-flag", action="store_true",
                        help="Disable the Boomer ambiguity hatch/dual-label. Use for "
                             "the ADJUSTED run where Boomer's reference ptable uses a "
                             "realistic (mean-AML) p_equiv instead of the artificial cap.")
    args = parser.parse_args()

    rows: list[dict] = []
    for name, ref_path, s2_dir, s3_dir, input_dir in args.dataset:
        ref_path, s2_dir, s3_dir, input_dir = map(Path, (ref_path, s2_dir, s3_dir, input_dir))
        if not ref_path.exists():
            sys.exit(f"[{name}] reference not found: {ref_path}")
        applied_s2 = s2_dir / "applied_stats.json"
        if not applied_s2.exists():
            sys.exit(f"[{name}] {applied_s2} missing (needed as AML candidate set A)")
        owls = sorted(input_dir.glob("*.owl"))
        if len(owls) != 2:
            sys.exit(f"[{name}] expected 2 .owl in {input_dir}, found {len(owls)}")

        base_ns, cand_ns = _main_ns(owls[0]), _main_ns(owls[1])
        names1, names2 = _local_names(owls[0]), _local_names(owls[1])

        # Reference + AML candidate set as namespace-qualified pairs.
        R_pairs = _reference_qpairs(ref_path, base_ns, cand_ns)
        R_keys = {frozenset(p) for p in R_pairs}
        # Full AML candidate set — from the raw AML alignment, not applied_stats
        # (which drops many-to-one pairs when collapsing).
        A_pairs = _aml_qpairs(owls[0], owls[1], base_ns, cand_ns)
        # AML false-positives = AML pairs NOT in the reference (to test measure 2).
        A_fp = [p for p in A_pairs if frozenset(p) not in R_keys]

        has_s3 = (s3_dir / "alignment_stats.json").exists() or (s3_dir / "arom_ontology.owl").exists()
        if not has_s3:
            print(f"  [{name}] scenario_3 outputs not found in {s3_dir} — measure 1 "
                  f"(rejected correct) skipped; run scenario_3.sh {name}")

        for m in _METHODS:
            # Measure 2 (accept AML-FP): built from scenario_2 (AML input).  A false
            # positive is "accepted" iff the method merged both its entities.
            uf2 = _method_uf(s2_dir, A_pairs, base_ns, cand_ns, names1, names2, m)
            accepted_aml_fp = (sum(1 for a, b in A_fp if uf2.same(a, b))
                               if uf2 is not None else None)
            # Measure 1 (reject correct): from scenario_3 (reference input).  A gold
            # pair is "rejected" iff the method did NOT merge both its entities.
            rejected_correct = None
            if has_s3:
                uf1 = _method_uf(s3_dir, R_pairs, base_ns, cand_ns, names1, names2, m)
                if uf1 is not None:
                    rejected_correct = sum(1 for a, b in R_pairs if not uf1.same(a, b))
            if accepted_aml_fp is None and rejected_correct is None:
                continue
            rows.append({
                "method": m, "dataset": name,
                "reference_total": len(R_pairs), "aml_total": len(A_pairs),
                "rejected_correct": rejected_correct,
                "accepted_aml_fp": accepted_aml_fp,
            })
        print(f"  [{name}] |R|={len(R_pairs)} |A|={len(A_pairs)} "
              f"measure1={'yes' if has_s3 else 'NO (no scenario_3)'}")

    # ── CSV ──────────────────────────────────────────────────────────────────
    fieldnames = ["method", "dataset", "reference_total", "aml_total",
                  "rejected_correct", "accepted_aml_fp"]
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {args.out_csv} ({len(rows)} rows)")

    # ── per-dataset chart (NO cross-dataset aggregation) ─────────────────────
    # Grid: one row per dataset (conference, human-mouse), two columns (the two
    # measures).  Each dataset keeps its own y-scale (conference ~10s vs
    # human-mouse ~1000s would otherwise be incomparable).
    methods: list[str] = []
    for r in rows:
        if r["method"] not in methods:
            methods.append(r["method"])
    datasets: list[str] = []
    for r in rows:
        if r["dataset"] not in datasets:
            datasets.append(r["dataset"])
    lookup = {(r["method"], r["dataset"]): r for r in rows}

    # Uniform muted blue + black edge — same palette as the other thesis charts
    # (tests/analiza/plot_pct.py).
    BAR_COLOR = "#4472C4"
    measures = [
        ("rejected_correct", "Rejected correct alignments\n(reference input; lower = better)"),
        ("accepted_aml_fp", "Accepted AML false-positives\n(AML input; lower = better)"),
    ]

    # AMBIGUOUS cell(s): Boomer's human-mouse rejected_correct exists ONLY thanks
    # to the artificial p_equiv cap (0.99) on the reference ptable — without it
    # Boomer's solver fails ('No possible resolution of perplexity') → 0/undefined.
    # ONLY this single bar is hatched and labelled "<capped>/0".  Boomer's other
    # bars (conference, and accepted_aml_fp from the AML run) have no such issue.
    FLAGGED_CELLS = set() if args.no_flag else {("Boomer", "human-mouse", "rejected_correct")}

    fig, axes = plt.subplots(len(datasets), 2, figsize=(12, 5 * len(datasets)),
                             squeeze=False)
    for di, ds in enumerate(datasets):
        for mi, (metric, title) in enumerate(measures):
            ax = axes[di][mi]
            vals = [lookup.get((m, ds), {}).get(metric) for m in methods]
            bars = ax.bar(methods, [v or 0 for v in vals], color=BAR_COLOR,
                          edgecolor="black", linewidth=0.5)
            labels = []
            for bar, m, v in zip(bars, methods, vals):
                flagged = (m, ds, metric) in FLAGGED_CELLS
                if flagged:
                    bar.set_hatch("///")
                if v is None:
                    labels.append("n/a")
                elif flagged:
                    labels.append(f"{v}/0")       # with-cap / without-cap (crash)
                else:
                    labels.append(str(v))
            ax.bar_label(bars, labels=labels, padding=3)
            ax.axhline(0, color="black", linewidth=0.6)
            ax.set_title(f"{ds} — {title}")
            ax.set_ylabel("count")
            ax.tick_params(axis="x", rotation=20)
            ax.margins(y=0.2)

    fig.suptitle(args.title)
    if FLAGGED_CELLS:
        fig.text(0.5, 0.005,
                 "Hatched bar (Boomer, human-mouse rejected): relies on an artificial "
                 "p_equiv cap (0.99); uncapped Boomer fails to resolve the reference → 0/undefined.",
                 ha="center", fontsize=8, style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1) if FLAGGED_CELLS else None)
    fig.savefig(args.out_jpg, dpi=150)
    print(f"  wrote {args.out_jpg}")


if __name__ == "__main__":
    main()
