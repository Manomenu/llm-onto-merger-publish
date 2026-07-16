#!/usr/bin/env python3
import sys
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDFS

for path in sys.argv[1:]:
    g = Graph()
    g.parse(path)
    classes = {s for s, _, _ in g.triples((None, None, OWL.Class)) if isinstance(s, URIRef)}
    labeled   = {s for s in classes if any(True for _ in g.objects(s, RDFS.label))}
    commented = {s for s in classes if any(True for _ in g.objects(s, RDFS.comment))}
    pct = lambda n: f"({100*n/len(classes):.1f}%)" if classes else ""
    print(f"{path}")
    print(f"  owl:Class:      {len(classes)}")
    print(f"  rdfs:label:     {len(labeled)}  {pct(len(labeled))}")
    print(f"  rdfs:comment:   {len(commented)}  {pct(len(commented))}")
