#!/usr/bin/env python3
"""Apply the verdicts to the sample and print the two summary tables.

Table A (exhaustive): what the whole counted population consists of.
Table B (sample):     of the concept-to-concept assertions, how many hold.

The overall precision of a stratum composes the two tiers:

    P(counted relation is correct domain knowledge)
        = share(judgeable) x P(correct | judgeable)

with a Wilson 95% interval on the second factor.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from judgements import VERDICTS  # noqa: E402

JUDGEABLE = {"taxonomic", "relational", "nonstandard_predicate"}
CATEGORY_ORDER = [
    "taxonomic", "relational", "nonstandard_predicate",
    "schema_axiom", "equivalence",
    "annotation", "nonconcept_endpoint", "owl_vocabulary",
    "vacuous_selfloop", "provenance", "prompt_leakage", "class_as_predicate",
]
VERDICT_ORDER = ["correct", "plausible", "uninformative", "incorrect"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classified", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out-sample", required=True)
    ap.add_argument("--out-summary", required=True)
    args = ap.parse_args()

    pop = list(csv.DictReader(open(args.classified, encoding="utf-8")))
    sample = list(csv.DictReader(open(args.sample, encoding="utf-8")))

    missing = [r["id"] for r in sample if int(r["id"]) not in VERDICTS]
    if missing:
        sys.exit(f"no verdict for sample ids: {missing}")
    for r in sample:
        r["verdict"], r["reason"] = VERDICTS[int(r["id"])]

    with open(args.out_sample, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sample[0].keys()))
        w.writeheader()
        w.writerows(sample)

    rows_out: list[dict] = []

    print("\n" + "=" * 92)
    print("TABLE A — composition of the counted population (exhaustive, 5 runs x 2 models)")
    print("=" * 92)
    hdr = f"{'dataset':13s}{'meas':6s}{'n':>7s}  " + "".join(f"{c[:11]:>12s}" for c in CATEGORY_ORDER[:6])
    print(hdr)
    for ds in ["confOf-ekaw", "human-mouse", "swo-acm"]:
        for meas in ["NCRC", "NIRC"]:
            sub = [r for r in pop if r["dataset"] == ds and r["measure"] == meas]
            c = Counter(r["category"] for r in sub)
            n = len(sub)
            cells = "".join(f"{100 * c[k] / n:11.1f}%" for k in CATEGORY_ORDER[:6])
            print(f"{ds:13s}{meas:6s}{n:7d}  {cells}")

    print("\n  remaining categories (% of n):")
    print(f"  {'dataset':13s}{'meas':6s}" + "".join(f"{c[:13]:>15s}" for c in CATEGORY_ORDER[5:]))
    for ds in ["confOf-ekaw", "human-mouse", "swo-acm"]:
        for meas in ["NCRC", "NIRC"]:
            sub = [r for r in pop if r["dataset"] == ds and r["measure"] == meas]
            c = Counter(r["category"] for r in sub)
            n = len(sub)
            cells = "".join(f"{100 * c[k] / n:14.1f}%" for k in CATEGORY_ORDER[5:])
            print(f"  {ds:13s}{meas:6s}{cells}")

    print("\n" + "=" * 92)
    print("TABLE B — domain correctness of the concept-to-concept assertions (n=30 per stratum)")
    print("=" * 92)
    print(f"{'dataset':13s}{'meas':6s}{'judgeable':>10s}{'correct':>9s}{'plaus':>7s}{'uninf':>7s}{'incorr':>8s}"
          f"{'  P(correct|judg)':>18s}{'  overall precision':>21s}")
    for ds in ["confOf-ekaw", "human-mouse", "swo-acm"]:
        for meas in ["NCRC", "NIRC"]:
            sub = [r for r in pop if r["dataset"] == ds and r["measure"] == meas]
            n = len(sub)
            share = sum(1 for r in sub if r["category"] in JUDGEABLE) / n
            js = [r for r in sample if r["dataset"] == ds and r["measure"] == meas]
            vc = Counter(r["verdict"] for r in js)
            k, m = vc["correct"], len(js)
            lo, hi = wilson(k, m)
            print(f"{ds:13s}{meas:6s}{100 * share:9.1f}%{vc['correct']:9d}{vc['plausible']:7d}"
                  f"{vc['uninformative']:7d}{vc['incorrect']:8d}"
                  f"   {100 * k / m:5.1f}% [{100 * lo:4.1f};{100 * hi:4.1f}]"
                  f"      {100 * share * k / m:5.1f}% [{100 * share * lo:4.1f};{100 * share * hi:4.1f}]")
            rows_out.append({
                "dataset": ds, "measure": meas, "population": n,
                "judgeable_share": round(share, 4),
                "sample_n": m,
                "correct": vc["correct"], "plausible": vc["plausible"],
                "uninformative": vc["uninformative"], "incorrect": vc["incorrect"],
                "p_correct_given_judgeable": round(k / m, 4),
                "p_correct_ci_low": round(lo, 4), "p_correct_ci_high": round(hi, 4),
                "overall_precision": round(share * k / m, 4),
                "overall_ci_low": round(share * lo, 4),
                "overall_ci_high": round(share * hi, 4),
            })

    # Strata were sampled equally but differ in size by two orders of magnitude,
    # so the pooled figure must reweight each stratum by its share of the
    # population; an unweighted pool would let confOf-ekaw count as much as
    # human-mouse.
    allj = Counter(r["verdict"] for r in sample)
    N = len(pop)
    share_all = sum(1 for r in pop if r["category"] in JUDGEABLE) / N
    weighted = {v: 0.0 for v in VERDICT_ORDER}
    w_overall = w_lo = w_hi = 0.0
    for row in rows_out:
        w = row["population"] / N
        m_s = row["sample_n"]
        for v in VERDICT_ORDER:
            weighted[v] += w * row["judgeable_share"] * row[v] / m_s
        w_overall += w * row["overall_precision"]
        w_lo += w * row["overall_ci_low"]
        w_hi += w * row["overall_ci_high"]
    p_given = w_overall / share_all
    print("-" * 92)
    print(f"{'POOLED (pop.-weighted)':22s}{100 * share_all:.1f}% judgeable   "
          f"correct {100 * weighted['correct']:.1f}%  plausible {100 * weighted['plausible']:.1f}%  "
          f"uninformative {100 * weighted['uninformative']:.1f}%  incorrect {100 * weighted['incorrect']:.1f}%"
          f"  of ALL counted relations")
    print(f"{'':22s}P(correct | judgeable) = {100 * p_given:.1f}%   "
          f"overall precision = {100 * w_overall:.1f}% [{100 * w_lo:.1f};{100 * w_hi:.1f}]")
    print(f"{'':22s}(unweighted sample, for reference: {allj['correct']}/{len(sample)} = "
          f"{100 * allj['correct'] / len(sample):.1f}% correct)")

    print("\nSupplementary, exhaustive over the population:")
    taxo = [r for r in pop if r["category"] == "taxonomic"]
    red = sum(1 for r in taxo if r["redundant_shortcut"] == "1")
    print(f"  taxonomic edges already entailed elsewhere in the merged graph: "
          f"{red}/{len(taxo)} ({100 * red / len(taxo):.1f}%)")
    minted = sum(1 for r in pop if r.get("endpoint_minted") == "1")
    print(f"  relations with an endpoint absent from both inputs:            "
          f"{minted}/{len(pop)} ({100 * minted / len(pop):.1f}%)")

    by_model: dict[str, Counter] = defaultdict(Counter)
    for r in sample:
        by_model[r["model"]][r["verdict"]] += 1
    print("\n  by model (sample):")
    for mdl in sorted(by_model):
        c = by_model[mdl]
        tot = sum(c.values())
        print(f"    {mdl:10s} n={tot:3d}  " + "  ".join(f"{v}={c[v]}" for v in VERDICT_ORDER))

    with open(args.out_summary, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"\nsummary → {args.out_summary}\njudged sample → {args.out_sample}")


if __name__ == "__main__":
    main()
