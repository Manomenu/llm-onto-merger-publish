# Quality of the relations counted by NCRC and NIRC

NCRC and NIRC are **volume** measures: they count triples in the merged
ontology that are new with respect to the union of the inputs. Volume is not
quality — being new is not the same as being correct, and not even the same as
being a statement about the domain. This folder reports what the counted
relations actually are.

The study has two tiers. The first is **exhaustive**: every one of the 21 854
counted relations is assigned a category by rule. The second is a
**stratified random sample** of the relations the rules cannot decide — genuine
concept-to-concept assertions, whose truth needs a reader.

## Population

Every run behind the article's Knowledge Completeness figures: 5 runs x 3
scenarios x 2 models (gpt-oss-20b, DeepSeek-v4-flash), AML-alignment input.
Nothing is selected — the population is the multiset of all counted relations
over all runs, so a relation the framework produces repeatedly weighs
accordingly.

`tests/kc_validation/extract_new_relations.py` reproduces the selection logic of
`tests/metrics_def.py` verbatim (importing its helpers rather than
reimplementing them) and asserts that the number of extracted triples equals the
count `_compute_self_metrics` reports for the same inputs. All 30 runs match the
per-run figures in `tests/article_analysis_*/knowledge_completeness/work/`
exactly, so this is the same population the article reports, not a
reconstruction of it.

## Tier 1 — what the counted relations are (exhaustive)

| category | meaning |
|---|---|
| `taxonomic` | `rdfs:subClassOf` between two concepts |
| `relational` | another object property between two concepts |
| `nonstandard_predicate` | a meaningful relation whose IRI was minted inside a reserved namespace (`rdfs:partOf`, `oboInOwl:partOf`, `rdf:subClassOf`) |
| `schema_axiom` | `rdfs:domain` / `range` / `subPropertyOf` / `rdf:type` |
| `equivalence` | `equivalentClass` / `sameAs` / `exactMatch` — restates the alignment |
| `annotation` | synonym / definition / label / comment: metadata, not a relation |
| `nonconcept_endpoint` | an endpoint is not a concept — an OBO annotation holder (`…#genidNNN`), a placeholder minted for an anonymous class expression, or annotation text serialized as an IRI |
| `owl_vocabulary` | an endpoint is `owl:Thing` |
| `vacuous_selfloop` | subject == object |
| `provenance` | the framework's own `merged#alias` housekeeping |
| `prompt_leakage` | an endpoint is a class the model minted out of the prompt's structure — the KG2Code environment is rendered with `[Border_1]` / `[Border_2]` sections, and `BorderEntity` is that header reified as a class |
| `class_as_predicate` | the predicate slot holds something that is not a property |

Share of each stratum's counted relations (percentages of column `n`):

| dataset | measure | n | taxonomic | relational | nonstd. pred. | schema | equiv. | annotation | non-concept | owl:Thing | self-loop | provenance | prompt leak | class-as-pred |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| confOf-ekaw | NCRC | 148 | 80.4 | 5.4 | 0.0 | 11.5 | 0.0 | 0.0 | 1.4 | 0.0 | 0.0 | 0.0 | 0.0 | 1.4 |
| confOf-ekaw | NIRC | 144 | 60.4 | 4.2 | 2.8 | 13.9 | 0.0 | 0.0 | 6.9 | 0.0 | 11.8 | 0.0 | 0.0 | 0.0 |
| human-mouse | NCRC | 9756 | 51.9 | 0.4 | 0.9 | 0.1 | 0.1 | 6.4 | 23.7 | 16.2 | 0.0 | 0.3 | 0.0 | 0.0 |
| human-mouse | NIRC | 9729 | 34.0 | 0.2 | 0.5 | 0.1 | 0.0 | 10.7 | 30.3 | 3.5 | 20.7 | 0.0 | 0.0 | 0.0 |
| swo-acm | NCRC | 324 | 48.1 | 30.9 | 3.4 | 1.2 | 0.9 | 9.6 | 3.1 | 1.9 | 0.0 | 0.0 | 0.9 | 0.0 |
| swo-acm | NIRC | 1753 | 66.4 | 11.4 | 0.0 | 10.6 | 0.6 | 2.4 | 1.7 | 0.2 | 1.8 | 0.0 | 4.9 | 0.0 |

