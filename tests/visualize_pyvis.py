"""Visualize MergeEnvironment as an interactive HTML graph using pyvis.

Requires:
    uv add pyvis

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JAK CZYTAĆ WYNIKI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Co to jest MergeEnvironment?
─────────────────────────────
Mergowanie dwóch ontologii naraz byłoby za duże dla LLM. Zamiast tego:
1. Każdy alignment (para zmapowanych klas, np. „Reviewer" ↔ „Reviewer")
   staje się ziarnem (seed) środowiska.
2. Wokół ziarna BFS-em zbierane są sąsiednie trójki RDF z obu ontologii —
   lokalny kontekst wystarczający, żeby LLM zdecydował jak je scalić.
3. Zbiór tych lokalnych podgrafów + alignmentów = jeden MergeEnvironment.

env_0.html, env_1.html, env_2.html …
──────────────────────────────────────
Każdy plik to oddzielne środowisko. Kolejność = malejąca pewność alignmentu
ziarna: env_0 ma seed z najwyższą miarą podobieństwa, env_1 nieco niższą itd.
Środowiska są rozłączne — trójka raz wyciągnięta do env_0 nie pojawi się
w env_1 (graf źródłowy jest modyfikowany in-place podczas ekstrakcji).

Węzły (kółka/pudełka)
──────────────────────
  NIEBIESKI   (#aec6e8)  — klasa / instancja z ONTOLOGII 1
  POMARAŃCZOWY(#f5c98a)  — klasa / instancja z ONTOLOGII 2
  ZIELONY     (#2a9d2a)  — węzeł UCZESTNICZY W ALIGNMENCIE
                           (to właśnie ten węzeł LLM ma scalić z parą)
  CZERWONY    (#cc3333)  — węzeł na GRANICY (border): należy do środowiska,
                           ale jego sąsiedzi nie zostali jeszcze rozwinięci
                           (albo przekroczono limit znaków max_chars)

  Hover nad węzłem → pełne URI w tooltipie.
  Etykieta węzła   → lokalna nazwa (fragment po # lub ostatni segment /).

Krawędzie
──────────
  SZARA linia ciągła  — trójka RDF wewnątrz ontologii (predykat jako etykieta,
                        np. subClassOf, domain, range …)
  ZIELONA linia przerywana — alignment między klasą z onto_1 a klasą z onto_2;
                             etykieta = miara podobieństwa (0–1, wyżej = pewniej)

Interakcja w przeglądarce
──────────────────────────
  Przeciągnij węzeł     — ręczne pozycjonowanie
  Scroll / pinch        — zoom
  Kliknij + przeciągnij tło — przesunięcie widoku
  Hover nad węzłem / krawędzią — tooltip z pełnym URI lub miarą alignmentu

Co szukać?
──────────
  • Para zielonych węzłów połączonych przerywaną zieloną krawędzią to rdzeń
    środowiska — właśnie te dwa pojęcia LLM ma zdecydować jak scalić.
  • Czerwone węzły pokazują, jak szeroko sięga lokalny kontekst; jeśli jest
    ich dużo, środowisko zostało przycięte przez max_chars.
  • Struktury po lewej (niebieskej) vs po prawej (pomarańczowej) powinny być
    podobne dla dobrych alignmentów — skraj inaczej wyglądające poddrzewo
    sugeruje potencjalnie błędny alignment.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from pathlib import Path

from pyvis.network import Network
from rdflib import Graph, URIRef

from llm_onto_merger.alignment.aml_alignment import AmlAlignmentModule
from llm_onto_merger.extract_environments import (
    ExtractEnvironmentsModule,
    MergeEnvironment,
    MergeEnvironmentConfig,
)
from llm_onto_merger.ontology import local_name

_HERE = Path(__file__).parent

_ONTO1_COLOR = "#aec6e8"
_ONTO2_COLOR = "#f5c98a"
_ALIGN_COLOR = "#2a9d2a"
_BORDER_COLOR = "#cc3333"


def _local_name(uri: URIRef | str) -> str:
    return local_name(uri)


def _make_net() -> Network:
    net = Network(
        height="800px",
        width="100%",
        directed=True,
        notebook=False,
        bgcolor="#ffffff",
        font_color="#222222",
    )
    net.barnes_hut(gravity=-5000, central_gravity=0.3, spring_length=120)
    return net


def _add_graph_nodes(net: Network, onto: Graph, color: str) -> None:
    nodes = {str(s) for s, _, _ in onto if isinstance(s, URIRef)} | {
        str(o) for _, _, o in onto if isinstance(o, URIRef)
    }
    for n in nodes:
        net.add_node(n, label=_local_name(n), color=color, title=n)


def _add_graph_edges(net: Network, onto: Graph) -> None:
    for s, p, o in onto:
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            net.add_edge(
                str(s),
                str(o),
                label=_local_name(p),
                title=str(p),
                color="#888888",
                arrows="to",
            )


def visualize_graph(
    onto_1: Graph,
    onto_2: Graph,
    output_path: str,
) -> str:
    """Render two plain RDF graphs side by side (no alignment info)."""
    net = _make_net()
    _add_graph_nodes(net, onto_1, _ONTO1_COLOR)
    _add_graph_nodes(net, onto_2, _ONTO2_COLOR)
    _add_graph_edges(net, onto_1)
    _add_graph_edges(net, onto_2)
    net.save_graph(output_path)
    print(f"Saved: {output_path}")
    return output_path


def visualize_merge_environment(
    env: MergeEnvironment,
    output_path: str = "merge_env.html",
) -> str:
    """Render *env* to an interactive HTML file and return the output path."""
    net = _make_net()

    border1_uris = {str(u) for u in env.border1}
    border2_uris = {str(u) for u in env.border2}
    aligned_uris = {a.entity1 for a in env.alignments} | {
        a.entity2 for a in env.alignments
    }

    def _add_onto_nodes(onto: Graph, base_color: str, border_uris: set[str]) -> None:
        nodes = {str(s) for s, _, _ in onto if isinstance(s, URIRef)} | {
            str(o) for _, _, o in onto if isinstance(o, URIRef)
        }
        for n in nodes:
            if n in aligned_uris:
                color = _ALIGN_COLOR
                border_width = 3
            elif n in border_uris:
                color = _BORDER_COLOR
                border_width = 3
            else:
                color = base_color
                border_width = 1
            net.add_node(
                n,
                label=_local_name(n),
                color=color,
                borderWidth=border_width,
                title=n,
            )

    _add_onto_nodes(env.onto_1, _ONTO1_COLOR, border1_uris)
    _add_onto_nodes(env.onto_2, _ONTO2_COLOR, border2_uris)
    _add_graph_edges(net, env.onto_1)
    _add_graph_edges(net, env.onto_2)

    for al in env.alignments:
        net.add_edge(
            al.entity1,
            al.entity2,
            label=f"{al.measure:.2f}",
            title=f"alignment: {al.measure:.4f}",
            color=_ALIGN_COLOR,
            dashes=True,
            width=2,
        )

    net.save_graph(output_path)
    print(f"Saved: {output_path}")
    return output_path


if __name__ == "__main__":
    onto_1 = Graph().parse(_HERE / "inputs/cmt.owl")
    onto_2 = Graph().parse(_HERE / "inputs/edas.owl")
    alignments = AmlAlignmentModule()._load_alignments(_HERE / "outputs/alignment.owl")

    # Pełne grafy przed ekstrakcją
    visualize_graph(onto_1, onto_2, str(_HERE / "outputs/full.html"))

    config = MergeEnvironmentConfig(max_chars=4000)
    envs, leftover_1, leftover_2 = ExtractEnvironmentsModule(config).extract(
        onto_1, onto_2, alignments
    )
    print(f"Extracted {len(envs)} environments")

    # Resztki — trójki niepokryte żadnym MergeEnvironment
    visualize_graph(leftover_1, leftover_2, str(_HERE / "outputs/leftover.html"))

    # Indywidualne środowiska
    for i, env in enumerate(envs):
        visualize_merge_environment(
            env,
            output_path=str(_HERE / f"outputs/env_{i}.html"),
        )
