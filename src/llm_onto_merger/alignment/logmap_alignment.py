import asyncio
import shutil
from pathlib import Path

from ..logger import get_logger
from .alignment import Alignment, AlignmentModule, parse_oaei_alignment

log = get_logger(__name__)

# LogMap writes a directory of files; this is the OAEI alignment we care about.
_OUTPUT_DIR = Path("artifacts") / "logmap_output"
_MAPPINGS_FILE = "logmap2_mappings.rdf"


class LogmapAlignmentModule(AlignmentModule):
    """Alignment module backed by the LogMap matcher.

    LogMap CLI:
      java [--add-opens] -jar logmap-matcher-4.0.jar MATCHER \\
           <iri_onto1> <iri_onto2> <output_dir> <classify_bool>

    The matcher reads `parameters.txt` from its working directory, so we set
    cwd to the jar's parent.  Output is a directory containing several files;
    we read `logmap2_mappings.rdf` — same OAEI alignment XML format as AML.

    On Java 9+ LogMap requires `--add-opens=java.base/java.lang=ALL-UNNAMED`
    to satisfy an internal Guice/cglib reflection call; without it the
    matcher dies with InaccessibleObjectException.
    """

    def __init__(
        self,
        jar_path: Path = Path("thirdparty/logmap/logmap-matcher-4.0.jar"),
        classify: bool = False,
    ):
        self.jar_path = jar_path.resolve()
        self.work_dir = self.jar_path.parent
        self.classify = classify

    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> list[Alignment]:
        base_iri = f"file:{Path(base_ontology_path).resolve()}"
        cand_iri = f"file:{Path(candidate_ontology_path).resolve()}"

        output_dir = _OUTPUT_DIR.resolve()
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)

        cmd = [
            "java",
            "--add-opens=java.base/java.lang=ALL-UNNAMED",
            "-jar",
            str(self.jar_path),
            "MATCHER",
            base_iri,
            cand_iri,
            str(output_dir),
            "true" if self.classify else "false",
        ]

        log.info("Running LogMap: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.work_dir),
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"LogMap failed with return code {process.returncode}.\n"
                f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
            )

        mapping_file = output_dir / _MAPPINGS_FILE
        if not mapping_file.exists():
            raise RuntimeError(
                f"LogMap did not produce {mapping_file}; check stderr above.\n"
                f"Directory contents: {list(output_dir.iterdir())}"
            )

        log.info("Alignment written to %s", mapping_file)
        alignments = parse_oaei_alignment(mapping_file)
        log.info("Loaded %d alignments from %s", len(alignments), mapping_file)
        return alignments