**47.7 %** of the whole population is a concept-to-concept assertion
(`taxonomic` + `relational` + `nonstandard_predicate`). The rest is dominated by
two families, both concentrated in *human-mouse*, the scenario that produces the
large counts:

- **inherited annotations re-attached to the merged entity** (`annotation` +
  `nonconcept_endpoint`, 30 % of human-mouse NCRC and 41 % of its NIRC). Traced
  end to end: human.owl asserts `NCI_C13060 hasRelatedSynonym human#genid1522`,
  where `genid1522` is a label holder carrying "Sensory Ganglion". The merge
  writes the merged entity under the *mouse* IRI, so the merged ontology
  contains `mouse#sensory_ganglion hasRelatedSynonym human#genid1522` — the same
  annotation, now spanning two namespaces, and therefore counted as a new
  cross-ontology relation. Alias normalization does not absorb it because it
  rewrites merged names back to source identifiers, and here both endpoints
  already *are* source identifiers.
- **`owl:Thing` subsumptions and self-loops** (16 % of human-mouse NCRC, 21 % of
  its NIRC). Counting rows by category understates the first of these, because
  categories are assigned first-match-first: **3244 counted relations (14.8 % of
  the population) have `owl:Thing` as their object**, but those whose subject is
  also an annotation holder are booked under `nonconcept_endpoint`. `owl:Thing`
  is reachable at all because source attribution falls back to the alias map,
  which can tag the local name `Thing` as belonging to both sources.

Two further exhaustive checks:

- **29.4 %** of all new `rdfs:subClassOf` edges (2908 / 9893) are already
  entailed by the rest of the merged graph — the same subsumption is derivable
  through another path, so the edge is a shortcut, not a new subsumption.
- **5.9 %** of counted relations have an endpoint absent from both inputs: the
  model minted an entity inside a source namespace (e.g.
  `http://www.ebi.ac.uk/swo/version/Matlab_R14`, which does not exist in SWO),
  and NCRC/NIRC attribute it to that source by namespace.

## Tier 2 — are the concept-to-concept assertions true?

Frame: the `taxonomic` + `relational` + `nonstandard_predicate` rows. Strata:
dataset x measure, six in all, pooled over runs and models. 30 drawn per
stratum, seed 20260728, `sample_for_review.py`. Verdicts were made from the
entity labels plus the **source** ontologies' definitions — never the merged
ontology's own generated comments, since judging a model's relations against its
own prose would be circular.

| verdict | meaning |
|---|---|
| `correct` | true of the domain, with the asserted predicate |
| `plausible` | defensible but imprecise — a synonym pair asserted as subsumption, an over-general parent, an ambiguous label |
| `uninformative` | not false, but empty: an untyped `merged#linkTo`, subsumption under the top concept, a restatement of the alignment |
| `incorrect` | false, including part-whole asserted as subsumption and duplicate concepts asserted as sub/superclass |

| dataset | measure | judgeable share | correct | plausible | uninformative | incorrect | P(correct \| judgeable) 95 % CI |
|---|---|---:|---:|---:|---:|---:|---|
| confOf-ekaw | NCRC | 85.8 % | 14 | 8 | 2 | 6 | 46.7 % [30.2; 63.9] |
| confOf-ekaw | NIRC | 67.4 % | 18 | 1 | 2 | 9 | 60.0 % [42.3; 75.4] |
| human-mouse | NCRC | 53.2 % | 20 | 4 | 1 | 5 | 66.7 % [48.8; 80.8] |
| human-mouse | NIRC | 34.7 % | 25 | 1 | 0 | 4 | 83.3 % [66.4; 92.7] |
| swo-acm | NCRC | 82.4 % | 13 | 10 | 5 | 2 | 43.3 % [27.4; 60.8] |
| swo-acm | NIRC | 77.8 % | 22 | 2 | 2 | 4 | 73.3 % [55.6; 85.8] |

