import asyncio
from pathlib import Path

from ..logger import get_logger
from .alignment import Alignment, AlignmentModule, parse_oaei_alignment

log = get_logger(__name__)

ALIGNMENT_OUTPUT = Path("artifacts") / "tmp_alignment.owl"


class AmlAlignmentModule(AlignmentModule):
    def __init__(
        self,
        jar_path: Path = Path("thirdparty/aml/AgreementMakerLight.jar"),
    ):
        self.jar_path = jar_path

    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> list[Alignment]:
        # AML does not create the output directory itself.
        ALIGNMENT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "java",
            "-jar",
            str(self.jar_path),
            "-s",
            str(base_ontology_path),
            "-t",
            str(candidate_ontology_path),
            "-o",
            str(ALIGNMENT_OUTPUT),
            "-a",
        ]

        log.info("Running AML: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"AML failed with return code {process.returncode}.\n"
                f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
            )

        log.info("Alignment written to %s", ALIGNMENT_OUTPUT)
        alignments = parse_oaei_alignment(ALIGNMENT_OUTPUT)
        log.info("Loaded %d alignments from %s", len(alignments), ALIGNMENT_OUTPUT)
        return alignments
