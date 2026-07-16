import csv
from pathlib import Path

from pydantic import BaseModel
from rdflib import OWL, Graph

from ..extract_environments.merge_environment import MergeEnvironment
from ..ontology.kg2code import DropReport


class EnvInsight(BaseModel):
    env_idx: int
    input_triples: int
    kept_triples: int
    added_triples: int
    deleted_triples: int
    input_disjoint: int
    merged_disjoint: int
    drop_report: DropReport
    alignment_applied: bool

    @property
    def disjoint_delta(self) -> int:
        return self.merged_disjoint - self.input_disjoint

    @property
    def retention_pct(self) -> float:
        return 100 * self.kept_triples / self.input_triples if self.input_triples else 0.0

    @property
    def total_dropped(self) -> int:
        return self.drop_report.total


def _local(uri: str) -> str:
    for sep in ("#", "/"):
        idx = uri.rfind(sep)
        if idx >= 0:
            return uri[idx + 1:]
    return uri


def _local_keys(g: Graph) -> set[tuple[str, str, str]]:
    from rdflib import URIRef
    return {
        (_local(str(s)), _local(str(p)), _local(str(o)))
        for s, p, o in g
        if isinstance(s, URIRef) and isinstance(o, URIRef)
    }


def _compute_insights(
    merge_environments: list[MergeEnvironment],
    merged_graphs: list[Graph],
    drop_reports: list[DropReport],
    alignment_applied_flags: list[bool],
) -> list[EnvInsight]:
    rows = []
    for idx, (env, merged, report, applied) in enumerate(
        zip(merge_environments, merged_graphs, drop_reports, alignment_applied_flags),
        start=1,
    ):
        input_graph = Graph()
        for t in env.onto_1:
            input_graph.add(t)
        for t in env.onto_2:
            input_graph.add(t)

        input_keys = _local_keys(input_graph)
        merged_keys = _local_keys(merged)

        rows.append(EnvInsight(
            env_idx=idx,
            input_triples=len(input_keys),
            kept_triples=len(input_keys & merged_keys),
            added_triples=len(merged_keys - input_keys),
            deleted_triples=len(input_keys - merged_keys),
            input_disjoint=sum(1 for _ in input_graph.triples((None, OWL.disjointWith, None))),
            merged_disjoint=sum(1 for _ in merged.triples((None, OWL.disjointWith, None))),
            drop_report=report,
            alignment_applied=applied,
        ))
    return rows


def _write_csv(rows: list[EnvInsight], total: EnvInsight, out_dir: Path) -> Path:
    path = out_dir / "insights.csv"
    fields = [
        "env", "input_triples", "kept", "added", "deleted",
        "retention_%", "disjoint_in", "disjoint_out", "disjoint_delta",
        "dropped_invalid", "dropped_bad_subject", "dropped_bad_pred", "dropped_total",
        "alignment_applied", "llm_failed*",
    ]
    applied_count = sum(1 for r in rows if r.alignment_applied)
    llm_failed_count = sum(1 for r in rows if r.drop_report.llm_failed)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r in rows:
            w.writerow([
                r.env_idx, r.input_triples, r.kept_triples, r.added_triples, r.deleted_triples,
                f"{r.retention_pct:.1f}", r.input_disjoint, r.merged_disjoint, r.disjoint_delta,
                len(r.drop_report.invalid_entities),
                len(r.drop_report.bad_subject_entities),
                len(r.drop_report.bad_predicate_triples),
                r.total_dropped,
                "yes" if r.alignment_applied else "no",
                "yes" if r.drop_report.llm_failed else "no",
            ])
        w.writerow([
            "TOTAL",
            total.input_triples, total.kept_triples, total.added_triples, total.deleted_triples,
            f"{total.retention_pct:.1f}", total.input_disjoint, total.merged_disjoint, total.disjoint_delta,
            len(total.drop_report.invalid_entities),
            len(total.drop_report.bad_subject_entities),
            len(total.drop_report.bad_predicate_triples),
            total.total_dropped,
            f"{applied_count}/{len(rows)}",
            f"{llm_failed_count}/{len(rows)}",
        ])
    return path


def _cell_class(value: int | float, positive_bad: bool = False) -> str:
    if isinstance(value, float):
        bad = value < 50.0
    else:
        bad = value > 0 if positive_bad else value < 0
    return "bad" if bad else ""


