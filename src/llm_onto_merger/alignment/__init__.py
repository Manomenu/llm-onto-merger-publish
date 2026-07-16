from .alignment import AlignmentModule
from .aml_alignment import AmlAlignmentModule
from .file_alignment import FileAlignmentModule
from .logmap_alignment import LogmapAlignmentModule

alignment_modules_dict: dict[str, type[AlignmentModule]] = {
    "aml": AmlAlignmentModule,
    "logmap": LogmapAlignmentModule,
}
