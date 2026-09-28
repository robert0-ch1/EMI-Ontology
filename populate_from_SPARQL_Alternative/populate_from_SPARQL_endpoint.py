"""
populate_from_SPARQL_endpoint.py

Alternative populator that queries the DBpedia SPARQL endpoint for each
synth in the seed list, validates the returned values, and adds them
directly to the ontology. No intermediate CSV; the CSV is used only as
a seed list of names + DBpedia IRIs.

Sequential, polite-to-DBpedia version. Runs in ~30-45 minutes for
~377 synths.

Output: electronic_music_instruments_from_sparql.owl

Run:
    python3 populate_from_SPARQL_endpoint.py
"""

import csv
import re
import time
from pathlib import Path
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, XSD

SCRIPT_DIR = Path(__file__).parent.resolve()
ONTO = Namespace("https://github.com/robert0-ch1/EMI-Ontology/electronic_music_instrument_ontology#")

INPUT_CSV  = SCRIPT_DIR / "dbpedia_coverage.csv"
TBOX_OWL   = SCRIPT_DIR / "electronic_music_instruments.owl"
OUTPUT_OWL = SCRIPT_DIR / "electronic_music_instruments_from_sparql.owl"

DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"

MANUFACTURER_COUNTRY = {
    "Roland": "Japan", "Korg": "Japan", "Yamaha": "Japan",
    "Casio": "Japan", "Kawai": "Japan", "Akai": "Japan",
    "Moog": "United_States", "ARP": "United_States",
    "Oberheim": "United_States", "Sequential Circuits": "United_States",
    "Alesis": "United_States", "Ensoniq": "United_States",
    "E-mu": "United_States", "Kurzweil": "United_States",
    "Linn Electronics": "United_States", "Rhodes": "United_States",
    "Elka": "Italy", "Siel": "Italy", "Fairlight": "Australia",
    "Elektron": "Sweden", "Waldorf": "Germany",
    "Quasimidi": "Germany", "Formanta": "Russia",
}


def slug(text):
    s = re.sub(r"[^A-Za-z0-9_-]", "_", text.strip())
    return re.sub(r"_+", "_", s).strip("_")


# SPARQL query — slide-faithful: SELECT/WHERE/PREFIX/OPTIONAL/FILTER/REGEX
QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dbp:  <http://dbpedia.org/property/>
PREFIX dct:  <http://purl.org/dc/terms/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>

SELECT ?year ?polyphony ?synthesis_type ?wiki_url
       ?cat_analog ?cat_digital ?cat_drum ?cat_sampler