Strata differ in size by two orders of magnitude, so the pooled figure reweights
each stratum by its share of the population. Of **all** counted relations:

- **34.3 %** [26.0; 40.3] are correct new domain knowledge
- 4.7 % are plausible
- 1.5 % are uninformative
- 7.2 % are incorrect
- 52.3 % are not concept-to-concept assertions at all

Equivalently, roughly **one in three counted relations is a correct new domain
statement**, and among the assertions that are about the domain at all, 72 %
hold.

Recurring error types in the `incorrect` rows: part-whole asserted as
subsumption (`Conference_Session ⊑ Conference`, `Jugular_Foramen ⊑
Base_of_the_Skull`, `Palate_Bone ⊑ Skull`); lexical false friends
(`triceps_surae ⊑ Triceps` — calf group under triceps brachii); category errors
(`Blood_Vessel ⊑ Organism`, `Anatomical_Structure ⊑ Living_Being`); and
duplicate concepts asserted as sub/superclass, sometimes in both directions at
once (`ekaw#Conference_ ⊑ confOf#Conference` together with its converse).

## Caveats — read before citing these numbers

1. **The verdicts are an LLM-assisted first pass, not an expert review.** They
   were produced by an assistant model, and two of the systems under evaluation
   are language models. `sample_judged.csv` carries an empty `author_verdict`
   column for exactly this reason: the sample is meant to be re-read and signed
   off by the authors, and only the confirmed column should be reported as
   validation.
2. **The `correct` / `plausible` boundary is a judgement call.** Both columns
   are reported separately so a reader can set the threshold differently.
3. **The by-model split in `summarise.py` is confounded.** The sample is
   stratified by dataset and measure, not by model, so the two models are drawn
   in unequal numbers and unevenly across scenarios. It is suggestive, not a
   comparison.
4. **n = 30 per stratum** gives intervals about ±17 pp wide per stratum. The
   pooled interval is narrower but inherits the same stratum-level noise.

## Files

- `population_classified.csv.gz` — all 21 854 counted relations with
  `category`, `redundant_shortcut` and `endpoint_minted`
- `sample_judged.csv` — the 180 sampled relations with verdict, reason, source
  definitions, and the empty `author_verdict` column
- `summary.csv` — the per-stratum table above

## Reproduction

```bash
# 1. dump the populations (asserts the counts match metrics_def.py)
bash tests/kc_validation/extract_all.sh

# 2. rule-based categories + redundancy of new subsumptions
PYTHONHASHSEED=0 uv run python tests/kc_validation/classify_relations.py \
    --population tests/kc_validation/data/population.csv \
    --out        tests/kc_validation/data/population_classified.csv

# 3. flag endpoints absent from both inputs
PYTHONHASHSEED=0 uv run python tests/kc_validation/check_endpoints.py \
    --classified tests/kc_validation/data/population_classified.csv \
    --out        tests/kc_validation/data/population_classified.csv

# 4. draw the stratified sample
PYTHONHASHSEED=0 uv run python tests/kc_validation/sample_for_review.py \
    --classified tests/kc_validation/data/population_classified.csv \
    --per-stratum 30 --seed 20260728 \
    --out tests/kc_validation/data/sample_to_judge.csv

# 5. apply the verdicts and print both tables
python tests/kc_validation/summarise.py \
    --classified   tests/kc_validation/data/population_classified.csv \
    --sample       tests/kc_validation/data/sample_to_judge.csv \
    --out-sample   tests/kc_validation/data/sample_judged.csv \
    --out-summary  tests/kc_validation/data/summary.csv
```

`PYTHONHASHSEED=0` is required: `_build_alias_maps` iterates over sets, and the
NCRC/NIRC figures reported in the article were computed under that seed.
