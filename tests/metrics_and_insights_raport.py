#!/usr/bin/env python3
"""
Combined Metrics & Insights report comparing multiple scenario outputs.

Usage:
    uv run python tests/metrics_and_insights_raport.py \\
        --inputs tests/inputs/<dataset> \\
        --output <path-to-output.html> \\
        <scenario_dir_1> <scenario_dir_2> [scenario_dir_N...]

Each scenario directory must contain merged_ontology.owl.  Optional files
read when present: applied_alignments.owl, insights.csv, alignment_stats.json.

Produces:
    <output>.html  — full report with three sections:
                     (1) metrics per scenario (like metrics_def.html),
                     (2) full insights per scenario (all envs from insights.csv),
                     (3) comparison of merged_ontology metric values across all
                         scenarios with deltas vs the first (baseline) scenario.
    <output>.csv   — same data as flat multi-section CSV.

Reuses functions from tests/metrics_def.py — no logic duplication.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from rdflib import Graph, URIRef

sys.path.insert(0, str(Path(__file__).parent))
from metrics_def import (  # noqa: E402
    _CATEGORIES,
    _COLUMN_DISPLAY,
    _REGISTRY,
    _SOURCE_BORDER,
    _cat_badges,
    _compute_self_metrics,
    _compute_suspected_counts,
    _fmt,
    _fmt_applied,
    _load_graph,
    _reasoner_check,
)

# ── Per-scenario computation ───────────────────────────────────────────────────


def _compute_scenario(
    out_dir: Path,
    onto1: Graph,
    onto2: Graph,
    union: Graph,
    onto1_entities: set[URIRef],
    onto2_entities: set[URIRef],
) -> dict | None:
    merged_path = out_dir / "merged_ontology.owl"
    if not merged_path.exists():
        print(
            f"  WARNING: {merged_path} not found — skipping scenario {out_dir.name}",
            file=sys.stderr,
        )
        return None

    applied_path = out_dir / "applied_alignments.owl"
    boomer_path = out_dir / "boomer_ontology.owl"
    arom_path = out_dir / "arom_ontology.owl"
    comerger_path = out_dir / "comerger_ontology.owl"
    insights_path = out_dir / "insights.csv"
    alignment_stats_path = out_dir / "alignment_stats.json"
    boomer_stats_path = out_dir / "boomer_stats.json"
    arom_stats_path = out_dir / "arom_stats.json"
    comerger_stats_path = out_dir / "comerger_stats.json"

    merged = _load_graph(str(merged_path))
    applied = _load_graph(str(applied_path)) if applied_path.exists() else None
    boomer = _load_graph(str(boomer_path)) if boomer_path.exists() else None
    arom = _load_graph(str(arom_path)) if arom_path.exists() else None
    comerger = _load_graph(str(comerger_path)) if comerger_path.exists() else None
    arom_provenance: dict[str, dict[str, str]] | None = None
    if arom is not None and arom_stats_path.exists():
        arom_provenance = json.loads(
            arom_stats_path.read_text(encoding="utf-8")
        ).get("code_provenance")

    applied_stats_path = out_dir / "applied_stats.json"
    applied_provenance: dict[str, dict[str, str]] | None = None
    if applied is not None and applied_stats_path.exists():
        applied_provenance = json.loads(
            applied_stats_path.read_text(encoding="utf-8")
        ).get("code_provenance")

    boomer_provenance: dict[str, dict[str, str]] | None = None
    if boomer is not None and boomer_stats_path.exists():
        boomer_provenance = json.loads(
            boomer_stats_path.read_text(encoding="utf-8")
        ).get("code_provenance")

    graphs: dict[str, Graph] = {"union_input": union, "merged_ontology": merged}
    if applied is not None:
        graphs["applied_alignments"] = applied
    if arom is not None:
        graphs["arom_ontology"] = arom
    if comerger is not None:
        graphs["comerger_ontology"] = comerger
    if boomer is not None:
        graphs["boomer_ontology"] = boomer

    relabeling_map: dict[str, str] | None = None
    relabeling_path = out_dir / "relabeling_map.json"
    if relabeling_path.exists():
        relabeling_map = json.loads(relabeling_path.read_text(encoding="utf-8"))
        print(f"  relabeling_map: {len(relabeling_map)} entries")

    # Read stats sidecars before the metrics loop so we can pass authoritative
    # applied_alignments_count to _compute_self_metrics for every tool.  This
    # keeps per-alignment metrics (corc_per_applied, multi_d/r_change_per_alignment)
    # consistent with the "applied_alignments" column reported in the CSV.
    alignment_stats: dict | None = None
    llm_applied_count: int | None = None
    if alignment_stats_path.exists():
        alignment_stats = json.loads(alignment_stats_path.read_text(encoding="utf-8"))
        llm_applied_count = int(alignment_stats.get("applied_count", 0)) or None

    # Build a graph_name -> applied_count map from the same sources used in
    # the post-loop block that fills self_metrics[…]["applied_alignments"].
    applied_count_by_graph: dict[str, int] = {}
    if alignment_stats is not None:
        total_align = int(alignment_stats.get("total_alignments", 0))
        if "applied_alignments" in graphs:
            applied_count_by_graph["applied_alignments"] = total_align
        if "arom_ontology" in graphs:
            applied_count_by_graph["arom_ontology"] = total_align
        if llm_applied_count is not None and "merged_ontology" in graphs:
            applied_count_by_graph["merged_ontology"] = llm_applied_count
    if comerger_stats_path.exists() and "comerger_ontology" in graphs:
        cstats = json.loads(comerger_stats_path.read_text(encoding="utf-8"))
        applied_count_by_graph["comerger_ontology"] = int(cstats.get("applied_equiv_total", 0))
    if boomer_stats_path.exists() and "boomer_ontology" in graphs:
        bstats = json.loads(boomer_stats_path.read_text(encoding="utf-8"))
        applied_count_by_graph["boomer_ontology"] = int(bstats.get("accepted_equiv_count", 0))

    metrics: dict[str, dict[str, float | None]] = {}
    for name, g in graphs.items():
        print(f"  computing metrics: {name} ({len(g)} triples) …", flush=True)
        union_arg = None if name == "union_input" else union
        prov = (
            arom_provenance if name == "arom_ontology"
            else applied_provenance if name == "applied_alignments"
            else boomer_provenance if name == "boomer_ontology"
            else None
        )
        rmap = relabeling_map if name == "merged_ontology" else None
        aac = applied_count_by_graph.get(name)
        metrics[name] = _compute_self_metrics(
            g, onto1_entities, onto2_entities, union_arg,
            arom_provenance=prov, relabeling_map=rmap,
            applied_alignments_count=aac,
        )
        metrics[name]["unsatisfiable_classes"] = None  # HermiT disabled

    suspected_counts: dict[str, int] = {}
    if alignment_stats is not None:
        total = float(alignment_stats.get("total_alignments", 0))
        applied_count = float(alignment_stats.get("applied_count", 0))
        rejected = alignment_stats.get("rejected_alignments", [])
        rejected_count = int(total - applied_count)

        if "union_input" in metrics:
            metrics["union_input"]["applied_alignments"] = 0.0
        if "applied_alignments" in metrics:
            metrics["applied_alignments"]["applied_alignments"] = total
        if "merged_ontology" in metrics:
            metrics["merged_ontology"]["applied_alignments"] = applied_count
        # AROM has no rejection — applies all alignments ≥ threshold (default 0.0)
        if "arom_ontology" in metrics:
            metrics["arom_ontology"]["applied_alignments"] = total
        # CoMerger: prefer authoritative count from comerger_stats.json sidecar
        # (HModel.getEqClasses() etc.).  owl:equivalentClass count in output OWL
        # is unreliable for large ontologies — CoMerger may not materialize all
        # collapsed equiv groups as triples.
        if "comerger_ontology" in metrics and comerger is not None:
            if comerger_stats_path.exists():
                cstats = json.loads(comerger_stats_path.read_text(encoding="utf-8"))
                metrics["comerger_ontology"]["applied_alignments"] = float(
                    cstats.get("applied_equiv_total", 0)
                )
            else:
                from rdflib.namespace import OWL as _OWL
                equiv_count = sum(1 for _ in comerger.triples((None, _OWL.equivalentClass, None)))
                metrics["comerger_ontology"]["applied_alignments"] = float(equiv_count)

        if applied is not None and rejected:
            tainted_uris = {URIRef(a["entity1"]) for a in rejected}
            suspected_counts = _compute_suspected_counts(
                applied, onto1_entities, onto2_entities, tainted_uris
            )
            suspected_counts["applied_alignments"] = rejected_count

    # Boomer accepted-equiv count (from sidecar written by apply_boomer.py)
    if boomer_stats_path.exists() and "boomer_ontology" in metrics:
        bstats = json.loads(boomer_stats_path.read_text(encoding="utf-8"))
        metrics["boomer_ontology"]["applied_alignments"] = float(
            bstats.get("accepted_equiv_count", 0)
        )

    insights_rows: list[dict] = []
    if insights_path.exists():
        with insights_path.open(encoding="utf-8") as f:
            insights_rows = list(csv.DictReader(f))

    return {
        "label": out_dir.name,
        "out_dir": out_dir,
        "metrics": metrics,
        "suspected_counts": suspected_counts,
        "insights_rows": insights_rows,
        "alignment_stats": alignment_stats,
        "has_applied": applied is not None,
        "has_boomer": boomer is not None,
        "has_arom": arom is not None,
        "has_comerger": comerger is not None,
        # CoMerger's holistic merge blows up (Pellet RBox) on ontologies with
        # many object-property chains and is capped by comerger.sh; the wrapper
        # writes this marker instead of merged_ontology.owl when it times out.
        "comerger_timeout": (out_dir / "comerger_timeout.txt").exists(),
    }


# ── Comparison helpers ─────────────────────────────────────────────────────────


def _delta_direction(metric_name: str, baseline: float, value: float) -> str:
    """Return 'better' / 'worse' / 'neutral' based on the metric's target."""
    if baseline == value:
        return "neutral"
    meta = _REGISTRY.get(metric_name, {})
    target = meta.get("target", "").lower()
    if "= 1.0" in target:
        return "better" if abs(value - 1.0) < abs(baseline - 1.0) else "worse"
    if "= 0" in target or "low" in target:
        return "better" if value < baseline else "worse"
    if "high" in target:
        return "better" if value > baseline else "worse"
    return "neutral"


