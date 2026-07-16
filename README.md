# LLM-Onto-Merger

Framework do **fizycznego scalania dwóch ontologii OWL** z użyciem dużego modelu
językowego jako źródła wiedzy zewnętrznej. Pipeline dzieli ontologie na małe,
kontekstowo spójne *środowiska scalania*, wysyła każde do LLM (przez protokół
OpenAI Chat Completions — Ollama / vLLM / OpenRouter), a wyniki składa w jedną
ontologię. Referencyjna implementacja do artykułu o ewaluacji scalania ontologii.

## Instalacja

```bash
uv sync
cp .env.example .env      # następnie ustaw backend LLM — patrz docs/backends.md
```

## Szybki start

```bash
uv run llm-onto-merger --base base.owl --candidate candidate.owl --output out/
```

Opcje CLI: `--alignment-tool` (domyślnie `aml`), `--output`, `--max-env-chars`,
`--parallel-llm-request-count`, `--model` (przełącza na OpenRouter), `--run-nonce`.
Pełnia: `uv run llm-onto-merger --help`.

## Co powstaje

W katalogu `--output`: `merged_ontology.owl` (wynik), `applied_alignments.owl`
(baseline), statystyki JSON, `insights.*`, oraz — przy `DEBUG=1` — wizualizacje
HTML i `env_diff_*.txt` (dokładne decyzje LLM). Osobny krok raportowy dokłada
`report.html/.csv` i 7 wykresów jakości. **Pełna mapa „co gdzie trafia":
[docs/outputs.md](docs/outputs.md).**

## Dokumentacja

| Dokument | O czym |
|----------|--------|
| [docs/workflow.md](docs/workflow.md) | Szczegółowy przepływ (11 etapów) i architektura pipeline'u |
| [docs/outputs.md](docs/outputs.md) | **Co gdzie trafia** — każdy plik wyjściowy objaśniony |
| [docs/backends.md](docs/backends.md) | Konfiguracja LLM (Ollama / vLLM / OpenRouter), `.env`, timeout |
| [docs/reproduction.md](docs/reproduction.md) | Reprodukcja eksperymentów z artykułu (dane, baseline'y, scenariusze) |
| [thirdparty/README.md](thirdparty/README.md) | Jak zdobyć narzędzia baseline (AML, LogMap, Boomer, CoMerger, OWLTools) |

## Wymagania

- Python 3.11+ (testowane na 3.13)
- Java 17+ (do uruchamiania AML)
- Backend LLM zgodny z OpenAI Chat Completions — Ollama (domyślnie), vLLM lub OpenRouter (patrz [docs/backends.md](docs/backends.md))
- Narzędzia baseline (AML, LogMap, Boomer, CoMerger, OWLTools) **nie są dołączone** do repozytorium — pobierz je zgodnie z [`thirdparty/README.md`](thirdparty/README.md). Do samego mergowania wystarczy AML w `thirdparty/aml/AgreementMakerLight.jar` (+ katalog `store/`).
- Ontologie wejściowe (OAEI Conference/Anatomy, SWO, ACM CCS) — nie są dołączone; źródła w [docs/reproduction.md](docs/reproduction.md).