WHERE {
    <%s> rdfs:label ?label .
    FILTER (LANG(?label) = "en")
    OPTIONAL { <%s> dbp:dates ?year .
               FILTER REGEX(STR(?year), "^[0-9]{4}") }
    OPTIONAL { <%s> dbp:polyphony ?polyphony .
               FILTER REGEX(STR(?polyphony), "^[0-9]+$") }
    OPTIONAL { <%s> dbp:synthesisType ?synthesis_type . }
    OPTIONAL { <%s> foaf:isPrimaryTopicOf ?wiki_url . }
    OPTIONAL { <%s> dct:subject ?cat_analog .
               FILTER REGEX(STR(?cat_analog), "Analog_synthesizers") }
    OPTIONAL { <%s> dct:subject ?cat_digital .
               FILTER REGEX(STR(?cat_digital), "Digital_synthesizers") }
    OPTIONAL { <%s> dct:subject ?cat_drum .
               FILTER REGEX(STR(?cat_drum), "Drum_machines") }
    OPTIONAL { <%s> dct:subject ?cat_sampler .
               FILTER REGEX(STR(?cat_sampler), "Samplers_") }
}
LIMIT 1
"""


def query_dbpedia(iri):
    sparql = SPARQLWrapper(DBPEDIA_ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.setTimeout(15)
    sparql.setQuery(QUERY % ((iri,) * 9))
    try:
        results = sparql.query().convert()["results"]["bindings"]
        return results[0] if results else None
    except Exception as e:
        if "429" in str(e):
            time.sleep(10)   # back off if rate-limited
        return None


# --- Validation helpers ---

ALLOWED_SYNTH_TYPES = {
    "Subtractive": "Subtractive", "Subtractive synthesis": "Subtractive",
    "FM": "FM", "FM synthesis": "FM",
    "PCM": "Sample-based", "Sample-based": "Sample-based",
    "Sample-based synthesis": "Sample-based",
    "Wavetable": "Wavetable", "Wavetable synthesis": "Wavetable",
    "Vector": "Vector", "Vector synthesis": "Vector",
    "Additive": "Additive", "Additive synthesis": "Additive",
    "Physical modelling": "Physical modelling",
    "Physical modelling synthesis": "Physical modelling",
}


def get(r, k): return r.get(k, {}).get("value") if r else None


def parse_year(v):
    if not v: return None
    m = re.search(r"\b(\d{4})\b", v)
    return int(m.group(1)) if m and 1950 <= int(m.group(1)) <= 2030 else None


def parse_polyphony(v):
    if not v or v.startswith("http"): return None
    m = re.search(r"^(\d+)$", v.strip())
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 256 else None


def normalise_synthesis_type(v):
    if not v: return None
    v = v.strip()
    if v in ALLOWED_SYNTH_TYPES: return ALLOWED_SYNTH_TYPES[v]
    v_low = v.lower()
    for k, label in ALLOWED_SYNTH_TYPES.items():
        if k.lower() in v_low: return label
    return None


def classify_top_level(r):
    if get(r, "cat_drum"):    return "DrumMachine"
    if get(r, "cat_sampler"): return "Sampler"
    return "Synthesizer"


def classify_sound_generation(r, top_level):
    if top_level == "Sampler": return "Digital"
    has_analog  = bool(get(r, "cat_analog"))
    has_digital = bool(get(r, "cat_digital"))
    if has_analog and has_digital: return "Hybrid"
    if has_analog:  return "Analog"
    if has_digital: return "Digital"
    return None


# --- Load seeds (deduplicated by IRI) ---

all_rows = []
with open(INPUT_CSV) as f:
    for r in csv.DictReader(f):
        iri = r.get("dbpedia_iri", "").strip()
        if iri:
            all_rows.append((r.get("manufacturer", "").strip(),
                             r.get("name", "").strip(), iri))

seeds = []
seen = set()
for mfr, name, iri in all_rows:
    if iri not in seen:
        seen.add(iri)
        seeds.append((mfr, name, iri))

print(f"Total rows with IRIs: {len(all_rows)}")
print(f"After dedup:          {len(seeds)}")
print()

# --- Load T-Box ---

g = Graph()
g.parse(TBOX_OWL, format="xml")
print(f"Loaded T-Box: {len(g)} triples")
g.bind("",     ONTO)
g.bind("owl",  OWL)
g.bind("rdfs", RDFS)
g.bind("xsd",  XSD)

# --- Add Manufacturer individuals ---

seen_mfr = set()
for mfr, _name, _iri in seeds:
    if not mfr or mfr in seen_mfr: continue
    seen_mfr.add(mfr)
    m_iri = ONTO[slug(mfr)]
    g.add((m_iri, RDF.type, ONTO.Manufacturer))
    g.add((m_iri, RDF.type, OWL.NamedIndividual))
    g.add((m_iri, RDFS.label, Literal(mfr, lang="en")))
    if mfr in MANUFACTURER_COUNTRY:
        g.add((m_iri, ONTO.basedIn, ONTO[MANUFACTURER_COUNTRY[mfr]]))

print(f"Added {len(seen_mfr)} manufacturers")
print()

# --- Query DBpedia and build the A-Box (sequential) ---

TOP_CLASS_IRI = {
    "Synthesizer": ONTO.Synthesizer,
    "Sampler":     ONTO.Sampler,
    "DrumMachine": ONTO.DrumMachine,
}
SOUND_GEN_IRI = {"Analog": ONTO.Analog, "Digital": ONTO.Digital, "Hybrid": ONTO.Hybrid}
SYNTH_METHOD_IRI = {
    "Subtractive": ONTO.Subtractive, "FM": ONTO.FM,
    "Sample-based": ONTO.SampleBased, "Wavetable": ONTO.Wavetable,
    "Vector": ONTO.Vector, "Additive": ONTO.Additive,
    "Physical modelling": ONTO.PhysicalModelling,
}

added = skipped = 0
for i, (mfr, name, iri) in enumerate(seeds, 1):
    r = query_dbpedia(iri)
    if r is None:
        print(f"[{i:3}/{len(seeds)}] {name:40} → no data")
        skipped += 1
        continue

    top_level = classify_top_level(r)
    sound_gen = classify_sound_generation(r, top_level)
    year      = parse_year(get(r, "year"))
    poly      = parse_polyphony(get(r, "polyphony"))
    synth     = normalise_synthesis_type(get(r, "synthesis_type"))

    s_iri = ONTO[slug(name)]
    g.add((s_iri, RDF.type, TOP_CLASS_IRI[top_level]))
    g.add((s_iri, RDF.type, OWL.NamedIndividual))
    g.add((s_iri, RDFS.label, Literal(name, lang="en")))
    g.add((s_iri, ONTO.hasModelName, Literal(name, datatype=XSD.string)))
    if mfr:
        g.add((s_iri, ONTO.hasManufacturer, ONTO[slug(mfr)]))

    # Functional properties — add only if no existing value
    if year and not list(g.objects(s_iri, ONTO.yearOfRelease)):
        g.add((s_iri, ONTO.yearOfRelease, Literal(year, datatype=XSD.integer)))
    if sound_gen and not list(g.objects(s_iri, ONTO.hasSoundGeneration)):
        g.add((s_iri, ONTO.hasSoundGeneration, SOUND_GEN_IRI[sound_gen]))
    if poly and top_level == "Synthesizer" and not list(g.objects(s_iri, ONTO.polyphony)):
        g.add((s_iri, ONTO.polyphony, Literal(poly, datatype=XSD.integer)))
    if synth:
        g.add((s_iri, ONTO.hasSynthesisMethod, SYNTH_METHOD_IRI[synth]))

    g.add((s_iri, ONTO.dbpediaRef, Literal(iri, datatype=XSD.anyURI)))
    wiki = get(r, "wiki_url")
    if wiki:
        g.add((s_iri, ONTO.wikipediaRef, Literal(wiki, datatype=XSD.anyURI)))

    print(f"[{i:3}/{len(seeds)}] {name:40} → {top_level} | "
          f"{sound_gen or '—'} | year={year or '—'} | "
          f"poly={poly or '—'} | {synth or '—'}")
    added += 1

# --- Save ---

g.serialize(destination=str(OUTPUT_OWL), format="xml")
print()
print(f"Added:   {added}")
print(f"Skipped: {skipped}")
print(f"Wrote:   {len(g)} triples to {OUTPUT_OWL.name}")
