#!/usr/bin/env python3
"""Compute 1-5 scores per dimension per method from aggregated CSVs.

Each dimension averages 1-5 sub-scores of its constituent technical metrics
(only metrics with an unambiguous "better" direction are included; ambiguous
ones like raw breadth or applied_alignments count are excluded).

Per-metric scoring functions are absolute (not rank-based) so the resulting
score is meaningful on its own, not just relative to the four compared
methods.  Output CSV: rows = methods, cols = dimensions.
"""

import csv
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ANALIZA = REPO / "tests" / "analiza"
SCEN_OUT = REPO / "tests" / "scenarios" / "outputs"

METHODS = ["AROM", "CoMerger", "Boomer", "Our Solution"]
DATASETS = ["conference-s2", "human-mouse-s2", "acm-union-s2", "swo-union-s2"]
GRAPH_OF_METHOD = {
    "AROM": "arom_ontology",
    "CoMerger": "comerger_ontology",
    "Boomer": "boomer_ontology",
    "Our Solution": "merged_ontology",
}


def clamp(v: float, lo: float = 1.0, hi: float = 5.0) -> float:
    return max(lo, min(hi, v))


def read_csv_indexed(path: Path, key_col: str = "dataset") -> tuple[list[str], dict[str, dict[str, float]]]:
    with path.open() as fh:
        reader = csv.reader(fh)
        header = next(reader)
        cols = header[1:]
        data: dict[str, dict[str, float]] = {}
        for row in reader:
            data[row[0]] = {c: float(v) if v else float("nan") for c, v in zip(cols, row[1:])}
    return cols, data


def extract_from_mir(metric: str) -> dict[str, dict[str, float]]:
    """Extract a metric from m_i_raport CSVs across all datasets.
    Returns {method: {dataset: value}}."""
    out: dict[str, dict[str, float]] = {m: {} for m in METHODS}
    for ds in DATASETS:
        p = SCEN_OUT / ds / f"m_i_raport_{ds}.csv"
        with p.open() as fh:
            lines = [ln for ln in fh if not ln.lstrip().lstrip('"').startswith('#')]
        for row in csv.DictReader(lines):
            if row.get("section") != "metrics" or row.get("metric") != metric:
                continue
            for method, graph_name in GRAPH_OF_METHOD.items():
                if row.get("graph") == graph_name:
                    val = row.get("value", "")
                    out[method][ds] = float(val) if val else float("nan")
    return out


def avg_across_datasets(values: dict[str, float], exclude: set[str] = set()) -> float:
    vals = [v for ds, v in values.items() if ds not in exclude and v == v]
    return sum(vals) / len(vals) if vals else float("nan")


# ─── Scoring functions ────────────────────────────────────────────────────────

def f_cycles(c: float) -> float:
    """Cycle count: 0 → 5, 48+ → 1.  Lower is better.
    Calibrated so Our Solution (~35 avg cycles) lands at ~2 — meaningful penalty
    for being the only method introducing is-a cycles, without zeroing out."""
    return clamp(5 - c / 12)


def f_arc_change(p: float) -> float:
    """ARC % change vs Naive Union (negative = orphan reduction, more negative = better)."""
    return clamp(1 + max(0.0, -p) / 5)


def f_depth_change(p: float) -> float:
    """avg_depth % change vs NU.  Increase (positive) rewarded; decrease penalised."""
    return clamp(3 + p / 5)


def f_max_depth_change(p: float) -> float:
    """max_depth % change vs NU.  Same shape as avg_depth."""
    return clamp(3 + p / 5)


def f_connectivity(r: float) -> float:
    """connectivity_ratio in [0,1]; higher → better."""
    return clamp(1 + 4 * r)


def f_log_count_up(x: float) -> float:
    """Higher count = better.  log-scaled: 0→1, 10→~2.4, 100→~3.6, 1000→~4.9, 10000+→5."""
    return clamp(1 + math.log10(1 + max(0, x)) * 1.3)