def _fmt_compare_cell(
    metric_name: str, baseline: float | None, value: float | None, is_baseline: bool
) -> str:
    if value is None:
        return '<td class="na">N/A</td>'
    base_text = (
        f"{int(value)}" if value == int(value) and abs(value) < 1e9 else f"{value:.4f}"
    )
    if is_baseline or baseline is None:
        return f'<td class="num">{base_text}</td>'
    direction = _delta_direction(metric_name, baseline, value)
    raw_diff = value - baseline
    meta = _REGISTRY.get(metric_name, {})
    target = meta.get("target", "")
    is_ratio = "= 1.0" in target or (0 < abs(baseline) <= 1.0 and abs(value) <= 1.0)
    if is_ratio and baseline != 0:
        diff_text = f"{100 * raw_diff / baseline:+.1f}%"
    elif value == int(value) and baseline == int(baseline) and abs(value) < 1e9:
        diff_text = f"{int(raw_diff):+d}"
    else:
        diff_text = f"{raw_diff:+.4f}"
    return (
        f'<td class="num">'
        f'<span class="val">{base_text}</span> '
        f'<span class="delta delta-{direction}">{diff_text}</span>'
        f"</td>"
    )


# ── HTML rendering ─────────────────────────────────────────────────────────────


_HTML_CSS = """
body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a;
       background: #fafafa; }
h1   { font-size: 1.5rem; margin: 0 0 0.3rem; }
h2   { font-size: 1.15rem; margin: 2rem 0 0.8rem;
       border-bottom: 2px solid #d0d0d0; padding-bottom: 0.3rem; }
h3   { font-size: 1.0rem; margin: 1.2rem 0 0.5rem; color: #2c3e50; }
p.sub { color: #666; font-size: 0.9rem; margin: 0 0 1rem; }
.scenario-section { background: #fff; border: 1px solid #ddd; border-radius: 8px;
                    padding: 1rem 1.4rem; margin-bottom: 1.2rem; }
.scenario-meta { font-size: 0.82rem; color: #666; margin-bottom: 0.6rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
th, td { padding: 0.45rem 0.6rem; text-align: left; vertical-align: top;
         border: 1px solid #d8d8d8; }
th { background: #2c3e50; color: #fff; font-weight: 600; white-space: nowrap; }
tr:nth-child(even) td { background: #f9f9f9; }
tr:hover td { background: #eef5fb; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.na  { text-align: center; color: #aaa; }
td.src { font-size: 0.78rem; white-space: nowrap; }
td.tgt { font-size: 0.78rem; color: #666; white-space: nowrap; }
td.cats { max-width: 220px; }
td.interp { font-size: 0.8rem; color: #444; max-width: 280px; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 3px;
         font-size: 0.7rem; margin: 1px; color: #fff; white-space: nowrap; }
.susp { color: #c0392b; font-size: 0.76rem; font-weight: 600;
        margin-left: 0.2rem; cursor: help; }
.delta { font-size: 0.78rem; font-weight: 600; margin-left: 0.3rem;
         font-variant-numeric: tabular-nums; }
.delta-better  { color: #2e7d32; }
.delta-worse   { color: #c62828; }
.delta-neutral { color: #888; }
tr.total td { background: #e8eef5 !important; font-weight: 700; }
"""


