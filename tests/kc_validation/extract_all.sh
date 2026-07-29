#!/usr/bin/env bash
# tests/kc_validation/extract_all.sh — dump the NCRC/NIRC populations of every
# run behind the article's Knowledge Completeness figures.
#
# 5 turns x 3 datasets x 2 models.  gpt-oss runs live in the variance tree
# (tests/scenarios/outputs/<turn>/<ds>-s2) except swo-acm, which was produced by
# the article batch (tests/article_scenarios/outputs/<turn>/s2/swo-acm);
# DeepSeek runs are the s5 batch throughout.
#
# PYTHONHASHSEED=0 — _build_alias_maps iterates over sets, and the reported
# NCRC/NIRC figures were computed under that seed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

OUT="tests/kc_validation/data/population.csv"
rm -f "$OUT"

run() {  # dataset model turn merged_path
  PYTHONHASHSEED=0 uv run python tests/kc_validation/extract_new_relations.py \
    --inputs "tests/inputs/$1" --merged "$4" \
    --dataset "$1" --model "$2" --run "$3" --out "$OUT"
}

for t in turn1 turn2 turn3 turn4 turn5; do
  for ds in confOf-ekaw human-mouse; do
    run "$ds" gpt-oss "$t" \
      "tests/scenarios/outputs/$t/$ds-s2/$ds-s2_aml_15k_p24/merged_ontology.owl"
  done
  run swo-acm gpt-oss "$t" \
    "tests/article_scenarios/outputs/$t/s2/swo-acm/swo-acm_aml_15k_p24/merged_ontology.owl"

  for ds in confOf-ekaw human-mouse swo-acm; do
    run "$ds" deepseek "$t" \
      "tests/article_scenarios/outputs/$t/s5/$ds/${ds}_aml_15000c_p1000_deepseek_deepseek-v4-flash/merged_ontology.owl"
  done
done

echo
echo "population → $OUT ($(( $(wc -l <"$OUT") - 1 )) rows)"
