# Szczegółowy przepływ (workflow) i architektura

> Pełny opis wewnętrznego pipeline'u. Przegląd i szybki start: [README](../README.md). Co gdzie trafia: [outputs.md](outputs.md).

## Workflow — szczegółowy opis

Poniżej opisany jest kompletny przepływ danych od wejścia (dwa pliki `.owl`) do wyjścia (`merged_ontology.owl`).

### 1. Wczytanie argumentów (`load_arguments.py`)

Parsowane są argumenty CLI i walidowane ścieżki do plików wejściowych. Wynikiem jest `LoadedArguments` — Pydantic model przechowujący wszystkie parametry sesji.

---

### 2. Załadowanie ontologii (`ontology/graph.py` → `create_ontology`)

Każda ontologia jest wczytywana przez `rdflib` z pliku OWL/RDF do obiektu `Graph`. Następuje preprocessing:

- **Relabelowanie encji** — jeśli encja ma przypisany `rdfs:label`, jej lokalny fragment URI (część po `#` lub `/`) jest zastępowany wartością etykiety (spacje → `_`), po czym triplet `rdfs:label` jest usuwany. Cel: zamiast generycznych identyfikatorów jak `Class_42`, LLM widzi semantyczne nazwy jak `MedicalProcedure`. Encje, których docelowe URI jest już zajęte, są pomijane.

Po tym kroku oba grafy (`onto_1`, `onto_2`) zawierają wyłącznie semantycznie nazwane encje bez nadmiarowych etykiet.

---

### 3. Alignment (`alignment/aml_alignment.py`)

Wywoływane jest narzędzie **AgreementMakerLight (AML)** jako proces Java. AML analizuje obie ontologie i produkuje plik EDOAL (XML) z listą par encji, które uznaje za powiązane.

Każdy alignment ma postać:
```
Alignment(entity1=URI, entity2=URI, measure=0.0–1.0, relation="="|"<"|">"|...)
```

- `entity1` — encja z onto_1
- `entity2` — odpowiadająca encja z onto_2
- `measure` — siła dopasowania (0 = brak podobieństwa, 1 = identyczne)
- `relation` — typ relacji (`=` znaczy tożsamość konceptualna, `<`/`>` subklasa)

Wynikiem jest lista `list[Alignment]` posortowana później malejąco po `measure`.

---

### 4. Naiwny merge (baseline) (`ontology/merge.py` → `apply_alignments`)

Tworzona jest prosta unia obu grafów, gdzie dla każdego alignmentu `entity2` jest "złożone" w `entity1` — wszystkie triplety `entity2` są przepisywane na `entity1`. Wynik zapisywany jest jako `applied_alignments.owl` w katalogu wyjściowym.

**Po co:** To nie jest wynikowy merge. To punkt odniesienia — baseline, który można porównać z wynikiem LLM, żeby ocenić jakość scalania.

---

### 5. Budowanie namespace codec (`merge_environment.py` → `build_namespace_codec`)

Namespace'y zbierane są ze **wszystkich pozycji** w tripletach obu ontologii (subject, predicate, object). Następnie dokładane są well-known NS (`owl`, `rdf`, `rdfs`, `xsd`, `swrl`, `protege`, ...) — tylko te, których nie ma już w danych. Każdemu unikalnemu namespace'owi przypisywany jest krótki kod leksykograficzny (`aa, ab, ac, ..., az, ba, bb, ...`):

```
http://cmt#                              →  aa
http://ekaw#                             →  ab
http://www.w3.org/1999/02/22-rdf-syntax-ns#  →  ae
http://www.w3.org/2002/07/owl#           →  ah
...
zz  →  http://merged#   ← zarezerwowany dla encji tworzonych przez LLM
```

Kod `zz` jest zawsze zarezerwowany i pomijany w sekwencji — służy jako namespace dla zupełnie nowych encji, które LLM może wprowadzić podczas scalania.

