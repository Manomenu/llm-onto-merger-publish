# LLM backends and configuration

The language model is the only place where external knowledge enters (stage 8 in
[workflow.md](workflow.md)). The model is accessed through the **OpenAI Chat
Completions** protocol, so any compatible endpoint can be connected. All settings
go through the `.env` file (copy it from `.env.example`).

## Three backends

| Backend | When | Keys in `.env` |
|---------|------|----------------|
| **Ollama** (default) | local model on `localhost:11434` | `OLLAMA_MODEL`, `OLLAMA_HOST` |
| **vLLM** (OpenAI-compatible) | self-hosted server (e.g. gpt-oss-20b on a GPU) | `USE_VLLM=true`, `VLLM_MODEL`, `VLLM_HOST` |
| **OpenRouter** | selected via the `--model` CLI flag | `OPENROUTER_API_KEY` (+ optional `OPENROUTER_HOST`) |

Selection:
- no `--model` + `USE_VLLM=false` → **Ollama**;
- no `--model` + `USE_VLLM=true` → **vLLM** (`VLLM_HOST`, `api_key="Empty"`);
- `--model <name>` → **OpenRouter** (`OPENROUTER_API_KEY`, host `openrouter.ai/api/v1`).

## Example: gpt-oss-20b via vLLM (the paper's setup)

```dotenv
USE_VLLM=true
VLLM_MODEL=openai/gpt-oss-20b
VLLM_HOST=http://<host>/vllm-gh200   # OpenAI-compatible endpoint serving the model
PARALLEL_LLM_REQUEST_COUNT=24
DEBUG=1
```

Run (no `--model` → uses the backend from `.env`):
```bash
uv run llm-onto-merger --base A.owl --candidate B.owl --output out/
```

## Timeout — important for reasoning models

`gpt-oss-20b` is a **reasoning** model: a single call to a self-hosted vLLM can
take tens of seconds (cold start / load). The client therefore uses an extended
timeout, configurable via an environment variable:

```dotenv
LLM_REQUEST_TIMEOUT=600   # seconds (default 600)
```

Without this, every call would time out and **silently fall back** to a
deterministic merge (union + pair collapse), quietly invalidating a run. The
fallback is logged as a `WARNING`, and `cost_stats.json` would show `call_count: 0`.

## Parallelism

`PARALLEL_LLM_REQUEST_COUNT` (or `--parallel-llm-request-count`) sets the number
of concurrent LLM calls (one per merge environment). In the paper: 24 for vLLM.

## Repeated measurements and prompt caching

`--run-nonce` prepends a unique identifier to the **beginning** of the prompt so
that repeated runs of the same dataset do not share a prefix — this defeats
provider-side prompt caches and guarantees independent sampling. The scenario
scripts set the nonce automatically from `--label`.
