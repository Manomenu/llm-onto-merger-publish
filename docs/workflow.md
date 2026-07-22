# Detailed workflow and architecture

> Full description of the internal pipeline. Overview and quick start: [README](../README.md). What goes where: [outputs.md](outputs.md).

Below is the complete data flow from input (two `.owl` files) to output
(`merged_ontology.owl`).

### 1. Argument loading (`load_arguments.py`)

CLI arguments are parsed and input-file paths validated. The result is a
`LoadedArguments` Pydantic model holding all session parameters.

---

### 2. Ontology loading (`ontology/graph.py` → `create_ontology`)

Each ontology is read by `rdflib` from an OWL/RDF file into a `Graph`. Preprocessing follows:

- **Entity relabeling** — if an entity has an `rdfs:label`, its local URI fragment
  (the part after `#` or `/`) is replaced by the label value (spaces → `_`), and
  the `rdfs:label` triple is removed. Goal: instead of generic identifiers like
  `Class_42`, the LLM sees semantic names like `MedicalProcedure`. Entities whose
  target URI is already taken are skipped.

After this step both graphs (`onto_1`, `onto_2`) contain only semantically named
entities without redundant labels.

---

### 3. Alignment (`alignment/aml_alignment.py`)

The **AgreementMakerLight (AML)** tool is invoked as a Java process. AML analyzes
both ontologies and produces an EDOAL (XML) file listing entity pairs it considers related.

Each alignment has the form:
```
Alignment(entity1=URI, entity2=URI, measure=0.0–1.0, relation="="|"<"|">"|...)
```

- `entity1` — entity from onto_1
- `entity2` — corresponding entity from onto_2
- `measure` — match strength (0 = no similarity, 1 = identical)
- `relation` — relation type (`=` means conceptual identity, `<`/`>` subclass)

The result is a `list[Alignment]`, later sorted by descending `measure`.

---

### 4. Naive merge (baseline) (`ontology/merge.py` → `apply_alignments`)

A simple union of both graphs is created where, for each alignment, `entity2` is
"collapsed" into `entity1` — all `entity2` triples are rewritten onto `entity1`.
The result is saved as `applied_alignments.owl` in the output directory.

**Why:** this is not the final merge. It is a reference point — a baseline that
can be compared against the LLM result to assess merge quality.

---

### 5. Building the namespace codec (`merge_environment.py` → `build_namespace_codec`)

Namespaces are collected from **all positions** in both ontologies' triples
(subject, predicate, object). Then well-known NSs (`owl`, `rdf`, `rdfs`, `xsd`,
`swrl`, `protege`, ...) are added — only those not already present in the data.
Each unique namespace is assigned a short lexicographic code (`aa, ab, ac, ..., az, ba, bb, ...`):

```
http://cmt#                              →  aa
http://ekaw#                             →  ab
http://www.w3.org/1999/02/22-rdf-syntax-ns#  →  ae
http://www.w3.org/2002/07/owl#           →  ah
...
zz  →  http://merged#   ← reserved for entities created by the LLM
```

The `zz` code is always reserved and skipped in the sequence — it serves as the
namespace for entirely new entities the LLM may introduce during merging.

