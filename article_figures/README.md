# Article figures and source data

This folder holds the result figures used in the article, the source data for
the Knowledge Completeness (KC) chart, the Conciseness aggregates
(`conciseness_data/`), the raw LLM error/fallback-rate tables (`errors_data/`),
and the raw per-turn measure reports the aggregates are computed from
(`raw_data/`).

## Figures
- `ccr_med.png` — Understandability (Comment Coverage Ratio)
- `hiq_med.png` — Hierarchy Integration Quality (ARC, depth, breadth)
- `kc_med.png` — Knowledge Completeness (NCRC, NIRC)
- `tpr_med.png` — Accuracy (semantic Triple Preservation Ratio)
- `conciseness_med.jpg` — Conciseness (Structural Redundancy, Syntactic Uniqueness); not used
  in the article

The four article figures are PNG (lossless, as they are line art with text) at 300 dpi, with a
single shared legend above the panels. `hiq_med.png` omits the union input, which is the
reference for the %-change it plots and therefore zero throughout.

## KC data (`kc_data/`)
One wide CSV per scenario, in `combine_turns.py` format
(`method,NCRC,NCRC_min,NCRC_max,NIRC,NIRC_min,NIRC_max`); medians in the bare
columns, min/max across the five runs in the `_min`/`_max` columns. These are
the exact inputs to `tests/article_analysis_deepseek/plot_grouped.py` that
produced `kc_med.png`. The figure reports the proposed framework only (one bar
group per model): the reference methods score zero on both measures on
confOf-ekaw and swo-acm (except AROM on swo-acm: 1 NCRC, 3 NIRC) and at most 6
NCRC / 1 NIRC on human-mouse, values a logarithmic axis cannot render, so they
are omitted from the chart and given in the article text instead.

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
  --output kc_med.png \
  --ylabel-for NCRC "New cross-onto relations (log)" \
  --ylabel-for NIRC "New intra-onto relations (log)" \
  --log-for NCRC --log-for NIRC --bar-fmt "%.0f" \
  --drop-method "Applied Alignments" --drop-method AROM \
  --drop-method CoMerger --drop-method Boomer \
  --rename-method "Proposed: deepseek-v4-flash" "Proposed: DeepSeek" \
  --legend-figure --panel-height 3.0 --dpi 300
```

## How Structural Redundancy was computed (corrected)

The Structural Redundancy (SR) measure in `tests/metrics_def.py` was tightened
to count only redundancy proper: a class `c` is flagged iff it has two distinct
named parents `p1`, `p2` with `p2` an ancestor of `p1` via a subClassOf chain
avoiding `c`, so the asserted edge `c ⊑ p2` is entailed by the remaining axioms
(transitivity). A diamond — incomparable parents that merely share a common
ancestor — is legitimate multiple inheritance and is **not** counted (the
earlier criterion counted it, over-approximating redundancy). All SR values in
`conciseness_data/` and `raw_data/` were recomputed with the corrected measure
from the archived merged-ontology artifacts; every other measure is unaffected
(verified identical under `PYTHONHASHSEED=0`).

## Conciseness data (`conciseness_data/`)

One wide CSV per scenario in `combine_turns.py` format (median plus `_min`/
`_max` across the five runs) for Syntactic Uniqueness Ratio and Structural
Redundancy, all methods — the exact inputs behind `conciseness_med.jpg`.

## Raw per-turn data (`raw_data/`)

The unaggregated inputs from which every aggregate above (median [min; max])
is computed, enabling independent verification of the article's numbers:

- `raw_data/measures/{gptoss,deepseek}/turnN/m_i_raport_<dataset>.csv` — the
  complete per-run measure report (all 14 technical measures, every compared
  method plus the union input) for each of the five independent runs, computed
  from that run's final OWL artifacts with `PYTHONHASHSEED=0`.
- `raw_data/oaei/turnN.csv` — the per-run reference-alignment validation
  (rejected correct correspondences, accepted AML false-positives) for every
  method and both model variants, computed against each scenario's reference
  alignment.

Aggregating these per-turn files (median/min/max over turn1..turn5) reproduces
the tables and figures in the article and in this folder.

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