Zwracane struktury:
- `uri_to_code` — pełne URI podmiotu → kod (dla `graph_to_string`)
- `code_to_ns` — kod → prefix NS (do dekodowania odpowiedzi LLM)
- `ns_to_code` — prefix NS → kod (do sprawdzania well-known przez kod zamiast string-prefix)
- `well_known_codes` — frozenset kodów well-known NS

Codec jest budowany **raz** wspólnie dla obu ontologii przed ekstrakcją i przekazywany w dół przez cały pipeline.

---

### 6. Ekstrakcja środowisk scalania (`extract_environments/module.py`)

Ekstrakcja przebiega w **dwóch fazach**. Faza 1 (`extract`) tworzy szkielet — po jednym środowisku na alignment, z seed-węzłami w środku i bezpośrednimi sąsiadami w borderze. Faza 2 (`expand_extracted`) iteracyjnie wciąga border do wnętrza środowisk, aż zabraknie miejsca lub węzłów do ekspansji.

---

#### Faza 1 — `ExtractEnvironmentsModule.extract`

##### 6a. Robocze kopie grafów

```python
source_1 = Graph()
source_2 = Graph()
for triple in onto_1:
    source_1.add(triple)
for triple in onto_2:
    source_2.add(triple)
```

Oba grafy są kopiowane do roboczych kopii. Triplety seed-węzłów są **przenoszone** (usuwane z source) przy ekstrakcji. Po przetworzeniu wszystkich alignmentów to co pozostanie w `source_1`/`source_2` to **leftovers** — encje bez dopasowania, pass-through do wyniku.

##### 6b. Pula alignmentów (`_AlignmentPool`)

```python
pool = _AlignmentPool(alignments)
# _sorted — lista posortowana rosnąco po measure; pop() z końca = O(1) najwyższy
```

`pop()` zawsze zwraca alignment o **najwyższym** `measure` (najlepsze dopasowania pierwsze).

##### 6c. Budowanie środowiska (`_build_merge_environment`)

Dla każdego alignmentu jedno środowisko:

**1. Seed — przeniesienie bezpośrednich trójek**

```python
seed1 = URIRef(seed_al.entity1)   # strona onto_1
seed2 = URIRef(seed_al.entity2)   # strona onto_2

triples = move_entity_triples(seed1, source_1, sub1)
```

`move_entity_triples` przenosi **wszystkie** triplety, w których seed jest podmiotem **lub** obiektem — więcej kontekstu niż same outgoing edges. Po przeniesieniu triplety nie istnieją już w `source_1`.

**2. Klasyfikacja sąsiadów → border**

```python
for s, _, o in triples:
    for neighbor in (s, o):
        if isinstance(neighbor, URIRef) and neighbor not in seeds and not is_wk(neighbor):
            border_set.add(neighbor)
```

Każdy sąsiad (URIRef, nie-well-known, nieistniejący już w seeds) trafia do `border_set`. Nie ma wyjątków — nawet jeśli sąsiad ma alignment w puli, zostaje w borderze. Jego alignment zostanie pobrany jako seed **własnego** środowiska w kolejnej iteracji.

| Przypadek | Akcja |
|-----------|-------|
| Well-known NS (`owl:`, `rdf:`, `xsd:`, ...) | pomijany — LLM zna te słowniki |
| Już w seeds | pomijany |
| Każdy inny URIRef | → `border` |

**3. Kopiowanie trójek border-węzłów**

```python
for node in border_set1:
    for triple in source_1.triples((node, None, None)):
        border1_graph.add(triple)   # KOPIA, source pozostaje niezmieniony
```

Trójki border-węzłów są **kopiowane** (nie przenoszone) — ten sam węzeł może pojawiać się w borderze wielu środowisk i za każdym razem dostarczać pełen kontekst. Trójki nigdy nie są konsumowane z source przez samą przynależność do granicy.