Returned structures:
- `uri_to_code` — full subject URI → code (for `graph_to_string`)
- `code_to_ns` — code → NS prefix (to decode the LLM's response)
- `ns_to_code` — NS prefix → code (to check well-known by code instead of string prefix)
- `well_known_codes` — frozenset of well-known NS codes

The codec is built **once**, jointly for both ontologies, before extraction and
passed down through the whole pipeline.

---

### 6. Merge-environment extraction (`extract_environments/module.py`)

Extraction runs in **two phases**. Phase 1 (`extract`) creates a skeleton — one
environment per alignment, with seed nodes in the interior and direct neighbours
in the border. Phase 2 (`expand_extracted`) iteratively pulls the border into the
environments' interiors until space or nodes run out.

---

#### Phase 1 — `ExtractEnvironmentsModule.extract`

##### 6a. Working graph copies

```python
source_1 = Graph()
source_2 = Graph()
for triple in onto_1:
    source_1.add(triple)
for triple in onto_2:
    source_2.add(triple)
```

Both graphs are copied into working copies. Seed-node triples are **moved**
(removed from source) during extraction. After all alignments are processed, what
remains in `source_1`/`source_2` are the **leftovers** — unmatched entities,
pass-through to the result.

##### 6b. Alignment pool (`_AlignmentPool`)

```python
pool = _AlignmentPool(alignments)
# _sorted — list sorted ascending by measure; pop() from the end = O(1) highest
```

`pop()` always returns the alignment with the **highest** `measure` (best matches first).

##### 6c. Building an environment (`_build_merge_environment`)

One environment per alignment:

**1. Seed — moving the direct triples**

```python
seed1 = URIRef(seed_al.entity1)   # onto_1 side
seed2 = URIRef(seed_al.entity2)   # onto_2 side

triples = move_entity_triples(seed1, source_1, sub1)
```

`move_entity_triples` moves **all** triples in which the seed is subject **or**
object — more context than just outgoing edges. After moving, the triples no
longer exist in `source_1`.

**2. Neighbour classification → border**

```python
for s, _, o in triples:
    for neighbor in (s, o):
        if isinstance(neighbor, URIRef) and neighbor not in seeds and not is_wk(neighbor):
            border_set.add(neighbor)
```

Every neighbour (URIRef, non-well-known, not already in seeds) goes to
`border_set`. No exceptions — even if a neighbour has an alignment in the pool, it
stays in the border. Its alignment will be picked up as the seed of **its own**
environment in a later iteration.

| Case | Action |
|------|--------|
| Well-known NS (`owl:`, `rdf:`, `xsd:`, ...) | skipped — the LLM knows these vocabularies |
| Already in seeds | skipped |
| Any other URIRef | → `border` |

**3. Copying border-node triples**

```python
for node in border_set1:
    for triple in source_1.triples((node, None, None)):
        border1_graph.add(triple)   # COPY, source stays unchanged
```

Border-node triples are **copied** (not moved) — the same node may appear in the
border of many environments and provide full context each time. Triples are never
consumed from source merely by belonging to a border.

> **Note:** triples that directly connect a border node to the seed (e.g.
> `(border_node, prop, seed1)`) were already moved by `move_entity_triples(seed1, ...)`
> and **will not appear** in `border1_graph`. This is correct — those relations are
> visible in `onto_1` on the seed side.

**Phase 1 result:** `(environments: list[MergeEnvironment], onto_1_leftover: Graph, onto_2_leftover: Graph)`

- `environments` — list of environments, each with: `onto_1` (seed1 triples),
  `onto_2` (seed2 triples), `border1_graph`, `border2_graph`, `alignments: [seed_al]`
- `onto_1_leftover`, `onto_2_leftover` — source remainders after extraction:
  entities without any alignment, pass-through to the result unchanged

---

#### Phase 2 — `ExtractEnvironmentsModule.expand_extracted`

After phase 1 each environment has a seed in the interior and a border at the
edge. Phase 2 iteratively pulls border nodes into the interior (`onto_1`,
`onto_2`), gradually widening the context available to the LLM.

##### Global freeze (`global_frozen`)

```python
global_frozen: set[URIRef] = {
    s
    for env in environments
    for graph in (env.onto_1, env.onto_2)
    for s, _, _ in graph
    if isinstance(s, URIRef)
}
```

At the start of phase 2, `global_frozen` contains all seed nodes from all
environments. A node once added to some environment's interior is frozen globally
— it cannot enter another environment's interior. It may still appear in other
environments' `border_graph` as context, but will not be moved from there.

##### Round-robin loop

```python
active = list(range(len(environments)))

while active:
    next_active = []
    for idx in active:
        env = environments[idx]
        did_1 = _expand_one(env.border1, ..., env.onto_1, source_1, global_frozen, is_wk)
        did_2 = _expand_one(env.border2, ..., env.onto_2, source_2, global_frozen, is_wk)

        still_has_border = bool(env.border1) or bool(env.border2)
        within_limit = env.interior_char_estimate() < config.max_chars

        if still_has_border and within_limit:
            next_active.append(idx)
    active = next_active
    if not any_expanded:
        break
```

In each round every active environment gets **one expansion step from onto_1 and
one from onto_2** (at most 2 nodes per environment per round). Thanks to
round-robin, nodes are not monopolized by the first environment — every alignment
gets a chance to grow.

An environment is removed from rotation when:
- `env.interior_char_estimate() >= max_chars` — the interior exceeded the size
  limit, or
- no more nodes in `border1` and `border2` — all were pulled in or frozen.

The loop ends when `active` is empty or an entire round expanded nothing (all
borders exhausted / frozen).

##### Expansion step — `_expand_one`

```python
def _expand_one(border, border_queued, border_graph, interior, source, global_frozen, is_wk):
    while border:
        node = border.popleft()
        if node in global_frozen or is_wk(node):
            continue          # discard — frozen or well-known, permanently

        triples = move_entity_triples(node, source, interior)
        global_frozen.add(node)

        # Remove the node's outgoing triples from border_graph — it is now in the interior
        for triple in list(border_graph.triples((node, None, None))):
            border_graph.remove(triple)

        # Discover new neighbours and add them to the border
        for s, _, o in triples:
            for neighbour in (s, o):
                if (isinstance(neighbour, URIRef)
                        and neighbour not in global_frozen
                        and not is_wk(neighbour)
                        and neighbour not in border_queued):
                    border.append(neighbour)
                    border_queued.add(neighbour)
                    for triple in source.triples((neighbour, None, None)):
                        border_graph.add(triple)
        return True
    return False
```

**The border grows dynamically.** When a node `N` is expanded, its triples are
moved from `source` to `interior`. Each neighbour of `N` in those triples (that is
not frozen or well-known and has not been queued yet) becomes a **new border
candidate** — it is appended to the deque and its triples are copied into
`border_graph` as context. So the environment's border grows in waves: in phase 1
it holds only the seed's direct neighbours (distance 1); after the first expansion
step, nodes at distance 2 appear; after the next, distance 3, and so on.

The expansion order is BFS from the seed: nodes added in phase 1 (the seed's
direct neighbours) are at the front of the queue, nodes discovered during
expansion go to the back. This natural BFS order ensures contextually closer nodes
enter the interior before more distant ones.

A node already queued (`border_queued`) is never added twice — this prevents
duplicates in the deque when the same node is a neighbour of several expanded nodes.

##### Border rendering after phase 2

`MergeEnvironment._render_border` automatically skips nodes already present in the interior:

```python
interior_subjects = {s for s, _, _ in interior if isinstance(s, URIRef)}
subjects = sorted(
    {s for s, _, _ in border_graph if isinstance(s, URIRef)} - interior_subjects,
    key=str,
)
```

So a node that moved from the border into `onto_1` appears in the `[Ontology_1]`
section (with full triples) — and is not duplicated in `[Border_1]`.

**Phase 2 result:** environments are modified in-place; `source_1`/`source_2` are
further consumed — what remains after both phases is the final leftovers (entities
without any alignment, not considered as a neighbour of any seed).

---

### 7. Serialization to KG2Code (`merge_environment.py` → `to_string`)

Each `MergeEnvironment` is serialized to the KG2Code format. **Every URIRef in
every triple position** — subject, predicate, object — is encoded as
`code:LocalName`:

```python
Entity('aa:Person', tuples=[
    ('aa:Person', 'ah:subClassOf', 'ab:Animal'),
    ('aa:Person', 'ae:type', 'ah:Class'),
])
```

This makes every triple element fully decodable: `code_to_ns["ah"] + "subClassOf"`
→ `http://www.w3.org/2002/07/owl#subClassOf`. Literals (strings, numbers) are
written without encoding. Border nodes are encoded too. Alignments are appended as
a separate section:

```
[Ontology_1]:
Entity('aa:Researcher', tuples=[('aa:Researcher', 'ah:subClassOf', 'aa:Person'), ...])
...
[Border_1]:
aa:Animal, ab:Organization

[Ontology_2]:
Entity('ab:Author', tuples=[...])
...
[Border_2]:
aa:Person

[Alignment]:
Researcher ↔ Researcher (relation: =)
```

`to_string()` returns `(prompt: str, code_to_ns: dict)`. The dictionary is needed
to decode the LLM's response.

---

### 8. Merging by the LLM (`merge_environments/module.py` + `agent.py`)

Environments are sent to the LLM **in parallel** via `asyncio.gather`, bounded by
a semaphore (`parallel_llm_request_count`).

The agent receives the KG2Code prompt and an instruction requiring it to:
- honour the alignments (mandatory merges)
- preserve relations to all nodes in Border_1 and Border_2
- remove redundant entities (e.g. two names for the same concept)
- fix domain inconsistencies (e.g. remove wrong is-a relations)
- introduce new cross-ontology relations where domain-sensible
- minimize orphan classes (classes without a superclass)

The LLM responds in JSON (`MergedOntology.model_json_schema()`):
```json
{
  "Merged_Ontology": [
    {"uri": "aa:Researcher", "tuples": [["aa:Researcher", "ah:subClassOf", "aa:Person"], ...]}
  ]
}
```

An entity has only `uri` (in `code:LocalName` form) and `tuples` — there is no
separate `name` field, because the name is embedded in the `uri`. The LLM may use
`zz:NewName` for entirely new concepts.

`entities_to_graph(entities, code_to_ns)` decodes each element via `_decode(coded, code_to_ns)`:
- `"aa:Researcher"` → `URIRef("http://cmt#Researcher")`
- `"ah:subClassOf"` → `URIRef("http://www.w3.org/2002/07/owl#subClassOf")`
- `"zz:NewConcept"` → `URIRef("http://merged#NewConcept")`
- `"some string"` (no code) → `Literal("some string")`

Triples whose predicate is not a URIRef are skipped.

> **Robustness:** if the LLM call raises (timeout, malformed JSON), the environment
> falls back to a deterministic merge (`_fallback_merge`) and logs a `WARNING`, so a
> single bad environment never crashes the run. See [backends.md](backends.md) for
> the request timeout that keeps slow reasoning models from always hitting this path.

---

### 9. Debug output (`debug/`)

When `DEBUG=true`, after merging, HTML visualizations (`pyvis`) are generated:

| File | Contents |
|------|----------|
| `debug_pre_merge.html` | All environments before merging + leftovers (onto_1 and onto_2) — colors: blue (onto_1), orange (onto_2), green (border), red (alignment seed) |
| `debug_merge_env_N.html` | A single environment N before merging; pink edges = triples that will disappear after merge |
| `debug_post_merge.html` | All merged environments + leftovers in one view |
| `debug_merged_env_N.html` | Merged environment N; pink edges = triples added by the LLM |
| `onto_1_leftover.html` | Graph visualization of onto_1 leftover |
| `onto_2_leftover.html` | Graph visualization of onto_2 leftover |
| `env_diff_N.txt` | Text diff for environment N: which triples the LLM removed, which it added |

---

### 10. Integration (`integrate_environments.py`)

All merged subgraphs (`merged_environments`) plus `onto_1_leftover` and
`onto_2_leftover` are combined into one `rdflib.Graph` by a union of triples.

---

### 11. Saving the result (`ontology/graph.py` → `save_ontology`)

The final graph is serialized to RDF/XML and saved as `merged_ontology.owl` in the
output directory.

---

## Output files

```
<output>/
  merged_ontology.owl       — the resulting ontology
  applied_alignments.owl    — baseline: naive union with alignments (for comparison)
  debug_pre_merge.html      — (DEBUG=true) pre-merge visualization
  debug_post_merge.html     — (DEBUG=true) post-merge visualization
  debug_merge_env_N.html    — (DEBUG=true) environment N pre-merge
  debug_merged_env_N.html   — (DEBUG=true) environment N post-merge
  onto_1_leftover.html      — (DEBUG=true) unaligned entities from onto_1
  onto_2_leftover.html      — (DEBUG=true) unaligned entities from onto_2
  env_diff_N.txt            — (DEBUG=true) triple diff for environment N
```

See [outputs.md](outputs.md) for the full artifact map including the report step.

---

## Architecture

```
main.py
└── LLMOntologyMerger.merge()
    ├── create_ontology(onto_1)           # load + relabel
    ├── create_ontology(onto_2)
    ├── AlignmentModule.create_alignment() # AML → list[Alignment]
    ├── apply_alignments()                # baseline merge → applied_alignments.owl
    ├── build_namespace_codec()           # shared URI → code codec aa/ab/...
    ├── ExtractEnvironmentsModule.extract()          # phase 1
    │   └── _build_merge_environment() × N           # 1 env / alignment
    │       └── → MergeEnvironment (onto_1_sub, onto_2_sub, border, alignments)
    ├── ExtractEnvironmentsModule.expand_extracted() # phase 2
    │   └── _expand_one() × round-robin              # border → interior, BFS
    ├── MergeEnvironmentsModule.merge() × N  [parallel]
    │   ├── env.to_string()               # → KG2Code prompt
    │   ├── merge_agent.run()             # → LLM
    │   └── entities_to_graph()           # → rdflib.Graph
    ├── save_pre_merge_debug()            # (DEBUG) HTML visualizations
    ├── save_post_merge_debug()
    ├── save_diff_debug()
    ├── integrate_environments()          # union of all graphs + leftovers
    └── save_ontology()                   # → merged_ontology.owl
```