def _drop_details_html(rows: list[EnvInsight]) -> str:
    """HTML section listing dropped items per env (only for envs with drops)."""
    sections = []
    for r in rows:
        dr = r.drop_report
        if dr.total == 0:
            continue
        items: list[str] = []
        for uri in dr.invalid_entities:
            items.append(f'<li class="drop-invalid"><span class="tag">invalid/placeholder</span> <code>{uri}</code></li>')
        for uri in dr.bad_subject_entities:
            items.append(f'<li class="drop-subj"><span class="tag">bad subject</span> <code>{uri}</code></li>')
        for subj, pred in dr.bad_predicate_triples:
            items.append(f'<li class="drop-pred"><span class="tag">bad predicate</span> subject <code>{subj}</code> predicate <code>{pred}</code></li>')
        sections.append(
            f'<div class="drop-env">'
            f'<h3>env {r.env_idx} — {dr.total} odrzuconych</h3>'
            f'<ul>{"".join(items)}</ul>'
            f'</div>'
        )
    if not sections:
        return '<p style="color:#888;font-size:0.88rem;">Brak odrzuconych encji i trójek.</p>'
    return "\n".join(sections)


def _write_html(rows: list[EnvInsight], total: EnvInsight, out_dir: Path) -> Path:
    applied_count = sum(1 for r in rows if r.alignment_applied)
    llm_failed_count = sum(1 for r in rows if r.drop_report.llm_failed)

    def tr(
        r: EnvInsight, label: str, is_total: bool = False,
        applied_override: str | None = None, failed_override: str | None = None,
    ) -> str:
        row_cls = ' class="total"' if is_total else ""
        del_cls = _cell_class(r.deleted_triples, positive_bad=True)
        ret_cls = _cell_class(r.retention_pct)
        dj_cls = _cell_class(r.disjoint_delta, positive_bad=True)
        drop_cls = "bad" if r.total_dropped > 0 else ""
        if applied_override is not None:
            applied_cell = f'<td>{applied_override}</td>'
        else:
            applied_cell = (
                '<td class="good">tak</td>' if r.alignment_applied
                else '<td class="bad">nie</td>'
            )
        if failed_override is not None:
            failed_cell = f'<td>{failed_override}</td>'
        else:
            failed_cell = (
                '<td class="bad">tak</td>' if r.drop_report.llm_failed
                else '<td>nie</td>'
            )
        return (
            f"<tr{row_cls}>"
            f"<td>{label}</td>"
            f"<td>{r.input_triples}</td>"
            f'<td class="good">{r.added_triples}</td>'
            f"<td>{r.kept_triples}</td>"
            f'<td class="{del_cls}">{r.deleted_triples}</td>'
            f'<td class="{ret_cls}">{r.retention_pct:.1f}%</td>'
            f"<td>{r.input_disjoint}</td>"
            f"<td>{r.merged_disjoint}</td>"
            f'<td class="{dj_cls}">{r.disjoint_delta:+d}</td>'
            f'<td class="{drop_cls}">{r.total_dropped}</td>'
            f"{applied_cell}"
            f"{failed_cell}"
            f"</tr>"
        )

    rows_html = "\n".join(tr(r, f"env {r.env_idx}") for r in rows)
    total_html = tr(
        total, "TOTAL", is_total=True,
        applied_override=f"{applied_count}/{len(rows)}",
        failed_override=f"{llm_failed_count}/{len(rows)}",
    )
    drop_details = _drop_details_html(rows)

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <title>Merge insights</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      background: #f5f5f5;
      color: #222;
      margin: 0;
      padding: 2rem;
    }}
    h1 {{ font-size: 1.4rem; margin-bottom: 0.3rem; }}
    h2 {{ font-size: 1.1rem; margin: 1.8rem 0 0.6rem; border-bottom: 1px solid #ccc; padding-bottom: 0.3rem; }}
    h3 {{ font-size: 0.9rem; margin: 1rem 0 0.4rem; color: #555; }}
    .subtitle {{ color: #666; font-size: 0.9rem; margin-bottom: 2rem; }}
    .section {{
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 8px;
      padding: 1.2rem 1.6rem;
      margin-bottom: 1.5rem;
      max-width: 960px;
    }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{
      padding: 0.35rem 0.7rem;
      font-size: 0.88rem;
      text-align: right;
      border-bottom: 1px solid #eee;
    }}
    th {{ background: #f0f0f0; text-align: center; font-weight: 600; }}
    td:first-child, th:first-child {{ text-align: left; }}
    tr:hover td {{ background: #fafafa; }}
    tr.total td {{ font-weight: 700; background: #f0f4ff; border-top: 2px solid #aaa; }}
    td.good {{ color: #2e7d32; font-weight: 600; }}
    td.bad  {{ color: #c62828; font-weight: 600; }}
    .legend {{ font-size: 0.82rem; color: #666; margin-top: 1rem; }}
    .legend span {{ display: inline-block; width: 12px; height: 12px;
                    border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
    .drop-env {{ margin-bottom: 1.2rem; }}
    .drop-env ul {{ margin: 0.3rem 0 0 0; padding-left: 1.2rem; font-size: 0.85rem; }}
    .drop-env li {{ margin: 0.25rem 0; }}
    .tag {{
      display: inline-block;
      font-size: 0.75rem;
      padding: 0.1rem 0.45rem;
      border-radius: 3px;
      margin-right: 0.4rem;
      font-weight: 600;
    }}
    li.drop-invalid .tag {{ background: #fce4ec; color: #880e4f; }}
    li.drop-subj    .tag {{ background: #fff3e0; color: #bf360c; }}
    li.drop-pred    .tag {{ background: #fafafa; color: #555; border: 1px solid #ddd; }}
    code {{ font-family: monospace; font-size: 0.82rem; background: #f5f5f5;
            padding: 0.05rem 0.3rem; border-radius: 3px; }}
  </style>
</head>
<body>

<h1>Merge insights</h1>
<p class="subtitle">Statystyki per środowisko. Generowane gdy <code>settings.debug = True</code>.</p>

<div class="section">
  <h2>Podsumowanie</h2>
  <table>
    <thead>
      <tr>
        <th>env</th>
        <th>input</th>
        <th>dodane</th>
        <th>zachowane</th>
        <th>usunięte</th>
        <th>retencja %</th>
        <th>disjointWith (in)</th>
        <th>disjointWith (out)</th>
        <th>disjointWith Δ</th>
        <th>odrzucone</th>
        <th>alignment zastosowany</th>
        <th>llm_failed*</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
{total_html}
    </tbody>
  </table>
  <div class="legend">
    <span style="background:#2e7d32"></span> zielony = dobrze &nbsp;
    <span style="background:#c62828"></span> czerwony = podejrzane &nbsp;
    Retencja &lt; 50%, usunięte &gt; 0, disjointWith Δ &gt; 0 lub odrzucone &gt; 0 zaznaczają komórkę na czerwono.
    <br/>
    <strong>* llm_failed</strong> = LLM zwrócił niepoprawny JSON (np. unterminated string, przerwana odpowiedź) lub
    odpowiedź nie pasuje do <code>MergedOntology</code> schema mimo użycia structured-output.
    Dla takich env wykonano deterministyczny fallback: <code>apply_alignments(env.onto_1, env.onto_2, env.alignments)</code>
    — czyli union obu interior grafów z bezwarunkowym collapse'em e2 → e1 dla każdego alignmentu.
    Wynik zachowuje 100% input triples ale nie ma żadnego cross-onto enhancement ani komentarzy.
  </div>
</div>

<div class="section">
  <h2>Szczegóły odrzuconych</h2>
  {drop_details}
</div>

</body>
</html>
"""
    path = out_dir / "insights.html"
    path.write_text(html, encoding="utf-8")
    return path


def save_insights_debug(
    merge_environments: list[MergeEnvironment],
    merged_graphs: list[Graph],
    drop_reports: list[DropReport],
    alignment_applied_flags: list[bool],
    out_dir: Path,
) -> None:
    rows = _compute_insights(
        merge_environments, merged_graphs, drop_reports, alignment_applied_flags
    )
    merged_report = DropReport(
        invalid_entities=[e for r in drop_reports for e in r.invalid_entities],
        bad_subject_entities=[e for r in drop_reports for e in r.bad_subject_entities],
        bad_predicate_triples=[t for r in drop_reports for t in r.bad_predicate_triples],
    )
    total = EnvInsight(
        env_idx=0,
        input_triples=sum(r.input_triples for r in rows),
        kept_triples=sum(r.kept_triples for r in rows),
        added_triples=sum(r.added_triples for r in rows),
        deleted_triples=sum(r.deleted_triples for r in rows),
        input_disjoint=sum(r.input_disjoint for r in rows),
        merged_disjoint=sum(r.merged_disjoint for r in rows),
        drop_report=merged_report,
        alignment_applied=all(r.alignment_applied for r in rows),
    )
    csv_path = _write_csv(rows, total, out_dir)
    html_path = _write_html(rows, total, out_dir)
    from ..logger import get_logger
    log = get_logger(__name__)
    log.info("Insights saved: %s  %s", csv_path, html_path)
