# What goes where — output artifacts

This document describes **every file** produced by the framework — from a single
merge to a full experimental run. For the pipeline that produces these files, see
[workflow.md](workflow.md).

---

## 1. A single merge (`llm-onto-merger --output <DIR>`)

Everything lands in the directory given to `--output`. Below is the complete set
of artifacts (verified on a real gpt-oss-20b run):

### Result and baseline
| File | Contents |
|------|----------|
| `merged_ontology.owl` | **The merged ontology** (RDF/XML). The main artifact. |
| `applied_alignments.owl` | Baseline: naive union with the alignments applied (for comparison against the LLM result). |

### Statistics (JSON, for programmatic analysis)
| File | Contents |
|------|----------|
| `alignment_stats.json` | Number of alignments, how many were applied/rejected, `per_env`, `rejected_alignments`. |
| `cost_stats.json` | LLM cost and call count. **Note:** applies only to the OpenRouter backend; for local vLLM/Ollama `call_count`/`cost` = 0 (no billing), which does **not** mean the LLM did not run. |

### Insights
| File | Contents |
|------|----------|
| `insights.csv` | Run-time metrics (per environment / aggregate), CSV. |
| `insights.html` | The same content in readable HTML form. |

### Debug / visualizations (only when `DEBUG=1` in `.env`)
| File | Contents |
|------|----------|
| `debug_pre_merge.html` | All environments **before** merging + leftovers. Colors: blue=onto_1, orange=onto_2, green=border, red=seed. |
| `debug_post_merge.html` | All merged environments + leftovers in one view. |
| `debug_merge_env_<N>.html` | A single environment N **before** merging (pink edges = triples that will disappear). |
| `debug_merged_env_<N>.html` | Environment N **after** merging (pink edges = triples added by the LLM). |
| `onto_1_leftover.html` / `onto_2_leftover.html` | Entities without an alignment (pass-through) from each ontology. |
| `env_diff_<N>.txt` | **Text diff** of environment N: `[Deleted]` / `[Added]` sections — exactly what the LLM removed and added. The fastest way to see the model's decisions. |

> **Example `env_diff` from a real gpt-oss-20b run** (merging `Researcher↔Researcher`):
> `[Deleted] (wrote, domain, Researcher)…` — the model collapsed a duplicate relation;
> `[Added] (Paper, subClassOf, Publication)` — it added an emergent cross-ontology relation.

### Report (separate step: `metrics_and_insights_raport.py`)
| File | Contents |
|------|----------|
| `report.html` | Per-scenario report: quality measures + insights + comparison against baselines. |
| `report.csv` | The same measures machine-readable (`metrics` / `insights` sections), e.g. `ARC`, `cycle_count`, `syntactic_uniqueness_ratio`, `cross_onto_subclassof_count`. |
| `charts/report_<dimension>.jpg` | **7 charts** — one per quality dimension: `structural_coherence`, `domain_coherence`, `conciseness`, `knowledge_completeness`, `hierarchy_integration_quality`, `understandability`, `accuracy`. |

---

## 2. Experimental runs (`tests/article_scenarios/s*.sh` scripts)

The scenario scripts wrap the above with a directory structure and baselines.
Everything below is **gitignored** (data, not code).

```
tests/article_scenarios/outputs/[<label>/]s2/<dataset>/
  <dataset>_aml_15k_p24/          ← merger output + copied baselines:
      merged_ontology.owl
      applied_alignments.owl
      boomer_ontology.owl          (if Boomer completed)
      arom_ontology.owl            (if AROM)
      comerger_ontology.owl        (if CoMerger; else comerger_timeout.txt)
      *_stats.json, run.log, insights.*, debug_*.html, env_diff_*.txt
  m_i_raport_<dataset>.html/.csv/.log   ← per-scenario aggregate report

tests/article_scenarios/outputs/.baseline_cache/aml/<dataset>/
  boomer/  arom/  comerger/  applied/   ← deterministic baselines,
                                          computed ONCE and shared across turns
```

- **`--label <turn>`** nests output under `outputs/<turn>/…` (for repeated measurements).
- Baselines are deterministic → cached outside the label tree and shared.

## 3. Multi-turn analysis (`tests/article_analysis_gptoss/analyze-all.sh`)

Aggregates multiple turns (median [min; max]) and produces summary charts plus
per-dimension CSVs, reusing helpers from `tests/article_analysis_deepseek/`
(`combine_turns.py`, `plot_turns.py`, `plot_grouped.py`, `oaei_to_agg.py`).
It requires the full dataset set (3 datasets × N turns × baselines) — this is a
research run, not a smoke test. See [reproduction.md](reproduction.md).

---

## Which artifacts are "for inspection"?

- **Quick look at the result:** `merged_ontology.owl` + `env_diff_<N>.txt`.
- **Quality assessment:** `report.html` + `charts/*.jpg` + `report.csv`.
- **Understanding the process:** `debug_pre_merge.html` / `debug_post_merge.html`.
- **Data for further processing:** `*_stats.json`, `insights.csv`, `report.csv`.
