from pathlib import Path

from ..logger import get_logger
from .alignment import Alignment, AlignmentModule, parse_oaei_alignment

log = get_logger(__name__)


class FileAlignmentModule(AlignmentModule):
    """Alignment module that loads a pre-computed OAEI alignment file instead of
    running a matcher (AML/LogMap).

    Used to bypass the matching step and feed a ready alignment — e.g. the OAEI
    reference (gold-standard) alignment — directly into the merge pipeline.  The
    file must be in the same OAEI/EDOAL RDF/XML format that AML and LogMap emit.
    """

    def __init__(self, alignment_path: Path):
        self.alignment_path = Path(alignment_path)

    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> list[Alignment]:
        if not self.alignment_path.exists():
            raise FileNotFoundError(
                f"Alignment file not found: {self.alignment_path}"
            )
        alignments = parse_oaei_alignment(self.alignment_path)
        log.info(
            "Loaded %d alignments from provided file %s",
            len(alignments),
            self.alignment_path,
        )
        return alignments