def f_tcc(d: float) -> float:
    """Triples Count Change.  Positive (added triples) > 0 = good; negative penalised.
    Linear within bounds: -2000→1, 0→3, +2000→5."""
    return clamp(3 + d / 1000)


def f_sur(s: float) -> float:
    """Syntactic Uniqueness Ratio [0,1].  Higher → better."""
    return clamp(1 + 4 * s)


def f_sr(s: float) -> float:
    """Structural Redundancy [0,1].  Lower → better."""
    return clamp(5 - 4 * s)


def f_tpr(t: float) -> float:
    """TPR [0,1].  Higher → better."""
    return clamp(1 + 4 * t)


def f_mdr_change(d: float) -> float:
    """Multi D/R Δ per applied alignment.  Negative or 0 = no penalty.
    Positive (introduced conflicts) penalised: 0→5, +2→1."""
    return clamp(5 - max(0.0, d) * 2)


def f_selectivity(rejection_pct: float) -> float:
    """% reduction in applied alignments vs Applied Alignments baseline
    (negative value in input CSV means rejection).  Higher rejection = better
    selectivity — method is filtering bad alignments. 0%→1, 40%+→5."""
    rejection = max(0.0, -rejection_pct)
    return clamp(1 + rejection / 8)


def f_coverage(r: float) -> float:
    """Coverage ratio [0,1].  Higher → better."""
    return clamp(1 + 4 * r)


# ─── Per-dimension score builders ─────────────────────────────────────────────

def score_sc(method: str, cycle_csv: Path) -> float:
    _, data = read_csv_indexed(cycle_csv)
    vals = {ds: row[method] for ds, row in data.items()}
    return f_cycles(avg_across_datasets(vals))


def score_hiq(method: str) -> float:
    """HIQ averages 4 sub-scores: ARC reduction, depth, max_depth, connectivity."""
    # HIQ pct CSVs (raw values per method per dataset)
    hiq_dir = ANALIZA / "hierarchy_integration_quality"
    # Average each metric ABSOLUTELY then compute % vs NU using the same data.
    # Simpler: use the pct-change aggregate (already vs NU, ex swo) where possible
    # — values per method.
    pct_csv = hiq_dir / "hiq_pct_change.csv"
    if pct_csv.exists():
        with pct_csv.open() as fh:
            r = list(csv.reader(fh))
        cols = r[0][1:]
        row = next(rr for rr in r[1:] if rr[0] == method)
        d = dict(zip(cols, [float(x) if x else float("nan") for x in row[1:]]))
        # Pick metrics with clear direction
        arc_pct = d.get("ARC", float("nan"))
        depth_pct = d.get("average_depth", float("nan"))
        # max_breadth excluded — ambiguous; max_depth not in this aggregate
        # Fall back: just use ARC + avg_depth for HIQ
        scores = []
        if arc_pct == arc_pct: scores.append(f_arc_change(arc_pct))
        if depth_pct == depth_pct: scores.append(f_depth_change(depth_pct))

    # Connectivity ratio — extract directly from m_i_raport
    cr_data = extract_from_mir("connectivity_ratio")
    cr_avg = avg_across_datasets(cr_data[method])
    if cr_avg == cr_avg:
        scores.append(f_connectivity(cr_avg))

    return sum(scores) / len(scores) if scores else float("nan")


def score_kc(method: str) -> float:
    """KC averages NCRC, NIRC, TCC sub-scores."""
    kc_dir = ANALIZA / "knowledge_completeness"
    # NCRC + NIRC mean (excludes swo for CORC, but we use NCRC/NIRC which aren't filtered)
    # Read raw and average across 4 datasets ourselves (no exclusions for KC)
    _, ncrc_raw = read_csv_indexed(kc_dir / "new_cross_onto_relations_count.csv")
    _, nirc_raw = read_csv_indexed(kc_dir / "new_intra_onto_relations_count.csv")
    _, tcc_raw = read_csv_indexed(kc_dir / "triple_count_delta.csv")
    ncrc_avg = avg_across_datasets({ds: row[method] for ds, row in ncrc_raw.items()})
    nirc_avg = avg_across_datasets({ds: row[method] for ds, row in nirc_raw.items()})
    tcc_avg = avg_across_datasets({ds: row[method] for ds, row in tcc_raw.items()})
    scores = [f_log_count_up(ncrc_avg), f_log_count_up(nirc_avg), f_tcc(tcc_avg)]
    return sum(scores) / len(scores)


