from pathlib import Path

from rdflib import Graph

from llm_onto_merger.alignment.aml_alignment import AmlAlignmentModule
from llm_onto_merger.extract_environments import ExtractEnvironmentsModule, MergeEnvironmentConfig

_HERE = Path(__file__).parent
_OUTPUTS = _HERE / "outputs"


if __name__ == "__main__":
    onto_1 = Graph().parse(_HERE / "inputs/cmt.owl")
    onto_2 = Graph().parse(_HERE / "inputs/edas.owl")
    alignments = AmlAlignmentModule()._load_alignments(_OUTPUTS / "alignment.owl")

    extractor = ExtractEnvironmentsModule(MergeEnvironmentConfig(max_chars=4000))
    envs, _, _ = extractor.extract(onto_1, onto_2, alignments)
    print(f"Extracted {len(envs)} environments")

    for i, env in enumerate(envs):
        out_path = _OUTPUTS / f"env_{i}.txt"
        out_path.write_text(env.to_string(), encoding="utf-8")
        print(f"Saved: {out_path}")
