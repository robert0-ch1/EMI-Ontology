"""
populate.py — Add A-Box individuals to the synth ontology.

This script reads the existing T-Box from electronic_music_instruments.owl,
adds the manufacturer and instrument individuals from
abox_candidates_verified.csv, and writes the result back to the same file.

The verified CSV is the result of an earlier pipeline:
  scrape_vse.py   -> Vintage Synth Explorer scrape (Source 1)
  check_dbpedia.py -> DBpedia SPARQL queries (Source 2)
followed by manual verification of synthesis types and corrections to
known DBpedia data errors (e.g. Yamaha DX7 synthesis_type, Oberheim
OB-X polyphony).

Output:
    electronic_music_instruments.owl  (overwritten — T-Box + A-Box)

Run:
    python3 populate.py
"""

import csv
import re
from pathlib import Path
from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef, XSD

# ---------------------------------------------------------------
# Configuration — paths relative to this script
# ---------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()

ONTO = Namespace("https://github.com/robert0-ch1/EMI-Ontology/electronic_music_instrument_ontology#")

OWL_FILE  = SCRIPT_DIR / "electronic_music_instruments.owl"
INPUT_CSV = SCRIPT_DIR / "abox_candidates_verified.csv"

# Manufacturer -> country lookup (using the country's local name; Country
# individuals are already declared in the ontology). Sourced from each
# manufacturer's Wikipedia article.
MANUFACTURER_COUNTRY = {
    "Roland":               "Japan",
    "Korg":                 "Japan",
    "Yamaha":               "Japan",
    "Casio":                "Japan",
    "Kawai":                "Japan",
    "Akai":                 "Japan",
    "Moog":                 "United_States",
    "ARP":                  "United_States",
    "Oberheim":             "United_States",
    "Sequential Circuits":  "United_States",
    "Alesis":               "United_States",
    "Ensoniq":              "United_States",
    "E-mu":                 "United_States",
    "Kurzweil":             "United_States",
    "Linn Electronics":     "United_States",
    "Rhodes":               "United_States",
    "Elka":                 "Italy",
    "Siel":                 "Italy",
    "Fairlight":            "Australia",
    "Elektron":             "Sweden",
    "Waldorf":              "Germany",
    "Quasimidi":            "Germany",
    "Formanta":             "Russia",
}

# Lookup tables: CSV values -> IRIs declared in the T-Box
TOP_CLASS = {
    "Synthesizer": ONTO.Synthesizer,
    "Sampler":     ONTO.Sampler,
    "DrumMachine": ONTO.DrumMachine,
}
SOUND_GEN = {
    "Analog":  ONTO.Analog,
    "Digital": ONTO.Digital,
    "Hybrid":  ONTO.Hybrid,
}
SYNTH_METHOD = {
    "Subtractive":        ONTO.Subtractive,
    "FM":                 ONTO.FM,
    "Sample-based":       ONTO.SampleBased,
    "Wavetable":          ONTO.Wavetable,
    "Vector":             ONTO.Vector,
    "Additive":           ONTO.Additive,
    "Physical modelling": ONTO.PhysicalModelling,
}


def slug(text):
    """Replace spaces and special characters with underscores."""
    s = re.sub(r"[^A-Za-z0-9_-]", "_", text.strip())
    return re.sub(r"_+", "_", s).strip("_")


# ---------------------------------------------------------------
# Step 1: Load the existing ontology (T-Box already in the .owl file)
# ---------------------------------------------------------------

g = Graph()
g.parse(OWL_FILE, format="xml")
print(f"Loaded ontology: {len(g)} triples from {OWL_FILE.name}")

# Re-bind namespaces for clean output
g.bind("",     ONTO)
g.bind("owl",  OWL)
g.bind("rdfs", RDFS)
g.bind("xsd",  XSD)

# ---------------------------------------------------------------
# Step 2: Read the verified A-Box CSV
# ---------------------------------------------------------------