def score_conciseness(method: str) -> float:
    """C averages SUR and (1-SR) sub-scores."""
    c_dir = ANALIZA / "conciseness"
    _, sur_raw = read_csv_indexed(c_dir / "syntactic_uniqueness_ratio.csv")
    _, sr_raw = read_csv_indexed(c_dir / "structural_redundancy.csv")
    sur_avg = avg_across_datasets({ds: row[method] for ds, row in sur_raw.items()})
    sr_avg = avg_across_datasets({ds: row[method] for ds, row in sr_raw.items()})
    return (f_sur(sur_avg) + f_sr(sr_avg)) / 2


def score_accuracy(method: str) -> float:
    a_dir = ANALIZA / "accuracy"
    _, tpr_raw = read_csv_indexed(a_dir / "triple_preservation_ratio.csv")
    return f_tpr(avg_across_datasets({ds: row[method] for ds, row in tpr_raw.items()}))


def score_dc(method: str) -> float:
    """DC averages two sub-scores:
       1. Multi D/R Δ per applied alignment (lower = better; doesn't introduce conflicts)
       2. Alignment selectivity — rejection rate vs Applied Alignments baseline
          (rewarding methods that filter bad alignments)
    """
    dc_dir = ANALIZA / "domain_coherence"
    _, mdr_raw = read_csv_indexed(dc_dir / "multi_domain_range_change_per_alignment.csv")
    mdr_avg = avg_across_datasets({ds: row[method] for ds, row in mdr_raw.items()})
    s_mdr = f_mdr_change(mdr_avg)

    # Selectivity: read aggregated pct-change CSV (single value per method)
    sel_csv = dc_dir / "domain_coherence_combined.csv"
    rejection_pct = 0.0
    if sel_csv.exists():
        with sel_csv.open() as fh:
            r = list(csv.reader(fh))
        cols = r[0][1:]
        for row in r[1:]:
            if row[0] == method:
                d = dict(zip(cols, row[1:]))
                aa_pct = d.get("Applied Alignments", "")
                if aa_pct:
                    rejection_pct = float(aa_pct)
                break
    s_sel = f_selectivity(rejection_pct)
    return (s_mdr + s_sel) / 2


def score_u(method: str) -> float:
    """U uses only CCR (Comment Coverage Ratio).
    ACR is excluded because labels are trivially preserved by naive collapse
    (artefakt — nie różnicuje semantyki dokumentacji)."""
    u_dir = ANALIZA / "understandability"
    _, ccr_raw = read_csv_indexed(u_dir / "comment_coverage_ratio.csv")
    ccr_avg = avg_across_datasets({ds: row[method] for ds, row in ccr_raw.items()})
    return f_coverage(ccr_avg)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("radar_scores.csv")

    sc_csv = ANALIZA / "structural_coherence" / "cycle_count.csv"

    rows: list[dict[str, float]] = []
    for method in METHODS:
        row = {
            "method": method,
            "SC":  score_sc(method, sc_csv),
            "HIQ": score_hiq(method),
            "KC":  score_kc(method),
            "C":   score_conciseness(method),
            "A":   score_accuracy(method),
            "DC":  score_dc(method),
            "U":   score_u(method),
        }
        rows.append(row)

    cols = ["method", "SC", "HIQ", "KC", "C", "A", "DC", "U"]
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([r["method"]] + [f"{r[c]:.2f}" for c in cols[1:]])

    print(f"wrote {out}\n")
    # Pretty print
    print(f"{'method':<14}" + "".join(f"{c:>7}" for c in cols[1:]))
    for r in rows:
        print(f"{r['method']:<14}" + "".join(f"{r[c]:>7.2f}" for c in cols[1:]))


if __name__ == "__main__":
    main()
