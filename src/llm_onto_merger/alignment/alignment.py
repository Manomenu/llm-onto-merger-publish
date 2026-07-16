import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel

_NS_ALIGN = "http://knowledgeweb.semanticweb.org/heterogeneity/alignment"
_NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


class Alignment(BaseModel):
    entity1: str
    entity2: str
    measure: float
    relation: str

    def to_string(self) -> str:
        def _ln(uri: str) -> str:
            return uri.split("#")[-1] if "#" in uri else uri.rsplit("/", 1)[-1]

        return f"{_ln(self.entity1)} ↔ {_ln(self.entity2)} (relation: {self.relation})"


class AlignmentModule(ABC):
    @abstractmethod
    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> list[Alignment]:
        """Compute alignment between base and candidate ontologies."""


def parse_oaei_alignment(alignment_path: Path) -> list[Alignment]:
    """Parse an OAEI (EDOAL) alignment RDF/XML file and return its cells.

    Format produced by both AML and LogMap:
      <Alignment>
        <map><Cell>
          <entity1 rdf:resource="..."/>
          <entity2 rdf:resource="..."/>
          <measure rdf:datatype="xsd:float">0.79</measure>
          <relation>=</relation>
        </Cell></map>
        ...
      </Alignment>
    """
    tree = ET.parse(alignment_path)
    root = tree.getroot()

    alignment_el = root.find(f"{{{_NS_ALIGN}}}Alignment")
    if alignment_el is None:
        raise ValueError(f"No <Alignment> element found in {alignment_path}")

    alignments: list[Alignment] = []
    for map_el in alignment_el.findall(f"{{{_NS_ALIGN}}}map"):
        cell = map_el.find(f"{{{_NS_ALIGN}}}Cell")
        if cell is None:
            continue
        entity1_el = cell.find(f"{{{_NS_ALIGN}}}entity1")
        entity2_el = cell.find(f"{{{_NS_ALIGN}}}entity2")
        entity1 = entity1_el.get(f"{{{_NS_RDF}}}resource") if entity1_el is not None else None
        entity2 = entity2_el.get(f"{{{_NS_RDF}}}resource") if entity2_el is not None else None
        if not entity1 or not entity2:
            continue
        alignments.append(
            Alignment(
                entity1=entity1,
                entity2=entity2,
                # Reference alignments occasionally omit measure/relation;
                # default to a confident equivalence instead of crashing.
                measure=float(cell.findtext(f"{{{_NS_ALIGN}}}measure") or 1.0),
                relation=cell.findtext(f"{{{_NS_ALIGN}}}relation") or "=",
            )
        )
    return alignments


