import argparse
import os
from pathlib import Path

from pydantic import BaseModel

from .logger import get_logger
from .settings import settings

log = get_logger(__name__)

DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"


class LoadedArguments(BaseModel):
    base_path: str
    candidate_path: str
    alignment_tool: str = "aml"
    alignment_file: str | None = None
    output_dir: str
    merge_env_max_chars: int = 10_000
    parallel_llm_request_count: int = 4
    model: str | None = None
    run_nonce: str | None = None


def load_arguments() -> LoadedArguments:
    parser = argparse.ArgumentParser(
        description="Ontology Merging System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run llm-onto-merger --base base.owl --candidate cand.owl\n"
            "  uv run llm-onto-merger --base base.owl --candidate cand.owl "\
            "--alignment-tool aml --output merged.owl\n"
        ),
    )
    parser.add_argument("--base", required=True, help="Path to base ontology")
    parser.add_argument(
        "--candidate", required=True, help="Path to candidate ontology"
    )
    parser.add_argument(
        "--alignment-tool",
        default="aml",
        help="Alignment tool to use (default: aml)",
    )
    parser.add_argument(
        "--alignment-file",
        default=None,
        help=(
            "Path to a pre-computed OAEI alignment file (RDF/XML, same format as "
            "AML/LogMap output).  When set, the matcher (--alignment-tool) is "
            "skipped and these alignments are fed directly into the merge "
            "pipeline — e.g. to inject the OAEI reference (gold-standard) alignment."
        ),
    )
    parser.add_argument(
        "--output", default=None, help="Output directory (merged_ontology.owl and debug files are saved here)"
    )
    parser.add_argument(
        "--max-env-chars",
        type=int,
        default=10_000,
        help="Max characters per MergeEnvironment string (default: 10000)",
    )
    parser.add_argument(
        "--parallel-llm-request-count",
        type=int,
        default=None,
        help=(
            f"Number of concurrent LLM requests.  When omitted, falls back to "
            f"the PARALLEL_LLM_REQUEST_COUNT value from .env / settings "
            f"(current: {settings.parallel_llm_request_count})."
        ),
    )
    parser.add_argument(
        "--model",
        nargs="?",
        const=DEFAULT_OPENROUTER_MODEL,
        default=None,
        help=(
            "Route the merge LLM calls through OpenRouter instead of the "
            "default Ollama/vLLM backend. Pass a model name (e.g. "
            "'openai/gpt-4o-mini') to use that OpenRouter model, or pass "
            f"--model with no value to use the default ({DEFAULT_OPENROUTER_MODEL}). "
            "Omit --model entirely to keep using the current Ollama/vLLM setup. "
            "Requires OPENROUTER_API_KEY in .env."
        ),
    )
    parser.add_argument(
        "--run-nonce",
        default=None,
        help=(
            "Opaque per-run identifier prepended to the LLM system instructions. "
            "Repeated measurement runs of the same dataset should pass a "
            "different nonce so their prompts share no common prefix — this "
            "defeats provider-side prompt/prefix caching (OpenRouter, DeepSeek) "
            "and guarantees independently sampled responses per run."
        ),
    )
    args = parser.parse_args()

    # Validation
    for path_attr in ["base", "candidate"]:
        path = getattr(args, path_attr)
        if not os.path.exists(path):
            parser.error(f"File not found for --{path_attr}: {path}")
        if not os.path.isfile(path):
            parser.error(f"Path for --{path_attr} is not a file: {path}")
    if args.alignment_file is not None and not os.path.isfile(args.alignment_file):
        parser.error(f"File not found for --alignment-file: {args.alignment_file}")
    if args.model is not None and not settings.openrouter_api_key:
        parser.error(
            "--model requires OPENROUTER_API_KEY to be set in .env"
        )

    if args.output is not None:
        output_dir = args.output
    elif settings.use_vllm:
        output_dir = f"tests/vllm_outputs/{Path(args.base).parent.name}"
    else:
        output_dir = "tests/outputs"

    parallel_llm_request_count = (
        args.parallel_llm_request_count
        if args.parallel_llm_request_count is not None
        else settings.parallel_llm_request_count
    )

    loaded = LoadedArguments(
        base_path=args.base,
        candidate_path=args.candidate,
        alignment_tool=args.alignment_tool,
        alignment_file=args.alignment_file,
        output_dir=output_dir,
        merge_env_max_chars=args.max_env_chars,
        parallel_llm_request_count=parallel_llm_request_count,
        model=args.model,
        run_nonce=args.run_nonce,
    )
    log.info(
        "Arguments loaded | base: %s | candidate: %s | alignment_tool: %s"
        " | alignment_file: %s | output_dir: %s | max_env_chars: %d"
        " | parallel_llm_request_count: %d | model: %s | run_nonce: %s",
        loaded.base_path,
        loaded.candidate_path,
        loaded.alignment_tool,
        loaded.alignment_file,
        loaded.output_dir,
        loaded.merge_env_max_chars,
        loaded.parallel_llm_request_count,
        loaded.model or "(default backend)",
        loaded.run_nonce or "(none)",
    )
    return loaded