def _render_metrics_table(scenario: dict) -> str:
    rows_html: list[str] = []
    metrics = scenario["metrics"]
    suspected = scenario["suspected_counts"]
    has_applied = scenario["has_applied"]
    has_boomer = scenario["has_boomer"]
    has_arom = scenario["has_arom"]
    has_comerger = scenario["has_comerger"]
    for metric_name, meta in _REGISTRY.items():
        u_val = metrics.get("union_input", {}).get(metric_name)
        m_val = metrics.get("merged_ontology", {}).get(metric_name)
        a_val = (
            metrics.get("applied_alignments", {}).get(metric_name)
            if has_applied else None
        )
        b_val = (
            metrics.get("boomer_ontology", {}).get(metric_name)
            if has_boomer else None
        )
        ar_val = (
            metrics.get("arom_ontology", {}).get(metric_name)
            if has_arom else None
        )
        c_val = (
            metrics.get("comerger_ontology", {}).get(metric_name)
            if has_comerger else None
        )
        if all(v is None for v in (u_val, m_val, a_val, b_val, ar_val, c_val)):
            continue
        border = _SOURCE_BORDER.get(meta["source"], "#ccc")
        badges = _cat_badges(meta["categories"])
        susp = suspected.get(metric_name, 0)
        applied_cell = _fmt_applied(a_val, susp) if has_applied else ""
        arom_cell = _fmt(ar_val) if has_arom else ""
        comerger_cell = _fmt(c_val) if has_comerger else ""
        boomer_cell = _fmt(b_val) if has_boomer else ""
        rows_html.append(
            f'    <tr style="border-left: 3px solid {border}">'
            f"<td><strong>{_METRIC_DISPLAY.get(metric_name, metric_name)}</strong></td>"
            f"{_fmt(u_val)}"
            f"{applied_cell}"
            f"{arom_cell}"
            f"{comerger_cell}"
            f"{boomer_cell}"
            f"{_fmt(m_val)}"
            f'<td class="tgt">{meta["target"]}</td>'
            f'<td class="src">{meta["source"]}</td>'
            f'<td class="cats">{badges}</td>'
            f'<td class="interp">{meta["interpretation"]}</td>'
            f"</tr>"
        )
    applied_header  = f"<th>{_COLUMN_DISPLAY['applied_alignments']}</th>"  if has_applied else ""
    arom_header     = f"<th>{_COLUMN_DISPLAY['arom_ontology']}</th>"       if has_arom else ""
    comerger_header = f"<th>{_COLUMN_DISPLAY['comerger_ontology']}</th>"   if has_comerger else ""
    boomer_header   = f"<th>{_COLUMN_DISPLAY['boomer_ontology']}</th>"     if has_boomer else ""
    return f"""<table>
  <thead><tr>
    <th>Metric</th><th>{_COLUMN_DISPLAY['union_input']}</th>{applied_header}{arom_header}{comerger_header}{boomer_header}<th>{_COLUMN_DISPLAY['merged_ontology']}</th>
    <th>Target</th><th>Source</th><th>Categories</th><th>Interpretation</th>
  </tr></thead>
  <tbody>
{chr(10).join(rows_html)}
  </tbody>
</table>"""


