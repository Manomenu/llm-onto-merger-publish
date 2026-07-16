import asyncio
import json
from pathlib import Path

from rdflib import Graph

from llm_onto_merger.alignment.alignment import AlignmentModule
from llm_onto_merger.debug import (
    save_diff_debug,
    save_insights_debug,
    save_post_merge_debug,
    save_pre_merge_debug,
)
from llm_onto_merger.extract_environments import (
    ExtractEnvironmentsModule,
    MergeEnvironmentConfig,
    build_namespace_codec,
)
from llm_onto_merger.integrate_environments import integrate_environments
from llm_onto_merger.load_arguments import LoadedArguments
from llm_onto_merger.logger import get_logger
from llm_onto_merger.merge_environments.agent import build_merge_agent
from llm_onto_merger.merge_environments.module import MergeEnvironmentsModule
from llm_onto_merger.alignment.alignment import Alignment
from llm_onto_merger.ontology import apply_alignments, create_ontology, save_ontology
from llm_onto_merger.settings import settings

log = get_logger(__name__)


class LLMOntologyMerger:
    @staticmethod
    async def merge(
        args: LoadedArguments,
        alignment_module: AlignmentModule,
    ) -> None:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        onto_1, renames_1 = create_ontology(Path(args.base_path))
        onto_2, renames_2 = create_ontology(Path(args.candidate_path))

        alignments = await alignment_module.create_alignment(
            args.base_path, args.candidate_path
        )

        # Naive baseline: raw graphs + original alignment URIs (no LLM relabeling),
        # so triple_preservation_ratio is comparable to the raw union input.
        raw_1 = Graph()
        raw_1.parse(str(args.base_path))
        raw_2 = Graph()
        raw_2.parse(str(args.candidate_path))
        applied_onto = apply_alignments(raw_1, raw_2, alignments)
        save_ontology(applied_onto, out_dir, name="applied_alignments")

        all_renames = {**renames_1, **renames_2}
        if all_renames:
            alignments = [
                Alignment(
                    entity1=all_renames.get(a.entity1, a.entity1),
                    entity2=all_renames.get(a.entity2, a.entity2),
                    measure=a.measure,
                    relation=a.relation,
                )
                for a in alignments
            ]
            log.info(
                "Alignment URIs updated after relabeling: %d renames available",
                len(all_renames),
            )

        # Save relabeling map so metrics can normalise TPR against raw union triples.
        # Format: {old_local_name: new_local_name} for every entity relabelled by create_ontology.
        if all_renames:
            def _local_name(uri: str) -> str:
                idx = max(uri.rfind("#"), uri.rfind("/"))
                return uri[idx + 1:] if idx >= 0 else uri

            relabeling_local = {
                _local_name(old): _local_name(new)
                for old, new in all_renames.items()
            }
            relabeling_path = out_dir / "relabeling_map.json"
            relabeling_path.write_text(
                json.dumps(relabeling_local, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("Saved relabeling map: %d entries → %s", len(relabeling_local), relabeling_path)

        # Orient each alignment so entity1 ∈ onto_1 and entity2 ∈ onto_2.  AML
        # emits pairs in (source=base, target=candidate) order, but external
        # alignment files (e.g. the OAEI reference) may list them reversed.  A
        # reversed pair makes both seeds unresolvable in their expected ontology
        # → empty merge environment.  Swap reversed pairs; leave pairs matching
        # neither orientation untouched.
        onto_1_subjects = {str(s) for s in onto_1.subjects()}
        onto_2_subjects = {str(s) for s in onto_2.subjects()}
        swapped = 0
        oriented: list[Alignment] = []
        for a in alignments:
            forward = a.entity1 in onto_1_subjects and a.entity2 in onto_2_subjects
            reversed_ = a.entity1 in onto_2_subjects and a.entity2 in onto_1_subjects
            if reversed_ and not forward:
                oriented.append(Alignment(
                    entity1=a.entity2, entity2=a.entity1,
                    measure=a.measure, relation=a.relation,
                ))
                swapped += 1
            else:
                oriented.append(a)
        alignments = oriented
        if swapped:
            log.info(
                "Oriented %d/%d alignment pairs to (onto_1, onto_2) order "
                "(entity1/entity2 were reversed vs base/candidate)",
                swapped, len(alignments),
            )

        log.info("Alignments applied: %d", len(alignments))

        _, code_to_ns, ns_to_code, well_known_codes = build_namespace_codec(onto_1, onto_2)

        extractor = ExtractEnvironmentsModule(
            MergeEnvironmentConfig(max_chars=args.merge_env_max_chars)
        )
        merge_environments, onto_1_leftover, onto_2_leftover = extractor.extract(
            onto_1, onto_2, alignments,
            code_to_ns, ns_to_code, well_known_codes,
        )
        extractor.expand_extracted(
            merge_environments, onto_1_leftover, onto_2_leftover,
            ns_to_code, well_known_codes,
        )

        total     = len(merge_environments)
        semaphore = asyncio.Semaphore(args.parallel_llm_request_count)
        merger    = MergeEnvironmentsModule(
            build_merge_agent(ns_to_code, code_to_ns, args.model, args.run_nonce),
            args.model,
        )

        log.info(
            "Merging %d environments | parallel_llm_requests: %d",
            total,
            args.parallel_llm_request_count,
        )

        async def _merge_single_env(env, idx):
            async with semaphore:
                result = await merger.merge(env, idx=idx + 1, total=total)
                log.info("Merged environment %d/%d", idx + 1, total)
                return result

        results = list(
            await asyncio.gather(
                *[_merge_single_env(env, i) for i, env in enumerate(merge_environments)]
            )
        )
        merged_environments = [graph for graph, _, _ in results]
        drop_reports = [report for _, report, _ in results]
        alignment_applied_flags = [applied for _, _, applied in results]

        log.info(merger.cost_tracker.summary())

        applied_count = sum(alignment_applied_flags)
        total_alignments = len(alignment_applied_flags)
        log.info(
            "Alignment application summary: %d/%d applied by LLM (%d rejected)",
            applied_count,
            total_alignments,
            total_alignments - applied_count,
        )
        rejected_alignments = [
            {"entity1": al.entity1, "entity2": al.entity2}
            for i, applied in enumerate(alignment_applied_flags)
            if not applied
            for al in merge_environments[i].alignments
        ]
        (out_dir / "alignment_stats.json").write_text(
            json.dumps(
                {
                    "total_alignments": total_alignments,
                    "applied_count": applied_count,
                    "per_env": alignment_applied_flags,
                    "rejected_alignments": rejected_alignments,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (out_dir / "cost_stats.json").write_text(
            json.dumps(merger.cost_tracker.to_json_dict(), indent=2),
            encoding="utf-8",
        )

        if settings.debug:
            save_pre_merge_debug(
                merge_environments,
                onto_1_leftover,
                onto_2_leftover,
                out_dir,
                merged_graphs=merged_environments,
            )
            save_post_merge_debug(
                merged_environments,
                onto_1_leftover,
                onto_2_leftover,
                out_dir,
                merge_environments=merge_environments,
            )
            save_diff_debug(
                merge_environments,
                merged_environments,
                out_dir,
            )
            save_insights_debug(
                merge_environments, merged_environments, drop_reports,
                alignment_applied_flags, out_dir,
            )

        merged_onto = integrate_environments(
            merged_environments, onto_1_leftover, onto_2_leftover, code_to_ns
        )
        save_ontology(merged_onto, out_dir)
