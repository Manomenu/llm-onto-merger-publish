# Reproducing the paper's experiments

The framework was evaluated on 3 scenarios, 6 methods, and 7 quality dimensions.
This document describes what to obtain and how to run the full pipeline.

## 1. Input data (not bundled)

Three scenarios, each with a `reference.rdf` (ground truth):

| Scenario | Ontologies | Source |
|----------|-----------|--------|
| `confOf-ekaw` | OAEI Conference Track | https://oaei.ontologymatching.org/2025/conference/ |
| `human-mouse` | OAEI Anatomy Track | https://oaei.ontologymatching.org/2025/anatomy/ |
| `swo-acm` | Software Ontology + ACM CCS 2012 | SWO: https://github.com/allysonlister/swo · ACM CCS: https://www.acm.org/publications/class-2012 |

Place each pair in `tests/inputs/<scenario>/` (exactly 2 `.owl` files +
`reference.rdf`). For `swo-acm` the `reference.rdf` was built manually by the author.

## 2. Baseline tools (not bundled — see [`../thirdparty/README.md`](../thirdparty/README.md))

AML (alignment), plus the merge baselines: Boomer, AROM, CoMerger, OWLTools.
Download and place them per `thirdparty/README.md`.

## 3. LLM backend

Configure gpt-oss-20b via vLLM (or another model) — see [backends.md](backends.md).

## 4. Running

Single scenario, single turn:
```bash
tests/article_scenarios/s2.sh --label turn1 --only confOf-ekaw
```
(`s2` = AML input; `s3` = reference.rdf input; `s5`/`s6` = variants).

Repeated turns (for the median [min; max] statistic):
```bash
for t in turn1 turn2 turn3 turn4 turn5; do tests/article_scenarios/s2.sh --label $t; done
```

## 5. Aggregate analysis

```bash
bash tests/article_analysis_gptoss/analyze-all.sh turn1 turn2 turn3 turn4 turn5
```
Aggregates turns, computes median [min; max] per dimension, and generates summary
charts. DeepSeek variant: `tests/article_analysis_deepseek/` (shared helpers).
The same run also extracts the per-turn LLM error/fallback rate from each run
dir's `run.log` into `errors/errors.csv` and `errors/errors_summary.csv`
(also runnable standalone: `bash tests/article_analysis_gptoss/errors/analyze.sh
turn1 … turn5` — pure log parsing, never re-runs any merging).

## Notes

- **CoMerger on `swo-acm`** does not terminate (its embedded Pellet reasoner
  exceeds the 3-min cap) — this is expected; the CoMerger column is then absent.
- Baselines are deterministic — computed once and cached
  (`outputs/.baseline_cache/`), so subsequent turns reuse the results.
- Reasoning models are slow — a full run (3 datasets × 5 turns) takes hours; set
  `LLM_REQUEST_TIMEOUT` sufficiently high.

## Smoke test (minimal check that the pipeline works)

A trivial input (2 classes + 1 relation per ontology) is enough to exercise the
whole chain merge → report → charts without the full setup:
```bash
uv run llm-onto-merger --base tiny/base.owl --candidate tiny/candidate.owl --output tiny-out/
uv run python tests/metrics_and_insights_raport.py --inputs tiny --output tiny-out/report.html tiny-out/
```
Check `tiny-out/env_diff_0.txt` (LLM decisions) and `tiny-out/charts/*.jpg` (7 dimensions).