def _render_insights_table(scenario: dict) -> str:
    rows = scenario["insights_rows"]
    if not rows:
        return '<p style="color:#888;font-size:0.85rem;">insights.csv brak w tej ścieżce</p>'
    header = list(rows[0].keys())
    body_rows: list[str] = []
    for r in rows:
        is_total = str(r.get("env", "")).upper() == "TOTAL"
        tr_cls = ' class="total"' if is_total else ""
        cells = "".join(f'<td class="num">{r[c]}</td>' for c in header)
        body_rows.append(f"    <tr{tr_cls}>{cells}</tr>")
    return f"""<table>
  <thead><tr>{"".join(f"<th>{h}</th>" for h in header)}</tr></thead>
  <tbody>
{chr(10).join(body_rows)}
  </tbody>
</table>"""


def _render_comparison_table(scenarios: list[dict], graph_name: str) -> str:
    """Render comparison table for a specific graph column ('merged_ontology' or 'boomer_ontology')."""
    baseline = scenarios[0]
    labels = [s["label"] for s in scenarios]

    headers = [
        f"<th>{labels[0]} <span style='font-weight:400;color:#aaa;'>(baseline)</span></th>"
    ]
    for label in labels[1:]:
        headers.append(f"<th>{label}</th>")

    body_rows: list[str] = []
    for metric_name, meta in _REGISTRY.items():
        baseline_val = baseline["metrics"].get(graph_name, {}).get(metric_name)
        scenario_vals = [
            s["metrics"].get(graph_name, {}).get(metric_name) for s in scenarios
        ]
        if all(v is None for v in scenario_vals):
            continue
        border = _SOURCE_BORDER.get(meta["source"], "#ccc")
        cells = [
            _fmt_compare_cell(metric_name, None, scenario_vals[0], is_baseline=True)
        ]
        for v in scenario_vals[1:]:
            cells.append(
                _fmt_compare_cell(metric_name, baseline_val, v, is_baseline=False)
            )
        body_rows.append(
            f'    <tr style="border-left: 3px solid {border}">'
            f"<td><strong>{_METRIC_DISPLAY.get(metric_name, metric_name)}</strong></td>"
            f"{''.join(cells)}"
            f'<td class="tgt">{meta["target"]}</td>'
            f"</tr>"
        )

    return f"""<table>
  <thead><tr>
    <th>Metric</th>{"".join(headers)}<th>Target</th>
  </tr></thead>
  <tbody>
{chr(10).join(body_rows)}
  </tbody>
</table>
<p style="font-size:0.82rem;color:#666;margin-top:0.5rem;">
  <span class="delta delta-better">+/-</span> zielony = bliżej target wg <code>_REGISTRY</code>;
  <span class="delta delta-worse">+/-</span> czerwony = gorzej;
  <span class="delta delta-neutral">+/-</span> szary = context-dependent.
  Procenty dla metryk ratio (target = 1.0 lub baseline ∈ (0,1]), liczby absolutne dla pozostałych.
</p>"""


def _render_legend() -> str:
    cat_html = "\n".join(
        f'    <span class="badge" style="background:{color}">{cat}</span>'
        for cat, (_, color) in _CATEGORIES.items()
    )
    return f"""<div style="margin-top:1.5rem;font-size:0.82rem;color:#555;">
  <div><strong>Categories:</strong></div>
  <div style="margin-top:0.3rem;">
{cat_html}
  </div>
  <div style="margin-top:0.6rem;">
    <strong>Source border:</strong>
    <span style="display:inline-block;width:4px;height:14px;background:{_SOURCE_BORDER["self-implemented"]};vertical-align:middle;margin-right:4px;"></span>
    self-implemented &nbsp;
    <span style="display:inline-block;width:4px;height:14px;background:{_SOURCE_BORDER["hermit_reasoner"]};vertical-align:middle;margin-right:4px;"></span>
    hermit_reasoner
  </div>
</div>"""


def _align_stats_label(stats: dict | None) -> str:
    if not stats:
        return "brak"
    applied = int(stats.get("applied_count", 0))
    total = int(stats.get("total_alignments", 0))
    return f"applied {applied}/{total}"


