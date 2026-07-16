# Third-party baseline tools

This directory contains **only our own wrapper/runner scripts** for the baseline
systems compared in the paper. The tools themselves (JARs, compiled binaries,
their source trees and bundled data) are **not redistributed here** for licensing
and size reasons. Obtain each tool from its official source and place it in the
corresponding subdirectory, then use the wrapper scripts provided.

Each tool is the property of its respective authors and is covered by its own
license — please consult the upstream repository.

| Subdir            | Baseline            | Obtain from |
|-------------------|---------------------|-------------|
| `aml/`            | AgreementMakerLight | https://github.com/AgreementMakerLight/AML-Project — place `AgreementMakerLight.jar` and the `store/` resources here |
| `logmap/`         | LogMap              | https://github.com/ernestojimenezruiz/logmap-matcher — place `logmap-matcher-*.jar` here (see `parameters.txt`) |
| `arom/`           | AROM                | https://github.com/inesosman/AROM — build per its README, then use `arom.sh` / `build.sh` |
| `boomer/`         | Boomer              | https://github.com/INCATools/boomer — place the Scala build/`lib/` here, then use `boomer.sh` |
| `CoMerger-1.2/`   | CoMerger            | https://github.com/fusion-jena/CoMerger (tool: http://comerger.uni-jena.de/) — place `Source_Code/` here, then use `comerger.sh` |
| `owltools/`       | OWLTools            | https://github.com/owlcollab/owltools — place the `owltools` binary here |

## Wrapper scripts kept here

- `arom/`: `arom.sh`, `build.sh`, `extract_arom_stats.py`
- `boomer/`: `boomer.sh`, `boomer_s3.sh`, `apply_boomer.py`, `generate_inputs.py`, `artifacts/prefixes.yaml`
- `CoMerger-1.2/`: `comerger.sh`, `build.sh`, `example-run.sh`
- `logmap/`: `parameters.txt`

The AgreementMakerLight and OWLTools integration is driven from
`src/llm_onto_merger/alignment/` — no wrapper is stored here for them.

> **Note (from the paper).** CoMerger did not complete on the `swo-acm` scenario
> (its embedded Pellet reasoner exceeded the time cap); this is expected.
