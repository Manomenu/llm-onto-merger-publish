# Reprodukcja eksperymentów z artykułu

Framework był ewaluowany na 3 scenariuszach, 6 metodach i 7 wymiarach jakości.
Ten dokument opisuje, co trzeba zdobyć i jak uruchomić pełny pipeline.

## 1. Dane wejściowe (nie dołączone do repo)

Trzy scenariusze, każdy z `reference.rdf` (ground truth):

| Scenariusz | Ontologie | Źródło |
|------------|-----------|--------|
| `confOf-ekaw` | OAEI Conference Track | https://oaei.ontologymatching.org/2025/conference/ |
| `human-mouse` | OAEI Anatomy Track | https://oaei.ontologymatching.org/2025/anatomy/ |
| `swo-acm` | Software Ontology + ACM CCS 2012 | SWO: https://github.com/allysonlister/swo · ACM CCS: https://www.acm.org/publications/class-2012 |

Umieść każdą parę w `tests/inputs/<scenariusz>/` (dokładnie 2 pliki `.owl` +
`reference.rdf`). Dla `swo-acm` `reference.rdf` był zbudowany ręcznie przez autora.

## 2. Narzędzia baseline (nie dołączone — zob. [`../thirdparty/README.md`](../thirdparty/README.md))

AML (alignment), oraz merge-baseline'y: Boomer, AROM, CoMerger, OWLTools.
Pobierz i umieść zgodnie z instrukcją w `thirdparty/README.md`.

## 3. Backend LLM

Ustaw gpt-oss-20b przez vLLM (albo inny model) — zob. [backends.md](backends.md).

## 4. Uruchomienie

Pojedynczy scenariusz, jedna tura:
```bash
tests/article_scenarios/s2.sh --label turn1 --only confOf-ekaw
```
(`s2` = wejście AML; `s3` = wejście z reference.rdf; `s5`/`s6` = warianty).

Powtórzone tury (dla statystyki median [min; max]):
```bash
for t in turn1 turn2 turn3 turn4 turn5; do tests/article_scenarios/s2.sh --label $t; done
```

## 5. Analiza zbiorcza

```bash
bash tests/article_analysis_gptoss/analyze-all.sh turn1 turn2 turn3 turn4 turn5
```
Agreguje tury, liczy median [min; max] per wymiar i generuje wykresy zbiorcze.
Wariant DeepSeek: `tests/article_analysis_deepseek/` (helpery współdzielone).

## Uwagi

- **CoMerger na `swo-acm`** nie kończy się (zaszyty reasoner Pellet przekracza limit
  3 min) — to oczekiwane; kolumna CoMerger jest wtedy nieobecna.
- Baseline'y są deterministyczne — liczone raz i cache'owane
  (`outputs/.baseline_cache/`), więc kolejne tury reużywają wyników.
- Modele rozumujące są wolne — pełny przebieg (3 datasety × 5 tur) to godziny;
  ustaw `LLM_REQUEST_TIMEOUT` odpowiednio wysoko.

## Smoke-test (minimalny sprawdzian, że pipeline działa)

Trywialne wejście (2 klasy + 1 relacja na ontologię) wystarczy, by przejść cały
łańcuch merge → raport → wykresy bez pełnego setupu:
```bash
uv run llm-onto-merger --base tiny/base.owl --candidate tiny/candidate.owl --output tiny-out/
uv run python tests/metrics_and_insights_raport.py --inputs tiny --output tiny-out/report.html tiny-out/
```
Sprawdź `tiny-out/env_diff_0.txt` (decyzje LLM) i `tiny-out/charts/*.jpg` (7 wymiarów).