def _scenario_metrics_block(s: dict) -> str:
    applied_mark = "✓" if s["has_applied"] else "✗"
    arom_mark = "✓" if s["has_arom"] else "✗"
    comerger_timeout = s.get("comerger_timeout", False)
    comerger_mark = (
        "⏱ timeout (3 min)" if comerger_timeout
        else "✓" if s["has_comerger"] else "✗"
    )
    boomer_mark = "✓" if s["has_boomer"] else "✗"
    align_label = _align_stats_label(s["alignment_stats"])
    # Explicit banner so the missing CoMerger column is not mistaken for a plain
    # "not run" — it was capped at the 3-minute limit (see comerger.sh).
    timeout_note = (
        '<div style="margin:0.4rem 0;padding:6px 10px;border-left:4px solid #e67e22;'
        'background:#fdf3e7;color:#8a5000;font-size:0.85rem;">'
        "⏱ <strong>CoMerger:</strong> przekroczono limit 3&nbsp;min — kolumna CoMerger "
        "pominięta (brak danych)."
        "</div>"
        if comerger_timeout else ""
    )
    return (
        f'<div class="scenario-section"><h3>Scenariusz: <code>{s["label"]}</code></h3>'
        f'<div class="scenario-meta">'
        f"merged_ontology.owl: ✓ &nbsp; "
        f"applied_alignments.owl: {applied_mark} &nbsp; "
        f"arom_ontology.owl: {arom_mark} &nbsp; "
        f"comerger_ontology.owl: {comerger_mark} &nbsp; "
        f"boomer_ontology.owl: {boomer_mark} &nbsp; "
        f"alignment_stats: {align_label}"
        f"</div>"
        f"{timeout_note}"
        f"{_render_metrics_table(s)}</div>"
    )