> **Uwaga:** trójki bezpośrednio łączące border-węzeł z seedem (np. `(border_node, prop, seed1)`) zostały już przeniesione przez `move_entity_triples(seed1, ...)` i **nie pojawią się** w `border1_graph`. Jest to zachowanie poprawne — te relacje są widoczne w `onto_1` po stronie seeda.

**Wynik fazy 1:** `(environments: list[MergeEnvironment], onto_1_leftover: Graph, onto_2_leftover: Graph)`

- `environments` — lista środowisk, każde z: `onto_1` (trójki seed1), `onto_2` (trójki seed2), `border1_graph`, `border2_graph`, `alignments: [seed_al]`
- `onto_1_leftover`, `onto_2_leftover` — pozostałości source po ekstrakcji: encje bez żadnego alignmentu, pass-through do wyniku bez zmian

---

#### Faza 2 — `ExtractEnvironmentsModule.expand_extracted`

Po fazie 1 każde środowisko ma seed w środku i border na granicy. Faza 2 iteracyjnie wciąga węzły z bordera do wnętrza (`onto_1`, `onto_2`), stopniowo poszerzając kontekst dostępny dla LLM.

##### Globalne zamrożenie (`global_frozen`)

```python
global_frozen: set[URIRef] = {
    s
    for env in environments
    for graph in (env.onto_1, env.onto_2)
    for s, _, _ in graph
    if isinstance(s, URIRef)
}
```

Na początku fazy 2 zbiór `global_frozen` zawiera wszystkie seed-węzły ze wszystkich środowisk. Węzeł raz dodany do wnętrza jakiegoś środowiska jest zamrożony globalnie — nie może trafić do wnętrza innego środowiska. Może nadal figurować w `border_graph` innych środowisk jako kontekst, ale nie zostanie stamtąd przeniesiony.

##### Pętla round-robin

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

W każdej rundzie każde aktywne środowisko dostaje **jeden krok ekspansji z onto_1 i jeden z onto_2** (łącznie ≤ 2 węzły na środowisko na rundę). Dzięki round-robin węzły nie są monopolizowane przez pierwsze środowisko — każdy alignment dostaje szansę na rozrost.

Środowisko jest usuwane z rotacji gdy:
- `env.interior_char_estimate() >= max_chars` — wnętrze przekroczyło limit rozmiaru, lub
- brak dalszych węzłów w `border1` i `border2` — wszystkie zostały wciągnięte lub zamrożone.

Pętla kończy się gdy `active` jest puste lub w całej rundzie nie udało się nic expandować (wszystkie bordersy wyczerpane / zamrożone).

##### Krok ekspansji — `_expand_one`

