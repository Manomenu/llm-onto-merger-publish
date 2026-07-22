# LLM-Onto-Merger

A framework for the **physical merging of two OWL ontologies** using a large
language model as the source of external knowledge. The pipeline splits the
ontologies into small, contextually coherent *merge environments*, sends each to
an LLM (via the OpenAI Chat Completions protocol — Ollama / vLLM / OpenRouter),
and reassembles the results into a single ontology. Reference implementation for
the accompanying paper on ontology-merging evaluation.

## Installation

```bash
uv sync
cp .env.example .env      # then configure the LLM backend — see docs/backends.md
```

## Quick start

```bash
uv run llm-onto-merger --base base.owl --candidate candidate.owl --output out/
```

CLI options: `--alignment-tool` (default `aml`), `--output`, `--max-env-chars`,
`--parallel-llm-request-count`, `--model` (switches to OpenRouter), `--run-nonce`.
Full list: `uv run llm-onto-merger --help`.

## What gets produced

In the `--output` directory: `merged_ontology.owl` (result),
`applied_alignments.owl` (baseline), JSON statistics, `insights.*`, and — when
`DEBUG=1` — HTML visualizations and `env_diff_*.txt` (the exact LLM decisions). A
separate reporting step adds `report.html/.csv` and 7 quality charts. The
multi-turn analysis (`tests/article_analysis_*/analyze-all.sh`) additionally
computes the per-turn LLM error/fallback rate from the run logs
(`errors/errors.csv`, `errors/errors_summary.csv`). **Full
"what goes where" map: [docs/outputs.md](docs/outputs.md).**

## Documentation

| Document | About |
|----------|-------|
| [docs/workflow.md](docs/workflow.md) | Detailed pipeline (11 stages) and architecture |
| [docs/outputs.md](docs/outputs.md) | **What goes where** — every output file explained |
| [docs/backends.md](docs/backends.md) | LLM configuration (Ollama / vLLM / OpenRouter), `.env`, timeout |
| [docs/reproduction.md](docs/reproduction.md) | Reproducing the paper's experiments (data, baselines, scenarios) |
| [thirdparty/README.md](thirdparty/README.md) | How to obtain the baseline tools (AML, LogMap, Boomer, CoMerger, OWLTools) |

## Requirements

- Python 3.11+ (tested on 3.13)
- Java 17+ (to run AML)
- An OpenAI Chat Completions–compatible LLM backend — Ollama (default), vLLM, or OpenRouter (see [docs/backends.md](docs/backends.md))
- Baseline tools (AML, LogMap, Boomer, CoMerger, OWLTools) are **not bundled** — obtain them per [`thirdparty/README.md`](thirdparty/README.md). For merging alone you only need AML at `thirdparty/aml/AgreementMakerLight.jar` (+ the `store/` directory).
- Input ontologies (OAEI Conference/Anatomy, SWO, ACM CCS) are not bundled; sources in [docs/reproduction.md](docs/reproduction.md).

## License

Released under the [MIT License](LICENSE) — permissive use with no warranty and
no liability for the authors. The baseline tools referenced under `thirdparty/`
are **not** distributed here and remain subject to their own licenses; obtain
them from their upstream sources (see [thirdparty/README.md](thirdparty/README.md)).