with open(INPUT_CSV) as f:
    rows = list(csv.DictReader(f))
print(f"Loaded CSV: {len(rows)} entities from {INPUT_CSV.name}")

# ---------------------------------------------------------------
# Step 3: Create Manufacturer individuals (linked to existing countries)
# ---------------------------------------------------------------

manufacturers = sorted(set(r["manufacturer"].strip() for r in rows if r["manufacturer"].strip()))
for mfr in manufacturers:
    iri = ONTO[slug(mfr)]
    g.add((iri, RDF.type, ONTO.Manufacturer))
    g.add((iri, RDF.type, OWL.NamedIndividual))
    g.add((iri, RDFS.label, Literal(mfr, lang="en")))

    if mfr in MANUFACTURER_COUNTRY:
        country_iri = ONTO[MANUFACTURER_COUNTRY[mfr]]
        g.add((iri, ONTO.basedIn, country_iri))
    else:
        print(f"  ! No country mapping for: {mfr}")

print(f"Added {len(manufacturers)} Manufacturer individuals")

# ---------------------------------------------------------------
# Step 4: Create instrument individuals
# ---------------------------------------------------------------

created = 0
for r in rows:
    name = r["name"].strip()
    mfr  = r["manufacturer"].strip()
    top  = r["top_level_class"].strip()

    if not name or not mfr or top not in TOP_CLASS:
        print(f"  ! Skipping malformed row: {r}")
        continue

    iri = ONTO[slug(name)]

    # Top-level type
    g.add((iri, RDF.type, TOP_CLASS[top]))
    g.add((iri, RDF.type, OWL.NamedIndividual))
    g.add((iri, RDFS.label, Literal(name, lang="en")))
    g.add((iri, ONTO.hasModelName, Literal(name, datatype=XSD.string)))

    # Manufacturer (already created above)
    g.add((iri, ONTO.hasManufacturer, ONTO[slug(mfr)]))

    # Year — guard against malformed values
    year_raw = r["year"].strip()
    if year_raw:
        try:
            g.add((iri, ONTO.yearOfRelease, Literal(int(year_raw), datatype=XSD.integer)))
        except ValueError:
            print(f"  ! Skipping non-integer year for {name}: '{year_raw}'")

    # Sound generation
    sg = r["sound_generation"].strip()
    if sg in SOUND_GEN:
        g.add((iri, ONTO.hasSoundGeneration, SOUND_GEN[sg]))

    # Synthesis method
    sm = r["synthesis_type"].strip()
    if sm in SYNTH_METHOD:
        g.add((iri, ONTO.hasSynthesisMethod, SYNTH_METHOD[sm]))

    # Polyphony — only for Synthesizers (T-Box domain restriction)
    poly_raw = r["polyphony"].strip()
    if poly_raw and top == "Synthesizer":
        try:
            g.add((iri, ONTO.polyphony, Literal(int(poly_raw), datatype=XSD.integer)))
        except ValueError:
            print(f"  ! Skipping non-integer polyphony for {name}: '{poly_raw}'")

    # External references — store as string-valued annotation properties
    # (:dbpediaRef, :wikipediaRef). Using strings rather than URIs prevents
    # Protégé from treating the URLs as separate individuals.
    if r.get("dbpedia_iri", "").strip():
        g.add((iri, ONTO.dbpediaRef, Literal(r["dbpedia_iri"].strip(), datatype=XSD.anyURI)))
    if r.get("wiki_url", "").strip():
        g.add((iri, ONTO.wikipediaRef, Literal(r["wiki_url"].strip(), datatype=XSD.anyURI)))

    created += 1

print(f"Added {created} instrument individuals")

# ---------------------------------------------------------------
# Step 5: Write the populated ontology back to the same file
# ---------------------------------------------------------------

g.serialize(destination=str(OWL_FILE), format="xml")
print(f"\nWrote {len(g)} triples to {OWL_FILE.name}")
