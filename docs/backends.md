# Backendy LLM i konfiguracja

Model językowy jest jedynym miejscem, w którym wchodzi wiedza zewnętrzna
(etap 8 w [workflow.md](workflow.md)). Dostęp do modelu odbywa się przez
protokół **OpenAI Chat Completions**, więc dowolny zgodny endpoint da się podłączyć.
Wszystkie ustawienia idą przez plik `.env` (skopiuj z `.env.example`).

## Trzy backendy

| Backend | Kiedy | Klucz w `.env` |
|---------|-------|----------------|
| **Ollama** (domyślny) | model lokalny na `localhost:11434` | `OLLAMA_MODEL`, `OLLAMA_HOST` |
| **vLLM** (OpenAI-compatible) | samodzielnie hostowany serwer (np. gpt-oss-20b na GPU) | `USE_VLLM=true`, `VLLM_MODEL`, `VLLM_HOST` |
| **OpenRouter** | wybierany flagą `--model` na CLI | `OPENROUTER_API_KEY` (+ opcjonalnie `OPENROUTER_HOST`) |

Wybór:
- brak `--model` + `USE_VLLM=false` → **Ollama**;
- brak `--model` + `USE_VLLM=true` → **vLLM** (`VLLM_HOST`, `api_key="Empty"`);
- `--model <nazwa>` → **OpenRouter** (`OPENROUTER_API_KEY`, host `openrouter.ai/api/v1`).

## Przykład: gpt-oss-20b przez vLLM (setup z artykułu)

```dotenv
USE_VLLM=true
VLLM_MODEL=openai/gpt-oss-20b
VLLM_HOST=http://<host>/vllm-gh200   # endpoint OpenAI-compatible serwujący model
PARALLEL_LLM_REQUEST_COUNT=24
DEBUG=1
```

Uruchomienie (bez `--model` → używa backendu z `.env`):
```bash
uv run llm-onto-merger --base A.owl --candidate B.owl --output out/
```

## Timeout — ważne dla modeli rozumujących

`gpt-oss-20b` to model **rozumujący**: pojedyncze wywołanie na samodzielnie
hostowanym vLLM potrafi trwać kilkadziesiąt sekund (zimny start / obciążenie).
Klient ma dlatego wydłużony timeout, konfigurowalny zmienną środowiskową:

```dotenv
LLM_REQUEST_TIMEOUT=600   # sekundy (domyślnie 600)
```

Bez tego każde wywołanie kończyłoby się timeoutem i **cichym fallbackiem** do
deterministycznego scalania (unia + kolaps par), co po cichu unieważniłoby przebieg.
Fallback jest logowany jako `WARNING`, a `cost_stats.json` pokazałby `call_count: 0`.

## Równoległość

`PARALLEL_LLM_REQUEST_COUNT` (albo `--parallel-llm-request-count`) ustawia liczbę
równoległych wywołań LLM (jeden na środowisko scalania). W artykule: 24 dla vLLM.

## Powtórzone pomiary a cache promptów

`--run-nonce` dokleja na **początek** promptu unikatowy identyfikator, żeby
powtórzone przebiegi tego samego datasetu nie współdzieliły prefiksu — to psuje
cache promptów po stronie dostawcy i gwarantuje niezależne próbkowanie.
Skrypty scenariuszowe ustawiają nonce automatycznie z `--label`.
