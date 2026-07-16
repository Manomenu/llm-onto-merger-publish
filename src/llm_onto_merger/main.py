from pathlib import Path

from llm_onto_merger.alignment import FileAlignmentModule, alignment_modules_dict
from llm_onto_merger.merger import LLMOntologyMerger

from .load_arguments import load_arguments


async def _main():
    loaded_args = load_arguments()

    # A provided --alignment-file bypasses the matcher (--alignment-tool) and
    # feeds the given OAEI alignment directly (e.g. the reference alignment).
    if loaded_args.alignment_file:
        alignment_module = FileAlignmentModule(Path(loaded_args.alignment_file))
    else:
        alignment_module = alignment_modules_dict[loaded_args.alignment_tool]()

    await LLMOntologyMerger.merge(loaded_args, alignment_module)


def main():
    import asyncio

    asyncio.run(_main())


if __name__ == "__main__":
    main()
