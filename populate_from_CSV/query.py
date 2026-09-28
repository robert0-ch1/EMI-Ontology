"""
query.py — Query the curated electronic-music-instrument ontology.

Runs seven competency queries against the locally populated ontology, then
drops the user into an interactive prompt where any arbitrary SPARQL query
can be executed.

This script targets the curated A-Box at:
    electronic_music_instruments.owl

To query the SPARQL-derived A-Box instead, pass its path:
    python3 query.py path/to/electronic_music_instruments_from_sparql.owl

Notes
-----
- Loads the ontology with rdflib, then applies OWL-RL closure (`owlrl`)
  so queries can use inferred predicates (property chains, equivalent
  classes) without needing Protégé's reasoner.
- Uses SPARQL 1.1 features (GROUP BY, COUNT, BIND, FLOOR, FILTER NOT
  EXISTS via OPTIONAL+!BOUND), all standard in the SPARQL 1.1 specification.
"""

import sys
from pathlib import Path
from rdflib import Graph
from owlrl import DeductiveClosure, OWLRL_Semantics

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_OWL = SCRIPT_DIR / "electronic_music_instruments.owl"

# Standard prefixes prepended to every query.
PREFIXES = """
PREFIX :     <https://github.com/robert0-ch1/EMI-Ontology/electronic_music_instrument_ontology#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# ---------------------------------------------------------------
# Competency queries — seven queries covering different ontology
# features and SPARQL constructs.
# ---------------------------------------------------------------

QUERIES = [
    {
        "title": "Q1. Each manufacturer's synthesis methods (counts)",
        "description":
            "How synthesis approaches break down per manufacturer "
            "(hasManufacturer: functional; hasSynthesisMethod).",
        "sparql": """
            SELECT ?manufacturer ?method (COUNT(?synth) AS ?n) WHERE {
                ?synth :hasManufacturer ?manufacturer ;
                       :hasSynthesisMethod ?method .
            }
            GROUP BY ?manufacturer ?method
            ORDER BY ?manufacturer DESC(?n)
        """,
    },
    {
        "title": "Q2. Synthesizers contemporary with the Roland Juno-60",
        "description":
            "Synthesizers sharing a release year with the Juno-60 "
            "(contemporaryOf: symmetric, irreflexive — realised here in SPARQL).",
        "sparql": """
            SELECT ?synth ?year WHERE {
                :Roland_Juno-60 :yearOfRelease ?year .
                ?synth a :Synthesizer ;
                       :yearOfRelease ?year .
                FILTER (?synth != :Roland_Juno-60)
            }
            ORDER BY ?synth
        """,
    },
    {
        "title": "Q3. Count of instruments per sound generation paradigm",
        "description":
            "Analog/Digital/Hybrid split across the whole population "
            "(hasSoundGeneration: functional).",
        "sparql": """
            SELECT ?sound_gen (COUNT(?instrument) AS ?n) WHERE {
                ?instrument a :HardwareInstrument ;
                            :hasSoundGeneration ?sound_gen .
            }
            GROUP BY ?sound_gen
            ORDER BY DESC(?n)
        """,
    },
    {
        "title": "Q4. Synthesizers missing a synthesis method (audit)",
        "description":
            "Synthesizers with no hasSynthesisMethod asserted — useful for "
            "spotting gaps when comparing the two pipelines.",
        "sparql": """
            SELECT ?synth WHERE {
                ?synth a :Synthesizer .
                OPTIONAL { ?synth :hasSynthesisMethod ?method . }
                FILTER (!BOUND(?method))
            }
            ORDER BY ?synth
        """,
    },
    {
        "title": "Q5. Synthesis methods by decade",
        "description":
            "How synthesis methods shift across decades (Subtractive 70s, "
            "FM 80s, Sample-based 90s).",
        "sparql": """
            SELECT ?decade ?method (COUNT(?synth) AS ?n) WHERE {
                ?synth :yearOfRelease ?year ;
                       :hasSynthesisMethod ?method .
                BIND ((FLOOR(?year / 10) * 10) AS ?decade)
            }
            GROUP BY ?decade ?method
            ORDER BY ?decade DESC(?n)
        """,
    },
    {
        "title": "Q6. Instruments per decade",
        "description":
            "Population count per decade, with the decade computed from "
            "yearOfRelease (independent of the SWRL hasDecade rules).",
        "sparql": """
            SELECT ?decade (COUNT(?instrument) AS ?n) WHERE {
                ?instrument :yearOfRelease ?year .
                BIND ((FLOOR(?year / 10) * 10) AS ?decade)
            }
            GROUP BY ?decade
            ORDER BY ?decade
        """,
    },
    {
        "title": "Q7. Synthesis methods used by digital instruments",
        "description":
            "Which synthesis methods appear among Digital instruments "
            "(hasSoundGeneration value :Digital).",
        "sparql": """
            SELECT ?method (COUNT(?instrument) AS ?n) WHERE {
                ?instrument :hasSoundGeneration :Digital ;
                            :hasSynthesisMethod ?method .
            }
            GROUP BY ?method
            ORDER BY DESC(?n)
        """,
    },
]


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def shorten(value):
    """Display IRIs as short names; literals as themselves."""
    if value is None:
        return "—"
    s = str(value)
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    if s.startswith("http"):
        return s.rsplit("/", 1)[-1]
    return s


def run_query(graph, sparql, show_max=50):
    """Run a SPARQL query and print results as a simple text table."""
    full_query = PREFIXES + sparql
    try:
        results = list(graph.query(full_query))
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    if not results:
        print("  (no results)")
        return

    headers = [str(v) for v in results[0].labels]
    rows = [[shorten(cell) for cell in row] for row in results]

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    print("  " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  " + "-+-".join("-" * w for w in widths))

    for row in rows[:show_max]:
        print("  " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(row)))

    if len(rows) > show_max:
        print(f"  ... ({len(rows) - show_max} more rows)")
    print(f"  ({len(rows)} result{'s' if len(rows) != 1 else ''})")


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------

def main():
    owl_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OWL

    if not owl_path.exists():
        print(f"ERROR: OWL file not found: {owl_path}", file=sys.stderr)
        print("Usage: python3 query.py [PATH_TO_OWL_FILE]", file=sys.stderr)
        sys.exit(1)

    print(f"Loading ontology from: {owl_path}")
    g = Graph()
    g.parse(owl_path, format="xml")
    print(f"Loaded {len(g)} triples")

    # rdflib's SPARQL engine doesn't run a DL reasoner — so we use the
    # owlrl library to materialize the OWL-RL closure (property chains,
    # equivalent classes, etc.) before querying. This lets queries below
    # use inferred predicates without requiring Protégé.
    print("Applying OWL-RL reasoning...")
    DeductiveClosure(OWLRL_Semantics).expand(g)
    print(f"After reasoning: {len(g)} triples\n")

    # Run all pre-written queries
    print("=" * 70)
    print("COMPETENCY QUERIES")
    print("=" * 70)
    for q in QUERIES:
        print(f"\n{q['title']}")
        print(f"  {q['description']}")
        print()
        run_query(g, q["sparql"])

    # Interactive mode
    print("\n" + "=" * 70)
    print("INTERACTIVE MODE")
    print("=" * 70)
    print("Enter your own SPARQL queries. Standard prefixes are already loaded,")
    print("so you can use :ClassName / :propertyName directly.")
    print("Finish each query with a blank line. Type 'quit' or 'exit' to leave.\n")

    while True:
        try:
            print("SPARQL> ", end="", flush=True)
            lines = []
            while True:
                line = input()
                if not line:
                    break
                lines.append(line)
                print("        ", end="", flush=True)
            sparql = "\n".join(lines).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not sparql:
            continue
        if sparql.lower() in {"quit", "exit", "q"}:
            print("Goodbye.")
            break

        print()
        run_query(g, sparql)
        print()


if __name__ == "__main__":
    main()