```python
def _expand_one(border, border_queued, border_graph, interior, source, global_frozen, is_wk):
    while border:
        node = border.popleft()
        if node in global_frozen or is_wk(node):
            continue          # wyrzuć — zamrożony lub well-known, permanentnie

        triples = move_entity_triples(node, source, interior)
        global_frozen.add(node)

        # Usuń outgoing trójki węzła z border_graph — jest już we wnętrzu
        for triple in list(border_graph.triples((node, None, None))):
            border_graph.remove(triple)

        # Odkryj nowych sąsiadów i dodaj ich do bordera
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

**Border rośnie dynamicznie.** Gdy węzeł `N` jest expandowany, jego trójki są przenoszone z `source` do `interior`. Każdy sąsiad `N` w tych trójkach (który nie jest zamrożony ani well-known i nie był jeszcze zekolejkowany) staje się **nowym kandydatem do bordera** — trafia na koniec deque i jego trójki są kopiowane do `border_graph` jako kontekst. Oznacza to, że border środowiska rozrasta się falowo: w fazie 1 są w nim tylko bezpośredni sąsiedzi seeda (odległość 1), po pierwszym kroku ekspansji pojawiają się węzły na odległości 2, po kolejnym — odległości 3, itd.

Kolejność ekspansji to BFS od seeda: węzły dodane w fazie 1 (bezpośredni sąsiedzi seeda) są z przodu kolejki, węzły odkryte podczas ekspansji trafiają na koniec. Naturalna kolejność BFS zapewnia, że bliższe kontekstowo węzły wchodzą do wnętrza przed dalszymi.

Węzeł już zekolejkowany (`border_queued`) nigdy nie jest dodawany dwukrotnie — to zapobiega duplikatom w deque gdy ten sam węzeł jest sąsiadem wielu ekspandowanych węzłów.

##### Renderowanie bordera po fazie 2

`MergeEnvironment._render_border` automatycznie pomija węzły już obecne we wnętrzu:

```python
interior_subjects = {s for s, _, _ in interior if isinstance(s, URIRef)}
subjects = sorted(
    {s for s, _, _ in border_graph if isinstance(s, URIRef)} - interior_subjects,
    key=str,
)
```

Dzięki temu węzeł, który przeszedł z bordera do `onto_1`, pojawi się w sekcji `[Ontology_1]` (z pełnymi trójkami) — a nie zduplikuje się w `[Border_1]`.

**Wynik fazy 2:** środowiska są zmodyfikowane in-place; `source_1`/`source_2` są dalej konsumowane — to co z nich pozostanie po obu fazach to ostateczne leftovers (encje bez żadnego alignmentu i nierozważone jako sąsiedzi żadnego seeda).

---

### 7. Serializacja do KG2Code (`merge_environment.py` → `to_string`)

Każde `MergeEnvironment` jest serializowane do formatu KG2Code. **Każdy URIRef w każdej pozycji tripletu** — subject, predicate, object — jest zakodowany jako `code:LocalName`:

```python
Entity('aa:Person', tuples=[
    ('aa:Person', 'ah:subClassOf', 'ab:Animal'),
    ('aa:Person', 'ae:type', 'ah:Class'),
])
```

Dzięki temu każdy element tripletu jest w pełni dekodowalny: `code_to_ns["ah"] + "subClassOf"` → `http://www.w3.org/2002/07/owl#subClassOf`. Literały (stringi, liczby) zapisywane są bez kodowania. Węzły graniczne też są kodowane. Alignmenty doklejane są jako osobna sekcja:

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