def _build_html(scenarios: list[dict], inputs_dir: Path) -> str:
    summary = (
        f"<strong>{len(scenarios)}</strong> scenariuszy &nbsp;|&nbsp; "
        f"inputs: <code>{inputs_dir}</code> &nbsp;|&nbsp; "
        f"baseline: <code>{scenarios[0]['label']}</code>"
    )
    sec1 = "\n".join(_scenario_metrics_block(s) for s in scenarios)
    sec2 = "\n".join(
        f'<div class="scenario-section"><h3>Scenariusz: <code>{s["label"]}</code></h3>'
        f"{_render_insights_table(s)}</div>"
        for s in scenarios
    )
    sec3 = (
        '<div class="scenario-section">'
        + _render_comparison_table(scenarios, "merged_ontology")
        + "</div>"
    )
    sec4_html = ""
    if any(s["has_boomer"] for s in scenarios):
        sec4_html = (
            f"<h2>4. Porównanie <code>{_COLUMN_DISPLAY['boomer_ontology']}</code> — wszystkie scenariusze</h2>\n"
            '<div class="scenario-section">'
            + _render_comparison_table(scenarios, "boomer_ontology")
            + "</div>"
        )
    sec5_html = ""
    if any(s["has_arom"] for s in scenarios):
        sec5_html = (
            f"<h2>5. Porównanie <code>{_COLUMN_DISPLAY['arom_ontology']}</code> — wszystkie scenariusze</h2>\n"
            '<div class="scenario-section">'
            + _render_comparison_table(scenarios, "arom_ontology")
            + "</div>"
        )
    sec6_html = ""
    if any(s["has_comerger"] for s in scenarios):
        sec6_html = (
            f"<h2>6. Porównanie <code>{_COLUMN_DISPLAY['comerger_ontology']}</code> — wszystkie scenariusze</h2>\n"
            '<div class="scenario-section">'
            + _render_comparison_table(scenarios, "comerger_ontology")
            + "</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Metrics &amp; Insights Report</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<h1>Metrics &amp; Insights Report</h1>
<p class="sub">{summary}</p>

<h2>1. Metryki per scenariusz</h2>
{sec1}

<h2>2. Insights per scenariusz</h2>
{sec2}

<h2>3. Porównanie <code>{_COLUMN_DISPLAY['merged_ontology']}</code> — wszystkie scenariusze</h2>
{sec3}

{sec4_html}

{sec5_html}

{sec6_html}

{_render_legend()}
</body>
</html>"""


# ── CSV rendering ──────────────────────────────────────────────────────────────


def _build_csv_rows(scenarios: list[dict]) -> list[list[str]]:
    rows: list[list[str]] = []
    for s in scenarios:
        if s.get("comerger_timeout"):
            rows.append(
                [f"# NOTE: CoMerger timed out (3-min limit) for scenario "
                 f"'{s['label']}' — comerger_ontology column absent (no data)."]
            )
    rows.append(["# section: metrics (per scenario, per metric, per graph)"])
    rows.append(["section", "scenario", "metric", "graph", "value", "suspected"])
    for s in scenarios:
        for graph_name, graph_metrics in s["metrics"].items():
            for metric_name, value in graph_metrics.items():
                susp = (
                    s["suspected_counts"].get(metric_name, "")
                    if graph_name == "applied_alignments"
                    else ""
                )
                rows.append(
                    [
                        "metrics",
                        s["label"],
                        metric_name,
                        graph_name,
                        "" if value is None else str(value),
                        str(susp),
                    ]
                )

    rows.append([])
    rows.append(["# section: insights (per scenario, per env)"])
    for s in scenarios:
        if not s["insights_rows"]:
            continue
        header = list(s["insights_rows"][0].keys())
        rows.append(["section", "scenario"] + header)
        for r in s["insights_rows"]:
            rows.append(["insights", s["label"]] + [r[h] for h in header])

    def _emit_comparison_section(graph_name: str) -> None:
        rows.append([])
        rows.append(
            [f"# section: comparison ({graph_name} metric values across scenarios)"]
        )
        baseline = scenarios[0]
        labels = [s["label"] for s in scenarios]
        header = ["metric", labels[0] + "_baseline"]
        for label in labels[1:]:
            header += [label, label + "_delta_vs_baseline", label + "_direction"]
        rows.append(header)
        for metric_name in _REGISTRY:
            baseline_val = baseline["metrics"].get(graph_name, {}).get(metric_name)
            scenario_vals = [
                s["metrics"].get(graph_name, {}).get(metric_name) for s in scenarios
            ]
            if all(v is None for v in scenario_vals):
                continue
            row = [
                metric_name,
                "" if scenario_vals[0] is None else str(scenario_vals[0]),
            ]
            for v in scenario_vals[1:]:
                if v is None or baseline_val is None:
                    row += ["", "", ""]
                else:
                    row += [
                        str(v),
                        f"{v - baseline_val:+g}",
                        _delta_direction(metric_name, baseline_val, v),
                    ]
            rows.append(row)

    _emit_comparison_section("merged_ontology")
    if any(s["has_boomer"] for s in scenarios):
        _emit_comparison_section("boomer_ontology")
    if any(s["has_arom"] for s in scenarios):
        _emit_comparison_section("arom_ontology")
    if any(s["has_comerger"] for s in scenarios):
        _emit_comparison_section("comerger_ontology")
    return rows


# ── Charts (cross-scenario bar charts per category) ───────────────────────────

# Single best category per metric (user-provided mapping — distinct from
# _REGISTRY[m]["categories"] which sometimes lists two).  Charts are grouped
# by these keys: 7 files per scenario run, one per category.
_CATEGORY_TO_METRICS: dict[str, list[str]] = {
    "Structural Coherence":          ["cycle_count"],
    "Hierarchy Integration Quality": [
        "ARC", "connectivity_ratio", "average_depth",
        "max_depth", "average_breadth", "max_breadth",
    ],
    "Knowledge Completeness": [
        "cross_onto_relations_count",
        "corc_per_applied_alignment",
        "new_intra_onto_relations_count",
        "cross_onto_subclassof_count",
        "triple_count_delta",
    ],
    "Conciseness":         ["syntactic_uniqueness_ratio", "structural_redundancy"],
    "Accuracy":            ["triple_preservation_ratio"],
    "Domain Coherence":    ["applied_alignments", "multi_domain_range_count"],
    "Understandability":   ["annotation_coverage_ratio"],
}
_CATEGORY_SLUG: dict[str, str] = {
    "Structural Coherence":          "structural_coherence",
    "Hierarchy Integration Quality": "hierarchy_integration_quality",
    "Knowledge Completeness":        "knowledge_completeness",
    "Conciseness":                   "conciseness",
    "Accuracy":                      "accuracy",
    "Domain Coherence":              "domain_coherence",
    "Understandability":             "understandability",
}
# Color per method.  "Our Solution" multi-config variants get green shades.
_METHOD_COLORS: dict[str, str] = {
    "Naive Union":        "#7f8c8d",
    "Applied Alignments": "#bdc3c7",
    "AROM":               "#3498db",
    "CoMerger":           "#9b59b6",
    "Boomer":             "#e67e22",
    "Our Solution":       "#27ae60",
}
_OUR_SOLUTION_PALETTE = ["#27ae60", "#1e8449", "#52be80", "#16a085", "#0e6655", "#82e0aa"]

# Abbreviated / cleaned display names for chart subplot titles.
# Internal metric keys are unchanged everywhere else (registry, CSV, HTML tables).
_METRIC_DISPLAY: dict[str, str] = {
    "annotation_coverage_ratio":     "ACR",
    "comment_coverage_ratio":        "CCR",
    "applied_alignments":            "Applied Alignments",
    "multi_domain_range_count":      "Multi D/R",
    "multi_domain_range_change_per_alignment": "Multi D/R Change per Alignment",
    "structural_redundancy":         "Structural Redundancy",
    "connectivity_ratio":             "CR",
    "triple_preservation_ratio":      "TPR",
    "cross_onto_relations_count":     "CORC",
    "corc_per_applied_alignment":     "CORC per Applied Alignment",
    "new_intra_onto_relations_count": "NIRC",
    "cross_onto_subclassof_count":    "COSC",
    "new_cross_onto_relations_count": "NCRC",
    "triple_count_delta":             "Triples Count Change",
    "cycle_count":                    "Cycle Count",
    "average_depth":                  "Average Depth",
    "max_depth":                      "Max Depth",
    "average_breadth":                "Average Breadth",
    "max_breadth":                    "Max Breadth",
}


def _is_ratio_metric(metric_name: str) -> bool:
    """Detect whether a metric's value is conventionally in [0, 1] (ratio)."""
    target = _REGISTRY.get(metric_name, {}).get("target", "").lower()
    return ("= 1.0" in target) or ("ratio" in metric_name.lower())


def _should_use_log_scale(values: list[float]) -> bool:
    """Use log/symlog when max/min(positive) ratio > 20 (large spread across methods)."""
    pos = [v for v in values if v > 0]
    if len(pos) < 2:
        return False
    return max(pos) / min(pos) > 20


def _render_category_charts(scenarios: list[dict], out_dir: Path, file_prefix: str) -> list[Path]:
    """Generate cross-scenario bar-chart JPGs grouped by quality category.

    For each of the 7 categories, emit one JPG file.  Subplots = metrics in
    that category; bars per subplot = baseline methods + Our Solution variants.

    Special handling:
      - Domain Coherence: Naive Union excluded; bar labels show % vs Applied
        Alignments (the reference bar shows its absolute count).
      - ALC: dashed red reference line = avg(AROM, CoMerger, Boomer).
      - Log / symlog scale: auto-applied when max/min(positive) > 20× spread.

    Returns list of written paths.
    """
    import math
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not scenarios:
        return []

    baseline = scenarios[0]
    bmetrics = baseline["metrics"]

    # Build baseline methods list; colors keyed by display name for consistency.
    methods: list[tuple[str, str, str]] = []  # (display_label, color, graph_key)
    for graph_key, ok in [
        ("union_input",        "union_input" in bmetrics),
        ("applied_alignments", bool(baseline.get("has_applied")) and "applied_alignments" in bmetrics),
        ("arom_ontology",      bool(baseline.get("has_arom")) and "arom_ontology" in bmetrics),
        ("comerger_ontology",  bool(baseline.get("has_comerger")) and "comerger_ontology" in bmetrics),
        ("boomer_ontology",    bool(baseline.get("has_boomer")) and "boomer_ontology" in bmetrics),
    ]:
        if ok:
            disp = _COLUMN_DISPLAY[graph_key]
            methods.append((disp, _METHOD_COLORS[disp], graph_key))

    our_label = (
        lambda s: _COLUMN_DISPLAY["merged_ontology"]
        if len(scenarios) == 1
        else f"{_COLUMN_DISPLAY['merged_ontology']} ({s['label']})"
    )
    our_solutions: list[tuple[dict, str, str]] = [
        (s, our_label(s), _OUR_SOLUTION_PALETTE[i % len(_OUR_SOLUTION_PALETTE)])
        for i, s in enumerate(scenarios)
    ]

    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for category, category_metrics in _CATEGORY_TO_METRICS.items():
        present_metrics = [
            m for m in category_metrics
            if any(s["metrics"].get("merged_ontology", {}).get(m) is not None for s in scenarios)
        ]
        if not present_metrics:
            continue

        is_dc = category == "Domain Coherence"
        is_kc = category == "Knowledge Completeness"

        # Domain Coherence & Knowledge Completeness: Naive Union excluded (no cross-onto info).
        cat_methods = [t for t in methods if not ((is_dc or is_kc) and t[2] == "union_input")]
        all_labels = [m[0] for m in cat_methods] + [o[1] for o in our_solutions]
        all_colors = [m[1] for m in cat_methods] + [o[2] for o in our_solutions]

        n = len(present_metrics)
        cols = 1 if n == 1 else 2
        rows = math.ceil(n / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(7.5 * cols, 4.5 * rows), squeeze=False)
        fig.suptitle(category, fontsize=15, fontweight="bold")

        for idx, metric_name in enumerate(present_metrics):
            ax = axes[idx // cols][idx % cols]

            values: list[float] = []
            for _lbl, _clr, key in cat_methods:
                v = bmetrics.get(key, {}).get(metric_name)
                values.append(float(v) if v is not None else 0.0)
            for s, _lbl, _clr in our_solutions:
                v = s["metrics"].get("merged_ontology", {}).get(metric_name)
                values.append(float(v) if v is not None else 0.0)

            # Auto log/symlog for large-spread data (e.g. Knowledge Completeness).
            if _should_use_log_scale(values):
                if any(v == 0 for v in values):
                    ax.set_yscale("symlog", linthresh=1)
                else:
                    ax.set_yscale("log")

            bars = ax.bar(range(len(all_labels)), values, color=all_colors)
            ax.set_xticks(range(len(all_labels)))
            ax.set_xticklabels(all_labels, rotation=45, ha="right", fontsize=9)
            ax.set_title(_METRIC_DISPLAY.get(metric_name, metric_name), fontsize=11)
            ax.set_ylabel("ratio" if _is_ratio_metric(metric_name) else "value")
            ax.grid(axis="y", alpha=0.3)

            # Bar labels — applied_alignments uses % vs its own reference bar.
            # Other DC metrics (e.g. multi_domain_range_count) use regular labels.
            if is_dc and metric_name == "applied_alignments":
                applied_ref = bmetrics.get("applied_alignments", {}).get(metric_name)
                dc_labels: list[str] = []
                for _lbl, _clr, key in cat_methods:
                    v = float(bmetrics.get(key, {}).get(metric_name) or 0)
                    if key == "applied_alignments":
                        dc_labels.append(str(int(v)))
                    elif applied_ref and applied_ref > 0:
                        dc_labels.append(f"{(v - applied_ref) / applied_ref * 100:+.0f}%")
                    else:
                        dc_labels.append(str(int(v)))
                for s, _lbl, _clr in our_solutions:
                    v = float(s["metrics"].get("merged_ontology", {}).get(metric_name) or 0)
                    if applied_ref and applied_ref > 0:
                        dc_labels.append(f"{(v - applied_ref) / applied_ref * 100:+.0f}%")
                    else:
                        dc_labels.append(str(int(v)))
                ax.bar_label(bars, labels=dc_labels, fontsize=8, padding=2)
            else:
                fmt = "%.3f" if _is_ratio_metric(metric_name) else "%g"
                ax.bar_label(bars, fmt=fmt, fontsize=8, padding=2)

            # ALC and TPR: dashed red reference line = avg(AROM, CoMerger, Boomer).
            if metric_name in ("ALC", "triple_preservation_ratio"):
                ref_vals = [
                    float(bmetrics[k][metric_name])
                    for k in ("arom_ontology", "comerger_ontology", "boomer_ontology")
                    if bmetrics.get(k, {}).get(metric_name) is not None
                ]
                if ref_vals:
                    avg_ref = sum(ref_vals) / len(ref_vals)
                    val_fmt = ".3f" if _is_ratio_metric(metric_name) else ".0f"
                    ax.axhline(
                        y=avg_ref, color="#e74c3c", linestyle="--", linewidth=1.5,
                        alpha=0.85,
                        label=f"Avg(AROM, CoMerger, Boomer) = {avg_ref:{val_fmt}}",
                    )
                    ax.legend(fontsize=8, loc="lower right")

            target = _REGISTRY.get(metric_name, {}).get("target", "")
            if target:
                ax.text(
                    0.99, 0.97, f"target: {target}",
                    transform=ax.transAxes, fontsize=8, color="#666",
                    ha="right", va="top",
                )

        for idx in range(n, rows * cols):
            axes[idx // cols][idx % cols].axis("off")

        legend_handles = [
            plt.Rectangle((0, 0), 1, 1, color=c, label=lbl)
            for lbl, c in zip(all_labels, all_colors)
        ]
        legend_title = (
            "% values relative to Applied Alignments  (reference bar = absolute count)"
            if is_dc and "applied_alignments" in present_metrics else None
        )
        fig.legend(
            handles=legend_handles, loc="lower center",
            ncol=min(len(all_labels), 4),
            bbox_to_anchor=(0.5, -0.02), fontsize=9, frameon=False,
            title=legend_title, title_fontsize=8,
        )

        slug = _CATEGORY_SLUG[category]
        out_path = charts_dir / f"{file_prefix}_{slug}.jpg"
        bottom = 0.07 if is_dc else 0.04
        fig.tight_layout(rect=(0, bottom, 1, 0.96))
        fig.savefig(out_path, dpi=150, format="jpg", bbox_inches="tight")
        plt.close(fig)
        written.append(out_path)

    return written


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combined Metrics & Insights report comparing scenario outputs."
    )
    parser.add_argument(
        "--inputs",
        required=True,
        help="Path to inputs directory containing exactly 2 .owl files (same for all scenarios).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output .html file. CSV will be written alongside with .csv extension.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Paths to scenario output directories (≥1).  Label = basename.",
    )
    args = parser.parse_args()

    inputs_dir = Path(args.inputs)
    if not inputs_dir.is_dir():
        sys.exit(f"--inputs is not a directory: {inputs_dir}")
    owl_files = sorted(inputs_dir.glob("*.owl"))
    if len(owl_files) != 2:
        sys.exit(
            f"Expected exactly 2 .owl files in {inputs_dir}, found {len(owl_files)}"
        )

    print(f"Loading inputs from {inputs_dir}")
    onto1 = _load_graph(str(owl_files[0]))
    onto2 = _load_graph(str(owl_files[1]))
    union = Graph()
    for t in onto1:
        union.add(t)
    for t in onto2:
        union.add(t)
    onto1_entities: set[URIRef] = {s for s, _, _ in onto1 if isinstance(s, URIRef)}
    onto2_entities: set[URIRef] = {s for s, _, _ in onto2 if isinstance(s, URIRef)}
    print(f"  union_input: {len(union)} triples")

    scenarios: list[dict] = []
    for path_str in args.paths:
        path = Path(path_str)
        print(f"\nProcessing scenario: {path}")
        scenario = _compute_scenario(
            path, onto1, onto2, union, onto1_entities, onto2_entities
        )
        if scenario is not None:
            scenarios.append(scenario)

    if not scenarios:
        sys.exit("No valid scenarios — every path was missing merged_ontology.owl")

    out_html = Path(args.output)
    out_csv = out_html.with_suffix(".csv")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    out_html.write_text(_build_html(scenarios, inputs_dir), encoding="utf-8")
    print(f"\nReport HTML: {out_html}")

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(_build_csv_rows(scenarios))
    print(f"Report CSV:  {out_csv}")

    # ── Charts (per-category JPGs, side-by-side methods + Our Solution variants) ──
    # File prefix derived from output basename: e.g. m_i_raport_conference_1.html
    # → prefix "conference_1" (drop leading "m_i_raport_" if present).
    prefix = out_html.stem
    if prefix.startswith("m_i_raport_"):
        prefix = prefix[len("m_i_raport_"):]
    chart_paths = _render_category_charts(scenarios, out_html.parent, prefix)
    if chart_paths:
        print(f"Charts:      {len(chart_paths)} JPG file(s) → {chart_paths[0].parent}/")


if __name__ == "__main__":
    main()
