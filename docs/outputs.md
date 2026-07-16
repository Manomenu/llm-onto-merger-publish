# Co gdzie trafia — artefakty wyjściowe

Ten dokument opisuje **każdy plik**, który powstaje podczas działania frameworka —
od pojedynczego scalania po pełny przebieg eksperymentalny. Opis pipeline'u, który
te pliki produkuje: [workflow.md](workflow.md).

---

## 1. Pojedyncze scalanie (`llm-onto-merger --output <DIR>`)

Wszystko ląduje w katalogu podanym w `--output`. Poniżej komplet artefaktów
(zweryfikowany na realnym przebiegu gpt-oss-20b):

### Wynik i baseline
| Plik | Co zawiera |
|------|-----------|
| `merged_ontology.owl` | **Wynikowa scalona ontologia** (RDF/XML). Główny artefakt. |
| `applied_alignments.owl` | Baseline: naiwna unia z zastosowanymi alignmentami (do porównania z wynikiem LLM). |

### Statystyki (JSON, do analizy programatycznej)
| Plik | Co zawiera |
|------|-----------|
| `alignment_stats.json` | Liczba alignmentów, ile zastosowano/odrzucono, `per_env`, `rejected_alignments`. |
| `cost_stats.json` | Koszt i liczba wywołań LLM. **Uwaga:** dotyczy tylko backendu OpenRouter; dla lokalnego vLLM/Ollama `call_count`/`cost` = 0 (brak rozliczenia), co **nie** oznacza, że LLM nie działał. |

### Wgląd / insighty
| Plik | Co zawiera |
|------|-----------|
| `insights.csv` | Metryki „na gorąco" z przebiegu (per-środowisko / zbiorczo), format CSV. |
| `insights.html` | Ta sama treść w czytelnej formie HTML. |

### Debug / wizualizacje (tylko gdy `DEBUG=1` w `.env`)
| Plik | Co zawiera |
|------|-----------|
| `debug_pre_merge.html` | Wszystkie środowiska **przed** scalaniem + leftovers. Kolory: niebieski=onto_1, pomarańczowy=onto_2, zielony=granica, czerwony=seed. |
| `debug_post_merge.html` | Wszystkie scalone środowiska + leftovers w jednym widoku. |
| `debug_merge_env_<N>.html` | Pojedyncze środowisko N **przed** scalaniem (różowe krawędzie = trójki, które znikną). |
| `debug_merged_env_<N>.html` | Środowisko N **po** scalaniu (różowe krawędzie = trójki dodane przez LLM). |
| `onto_1_leftover.html` / `onto_2_leftover.html` | Encje bez alignmentu (pass-through) z każdej ontologii. |
| `env_diff_<N>.txt` | **Tekstowy diff** środowiska N: sekcje `[Deleted]` / `[Added]` — dokładnie co LLM usunął i dodał. Najszybszy sposób zobaczenia decyzji modelu. |

> **Przykład `env_diff` z realnego gpt-oss-20b** (scalanie `Researcher↔Researcher`):
> `[Deleted] (wrote, domain, Researcher)…` — model scalił zduplikowaną relację;
> `[Added] (Paper, subClassOf, Publication)` — dodał emergentną relację cross-ontology.

### Raport (osobny krok: `metrics_and_insights_raport.py`)
| Plik | Co zawiera |
|------|-----------|
| `report.html` | Raport per-scenariusz: miary jakości + insighty + porównanie z baseline'ami. |
| `report.csv` | Te same miary maszynowo (sekcje `metrics` / `insights`), np. `ARC`, `cycle_count`, `syntactic_uniqueness_ratio`, `cross_onto_subclassof_count`. |
| `charts/report_<dimension>.jpg` | **7 wykresów** — po jednym na wymiar jakości: `structural_coherence`, `domain_coherence`, `conciseness`, `knowledge_completeness`, `hierarchy_integration_quality`, `understandability`, `accuracy`. |

---

## 2. Przebiegi eksperymentalne (skrypty `tests/article_scenarios/s*.sh`)

Skrypty scenariuszowe nakładają na powyższe strukturę katalogów i baseline'y.
Wszystko poniżej jest **gitignore'owane** (dane, nie kod).

```
tests/article_scenarios/outputs/[<label>/]s2/<dataset>/
  <dataset>_aml_15k_p24/          ← wynik mergera + skopiowane baseline'y:
      merged_ontology.owl
      applied_alignments.owl
      boomer_ontology.owl          (jeśli Boomer się policzył)
      arom_ontology.owl            (jeśli AROM)
      comerger_ontology.owl        (jeśli CoMerger; albo comerger_timeout.txt)
      *_stats.json, run.log, insights.*, debug_*.html, env_diff_*.txt
  m_i_raport_<dataset>.html/.csv/.log   ← raport zbiorczy scenariusza

tests/article_scenarios/outputs/.baseline_cache/aml/<dataset>/
  boomer/  arom/  comerger/  applied/   ← deterministyczne baseline'y,
                                          liczone RAZ i współdzielone między turami
```

- **`--label <turn>`** zagnieżdża wynik pod `outputs/<turn>/…` (dla powtórzeń pomiarowych).
- Baseline'y są deterministyczne → cache poza drzewem etykiet, współdzielony.

## 3. Analiza wielu tur (`tests/article_analysis_gptoss/analyze-all.sh`)

Agreguje wyniki wielu tur (median [min; max]) i produkuje wykresy zbiorcze oraz
CSV per wymiar, reużywając helperów z `tests/article_analysis_deepseek/`
(`combine_turns.py`, `plot_turns.py`, `plot_grouped.py`, `oaei_to_agg.py`).
Wymaga pełnego zestawu danych (3 datasety × N tur × baseline'y) — to przebieg
badawczy, nie smoke-test. Zob. [reproduction.md](reproduction.md).

---

## Które artefakty są „do wglądu"?

- **Szybki podgląd wyniku:** `merged_ontology.owl` + `env_diff_<N>.txt`.
- **Ocena jakości:** `report.html` + `charts/*.jpg` + `report.csv`.
- **Zrozumienie działania:** `debug_pre_merge.html` / `debug_post_merge.html`.
- **Dane do dalszej obróbki:** `*_stats.json`, `insights.csv`, `report.csv`.