[Alignments]:
Researcher ↔ Researcher (relation: =)
```

`to_string()` zwraca `(prompt: str, code_to_ns: dict)`. Słownik jest potrzebny do dekodowania odpowiedzi LLM.

---

### 8. Scalanie przez LLM (`merge_environments/module.py` + `agent.py`)

Środowiska są wysyłane **równolegle** do LLM przez `asyncio.gather`, z ograniczeniem przez semafor (`parallel_llm_request_count`).

Agent Ollama dostaje prompt z KG2Code i instrukcję, która nakazuje mu:
- dotrzymać alignmentów (obowiązkowe scalenia)
- zachować relacje do wszystkich węzłów z Border_1 i Border_2
- usunąć redundantne encje (np. dwie nazwy tego samego konceptu)
- naprawić niespójności domenowe (np. usunąć błędne relacje is-a)
- wprowadzić nowe relacje cross-ontology tam gdzie ma to sens domenowy
- zminimalizować orphan classes (klasy bez superklasy)

LLM odpowiada w formacie JSON (`MergedOntology.model_json_schema()`):
```json
{
  "Merged_Ontology": [
    {"uri": "aa:Researcher", "tuples": [["aa:Researcher", "ah:subClassOf", "aa:Person"], ...]}
  ]
}
```

Encja ma tylko `uri` (w formacie `code:LocalName`) i `tuples` — nie ma osobnego pola `name`, bo nazwa jest już osadzona w `uri`. LLM może użyć `zz:NowaNazwa` dla zupełnie nowych konceptów.

`entities_to_graph(entities, code_to_ns)` dekoduje każdy element przez `_decode(coded, code_to_ns)`:
- `"aa:Researcher"` → `URIRef("http://cmt#Researcher")`
- `"ah:subClassOf"` → `URIRef("http://www.w3.org/2002/07/owl#subClassOf")`
- `"zz:NewConcept"` → `URIRef("http://merged#NewConcept")`
- `"some string"` (brak kodu) → `Literal("some string")`

Triplety z predykatem nie będącym URIRef są pomijane.

---

### 9. Debug output (`debug/`)

Gdy `DEBUG=true`, po zakończeniu mergowania generowane są pliki HTML z wizualizacjami (`pyvis`):

| Plik | Zawartość |
|------|-----------|
| `debug_pre_merge.html` | Wszystkie środowiska przed scalaniem + leftovers (onto_1 i onto_2) — kolory: niebieski (onto_1), pomarańczowy (onto_2), zielony (granica), czerwony (seed alignmentu) |
| `debug_merge_env_N.html` | Pojedyncze środowisko N przed scalaniem; różowe krawędzie = triplety które znikną po merge |
| `debug_post_merge.html` | Wszystkie scalone środowiska + leftovers w jednym widoku |
| `debug_merged_env_N.html` | Scalone środowisko N; różowe krawędzie = triplety dodane przez LLM |
| `onto_1_leftover.html` | Grafowa wizualizacja onto_1 leftover |
| `onto_2_leftover.html` | Grafowa wizualizacja onto_2 leftover |
| `env_diff_N.txt` | Tekstowy diff dla środowiska N: które triplety LLM usunął, które dodał |

---

### 10. Integracja (`integrate_environments.py`)

Wszystkie scalone podgrafy (`merged_environments`) plus `onto_1_leftover` i `onto_2_leftover` są łączone w jeden `rdflib.Graph` przez unię tripletów.

---

### 11. Zapis wyniku (`ontology/graph.py` → `save_ontology`)

Końcowy graf jest serializowany do formatu RDF/XML i zapisywany jako `merged_ontology.owl` w katalogu wyjściowym.

---

## Pliki wyjściowe

```
<output>/
  merged_ontology.owl       — wynikowa ontologia
  applied_alignments.owl    — baseline: naiwna unia z alignmentami (do porównania)
  debug_pre_merge.html      — (DEBUG=true) wizualizacja przed scalaniem
  debug_post_merge.html     — (DEBUG=true) wizualizacja po scalaniu
  debug_merge_env_N.html    — (DEBUG=true) środowisko N pre-merge
  debug_merged_env_N.html   — (DEBUG=true) środowisko N post-merge
  onto_1_leftover.html      — (DEBUG=true) encje bez alignmentu z onto_1
  onto_2_leftover.html      — (DEBUG=true) encje bez alignmentu z onto_2
  env_diff_N.txt            — (DEBUG=true) diff tripletów dla środowiska N
```

---

## Architektura

```
main.py
└── LLMOntologyMerger.merge()
    ├── create_ontology(onto_1)           # wczytaj + relabeluj
    ├── create_ontology(onto_2)
    ├── AlignmentModule.create_alignment() # AML → lista Alignment
    ├── apply_alignments()                # baseline merge → applied_alignments.owl
    ├── build_namespace_codec()           # wspólny codec URI → kody aa/ab/...
    ├── ExtractEnvironmentsModule.extract()          # faza 1
    │   └── _build_merge_environment() × N           # 1 env / alignment
    │       └── → MergeEnvironment (onto_1_sub, onto_2_sub, border, alignments)
    ├── ExtractEnvironmentsModule.expand_extracted() # faza 2
    │   └── _expand_one() × round-robin              # border → interior, BFS
    ├── MergeEnvironmentsModule.merge() × N  [równolegle]
    │   ├── env.to_string()               # → KG2Code prompt
    │   ├── merge_agent.run()             # → Ollama LLM
    │   └── entities_to_graph()           # → rdflib.Graph
    ├── save_pre_merge_debug()            # (DEBUG) HTML wizualizacje
    ├── save_post_merge_debug()
    ├── save_diff_debug()
    ├── integrate_environments()          # unia wszystkich grafów + leftovers
    └── save_ontology()                   # → merged_ontology.owl
```

