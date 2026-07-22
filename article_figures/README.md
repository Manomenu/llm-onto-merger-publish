# Article figures and source data

This folder holds the result figures used in the article, the source data for
the Knowledge Completeness (KC) chart, and the raw LLM error/fallback-rate
tables (`errors_data/`).

## Figures
- `ccr_med.jpg` — Understandability (Comment Coverage Ratio)
- `conciseness_med.jpg` — Conciseness (Structural Redundancy, Syntactic Uniqueness)
- `hiq_med.jpg` — Hierarchy Integration Quality (ARC, depth, breadth)
- `kc_med.jpg` — Knowledge Completeness (NCRC, NIRC)
- `tpr_med.jpg` — Accuracy (semantic Triple Preservation Ratio)

## KC data (`kc_data/`)
One wide CSV per scenario, in `combine_turns.py` format
(`method,NCRC,NCRC_min,NCRC_max,NIRC,NIRC_min,NIRC_max`); medians in the bare
columns, min/max across the five runs in the `_min`/`_max` columns. These are
the exact inputs to `tests/article_analysis_deepseek/plot_grouped.py` that
produced `kc_med.jpg`. The figure reports the proposed framework only (one bar
group per model): the classical baselines have no external-knowledge source and
introduce no knowledge-bearing relations (at most a handful of purely formal
ones, e.g. `owl:Thing` subsumptions; $\leq 6$ NCRC, $\leq 1$ NIRC), so they are
omitted from the chart and noted in the article text instead.

## How NCRC/NIRC were computed (corrected)

The NCRC (new cross-ontology relations) and NIRC (new intra-ontology relations)
measures in `tests/metrics_def.py` were corrected:

1. **Disjoint attribution.** `_intra_source` (NIRC) now uses the same
   namespace-priority as `_from_onto1`/`_from_onto2` (NCRC), so a relabeled
   entity living in a source namespace is attributed to its source rather than
   falling through to the alias map. This makes NIRC and NCRC disjoint (a
   relation is either cross- or intra-ontology, never both).
2. **Shared novelty baseline.** NIRC now measures novelty against
   `union_keys_norm` (alias/relabel-normalised), the same baseline NCRC uses, so
   a relation that merely survived OBO relabeling is not mistaken for new.
3. **Source-relation guard.** A relation whose raw local-name triple already
   appears verbatim in the input union is not counted as new (removes false
   positives such as AROM re-serialising SWO obsolescence axioms like
   `X IAO_0100001 Y` or `X subClassOf ObsoleteClass`, which exist in the input).

Numbers are computed with `PYTHONHASHSEED=0` for reproducibility (the alias-map
construction is otherwise sensitive to hash ordering). Regenerate the chart with:

```
python tests/article_analysis_deepseek/plot_grouped.py \
  --dataset confOf-ekaw kc_data/confOf-ekaw.csv \
  --dataset human-mouse kc_data/human-mouse.csv \
  --dataset swo-acm      kc_data/swo-acm.csv \
  --output kc_med.jpg \
  --ylabel-for NCRC "New cross-onto relations (log)" \
  --ylabel-for NIRC "New intra-onto relations (log)" \
  --log-for NCRC --log-for NIRC --bar-fmt "%.0f" --n-turns 5
```

## LLM error/fallback rate (`errors_data/`)

Raw per-turn error/fallback-rate tables for the proposed framework, recovered
from each article run's `run.log` (pure log parsing — see
`tests/article_analysis_deepseek/error_rate_turns.py` and each side's
`tests/article_analysis_*/errors/analyze.sh`, which `analyze-all.sh` runs
automatically at the end of the aggregation).

- `errors_gptoss.csv` / `errors_deepseek.csv` — one row per
  scenario × dataset × turn (scenarios: s2/s5 = AML input, s3/s6 =
  reference-alignment input). Columns: environment total, real failures,
  failure modes (`parse_fail` — unparsable LLM response, triggering the
  deterministic fallback merge; `empty_graph_total`; `other_error`),
  degenerate empty-input environments (empty response where the environment
  had zero URI–URI input triples — correct behaviour, not a failure, reported
  separately), and `real_error_rate_pct` = real failures / total environments.
  `source_log` records the exact run.log each row was parsed from (paths as in
  the original experiment tree).
- `errors_summary_gptoss.csv` / `errors_summary_deepseek.csv` — per
  scenario × dataset: median and min/max across the five turns.

Headline numbers (AML input, median over 5 turns): gpt-oss falls back on
0/16 (confOf-ekaw), 1/1396 = 0.07% (human-mouse) and 0/43 (swo-acm)
environments; DeepSeek on 0/16, 6/1396 = 0.43% and 2/43 = 4.65% — i.e. the
LLM makes the merge decision in ≥95% of environments (≥99.9% for gpt-oss).
