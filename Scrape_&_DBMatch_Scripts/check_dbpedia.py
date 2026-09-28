"""
DBpedia coverage check for VSE synths.
Pulls: existence, year, sound generation, top-level class,
synthesis type, polyphony, Wikipedia URL.
"""

import csv
import time
import re
import os
from SPARQLWrapper import SPARQLWrapper, JSON

INPUT_PATH = "data/vse_synths.csv"
OUTPUT_PATH = "data/dbpedia_coverage.csv"
DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"
DELAY = 0.05

TIMEOUT_FAST = 10
TIMEOUT_LABEL = 8

CATEGORY_DRUM_MACHINE = "<http://dbpedia.org/resource/Category:Drum_machines>"
CATEGORY_SAMPLER      = "<http://dbpedia.org/resource/Category:Samplers_(musical_instrument)>"
CATEGORY_VOCODER      = "<http://dbpedia.org/resource/Category:Vocoders>"
CATEGORY_SEQUENCER    = "<http://dbpedia.org/resource/Category:Music_sequencers>"
CATEGORY_ANALOG       = "<http://dbpedia.org/resource/Category:Analog_synthesizers>"
CATEGORY_DIGITAL      = "<http://dbpedia.org/resource/Category:Digital_synthesizers>"

WIKILINK_ANALOG_SIGNALS = {
    "Analog_synthesizer",
    "Voltage-controlled_oscillator",
    "Voltage-controlled_filter",
    "Voltage-controlled_amplifier",
}
WIKILINK_DIGITAL_SIGNALS = {
    "Digital_synthesizer",
    "Wavetable_synthesis",
    "FM_synthesis",
    "Frequency_modulation_synthesis",
    "Phase_distortion_synthesis",
    "Sample-based_synthesis",
}
WIKILINK_SYNTHTYPE_MAP = {
    "Subtractive_synthesis":    "Subtractive synthesis",
    "Additive_synthesis":       "Additive synthesis",
    "FM_synthesis":             "FM synthesis",
    "Frequency_modulation_synthesis": "FM synthesis",
    "Wavetable_synthesis":      "Wavetable synthesis",
    "Phase_distortion_synthesis": "Phase distortion synthesis",
    "Sample-based_synthesis":   "Sample-based synthesis",
    "Granular_synthesis":       "Granular synthesis",
    "Physical_modelling_synthesis": "Physical modelling synthesis",
}


def make_sparql(timeout=TIMEOUT_FAST):
    s = SPARQLWrapper(DBPEDIA_ENDPOINT)
    s.setReturnFormat(JSON)
    s.setTimeout(timeout)
    s.addCustomHttpHeader("User-Agent", "SynthOntology/1.0")
    return s


def slugify(text):
    return re.sub(r"\s+", "_", text.strip())


def candidate_slugs(manufacturer, name):
    candidates = []
    name_clean = name.strip()
    mfr_clean = manufacturer.strip()

    def strip_chars(s):
        return s.replace("'", "").replace("’", "").replace("/", "_")

    candidates.append(slugify(name_clean))
    candidates.append(slugify(strip_chars(name_clean)))
    candidates.append(slugify(re.sub(r"\s*\([^)]*\)", "", name_clean).strip()))
    if name_clean.lower().startswith(mfr_clean.lower()):
        model = name_clean[len(mfr_clean):].strip()
        if model:
            candidates.append(slugify(model))
            candidates.append(slugify(strip_chars(model)))
    candidates.append(f"{slugify(mfr_clean)}_{slugify(name_clean)}")
    candidates.append(slugify(name_clean.replace("-", " ")))
    candidates.append(name_clean.replace(" ", "_"))

    seen = set()
    return [c for c in candidates if c and not (c in seen or seen.add(c))]


def iri_exists(iri):
    s = make_sparql()
    s.setQuery(f"ASK WHERE {{ <{iri}> ?p ?o . }}")
    try:
        return s.query().convert().get("boolean", False)
    except Exception:
        return False


def resolve_redirect(iri):
    s = make_sparql()
    s.setQuery(f"SELECT ?t WHERE {{ <{iri}> dbo:wikiPageRedirects ?t }} LIMIT 1")
    try:
        r = s.query().convert()["results"]["bindings"]
        if r:
            return r[0]["t"]["value"]
    except Exception:
        pass
    return iri


def search_by_label(name, manufacturer):
    s = make_sparql(timeout=TIMEOUT_LABEL)
    safe_name = name.replace('"', '\\"')

    q = f"""
    SELECT ?entity WHERE {{
      ?entity rdfs:label "{safe_name}"@en .
      {{ ?entity dct:subject/skos:broader* <http://dbpedia.org/resource/Category:Synthesizers> }}
      UNION
      {{ ?entity dct:subject {CATEGORY_DRUM_MACHINE} }}
      UNION
      {{ ?entity dct:subject {CATEGORY_SAMPLER} }}
      UNION
      {{ ?entity dct:subject {CATEGORY_VOCODER} }}
      UNION
      {{ ?entity dct:subject {CATEGORY_SEQUENCER} }}
    }} LIMIT 1
    """
    s.setQuery(q)
    try:
        r = s.query().convert()["results"]["bindings"]
        if r:
            return r[0]["entity"]["value"]
    except Exception:
        pass

    s.setQuery(f"""
    SELECT ?entity WHERE {{
      ?entity rdfs:label "{safe_name}"@en .
      ?entity dbp:synthManufacturer ?mfr .
    }} LIMIT 1
    """)
    try:
        r = s.query().convert()["results"]["bindings"]
        if r:
            return r[0]["entity"]["value"]
    except Exception:
        pass

    return None


def find_iri(manufacturer, name):
    for slug in candidate_slugs(manufacturer, name):
        iri = f"http://dbpedia.org/resource/{slug}"
        if iri_exists(iri):
            return resolve_redirect(iri)
        time.sleep(DELAY)

    fallback = search_by_label(name, manufacturer)
    if fallback:
        return resolve_redirect(fallback)
    return None


def fetch_data(iri):
    """One batched SELECT: categories + values + wiki URL."""
    s = make_sparql()
    q = f"""
    SELECT
      (BOUND(?drum)      AS ?is_drum)
      (BOUND(?sampler)   AS ?is_sampler)
      (BOUND(?vocoder)   AS ?is_vocoder)
      (BOUND(?sequencer) AS ?is_sequencer)
      (BOUND(?analog)    AS ?is_analog)
      (BOUND(?digital)   AS ?is_digital)
      ?year ?synthesis_type ?polyphony ?wiki_url
    WHERE {{
      OPTIONAL {{ <{iri}> dct:subject {CATEGORY_DRUM_MACHINE} . BIND(1 AS ?drum) }}
      OPTIONAL {{ <{iri}> dct:subject {CATEGORY_SAMPLER} . BIND(1 AS ?sampler) }}
      OPTIONAL {{ <{iri}> dct:subject {CATEGORY_VOCODER} . BIND(1 AS ?vocoder) }}
      OPTIONAL {{ <{iri}> dct:subject {CATEGORY_SEQUENCER} . BIND(1 AS ?sequencer) }}
      OPTIONAL {{ <{iri}> dct:subject {CATEGORY_ANALOG} . BIND(1 AS ?analog) }}
      OPTIONAL {{ <{iri}> dct:subject {CATEGORY_DIGITAL} . BIND(1 AS ?digital) }}
      OPTIONAL {{ <{iri}> dbp:dates ?year . }}
      OPTIONAL {{ <{iri}> dbp:synthesisType ?synthesis_type . }}
      OPTIONAL {{ <{iri}> dbp:polyphony ?polyphony . }}
      OPTIONAL {{ <{iri}> foaf:isPrimaryTopicOf ?wiki_url . }}
    }} LIMIT 1
    """
    s.setQuery(q)
    try:
        r = s.query().convert()["results"]["bindings"]
        return r[0] if r else {}
    except Exception as e:
        print(f"    ! query error: {e}")
        return {}


def fetch_wiki_links(iri):
    """Fetch all dbo:wikiPageWikiLink slugs. Returns a set of slug strings."""
    s = make_sparql()
    s.setQuery(f"""
    SELECT ?link WHERE {{
      <{iri}> dbo:wikiPageWikiLink ?link .
    }}
    """)
    try:
        r = s.query().convert()["results"]["bindings"]
        return {row["link"]["value"].rsplit("/", 1)[-1] for row in r}
    except Exception:
        return set()


def truthy(data, key):
    v = data.get(key, {}).get("value")
    return v == "1" or v == "true"


def val(data, key):
    return data.get(key, {}).get("value", "")


def classify_top_level(data, name):
    """Categories first, then name heuristics. No wiki-link fallback (too noisy)."""
    if truthy(data, "is_drum"):      return "DrumMachine"
    if truthy(data, "is_sampler"):   return "Sampler"
    if truthy(data, "is_vocoder"):   return "Vocoder"
    if truthy(data, "is_sequencer"): return "Sequencer"

    n = name.lower()
    if "drum" in n or "rhythm" in n or re.search(r"\btr-?\d", n):
        return "DrumMachine"
    if "sampler" in n:    return "Sampler"
    if "vocoder" in n:    return "Vocoder"
    if "sequencer" in n:  return "Sequencer"
    return "Synthesizer"


def classify_sound_generation(data, top_class, synthesis_type, wiki_links=None):
    """Categories → synthesis_type text → wiki-link signals."""
    if top_class == "Sampler":
        return ""

    a = truthy(data, "is_analog")
    d = truthy(data, "is_digital")
    if a and d: return "Hybrid"
    if a:       return "Analog"
    if d:       return "Digital"

    s = synthesis_type.lower()
    if s:
        has_analog  = "analog" in s or "subtractive" in s
        has_digital = ("digital" in s or "fm" in s or "wavetable" in s
                       or "pcm" in s or "sample" in s or "additive" in s)
        if has_analog and has_digital: return "Hybrid"
        if has_analog:                  return "Analog"
        if has_digital:                 return "Digital"

    if wiki_links:
        has_analog  = bool(wiki_links & WIKILINK_ANALOG_SIGNALS)
        has_digital = bool(wiki_links & WIKILINK_DIGITAL_SIGNALS)
        if has_analog and has_digital: return "Hybrid"
        if has_analog:                  return "Analog"
        if has_digital:                 return "Digital"

    return ""


def clean_synthesis_type(raw):
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw.rsplit("/", 1)[-1].replace("_", " ")
    return raw


def infer_synthesis_type_from_links(wiki_links):
    if not wiki_links:
        return ""
    for link, label in WIKILINK_SYNTHTYPE_MAP.items():
        if link in wiki_links:
            return label
    return ""


def process_synth(manufacturer, name):
    row = {
        "manufacturer": manufacturer,
        "name": name,
        "exists_in_dbpedia": False,
        "dbpedia_iri": "",
        "wiki_url": "",
        "year": "",
        "sound_generation": "",
        "top_level_class": "",
        "synthesis_type": "",
        "polyphony": "",
    }

    iri = find_iri(manufacturer, name)
    if not iri:
        return row

    row["exists_in_dbpedia"] = True
    row["dbpedia_iri"] = iri

    data = fetch_data(iri)
    row["year"] = val(data, "year")
    row["polyphony"] = val(data, "polyphony")
    row["wiki_url"] = val(data, "wiki_url")
    row["synthesis_type"] = clean_synthesis_type(val(data, "synthesis_type"))

    top_class = classify_top_level(data, name)
    sound_gen = classify_sound_generation(data, top_class, row["synthesis_type"])

    # Wiki-link fallback only if needed for sound_generation or synthesis_type
    if not sound_gen or not row["synthesis_type"]:
        wiki_links = fetch_wiki_links(iri)
        sound_gen = classify_sound_generation(data, top_class, row["synthesis_type"], wiki_links)
        if not row["synthesis_type"]:
            row["synthesis_type"] = infer_synthesis_type_from_links(wiki_links)

    row["top_level_class"] = top_class
    row["sound_generation"] = sound_gen

    return row


def main():
    if not os.path.exists(INPUT_PATH):
        print(f"Input file {INPUT_PATH} not found.")
        return

    with open(INPUT_PATH, newline="", encoding="utf-8") as f:
        synths = list(csv.DictReader(f))

    # --- TESTING: uncomment to limit ---
    # synths = synths[:20]

    print(f"Read {len(synths)} synths from {INPUT_PATH}")
    print()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    fieldnames = [
        "manufacturer", "name", "exists_in_dbpedia", "dbpedia_iri", "wiki_url",
        "year", "sound_generation", "top_level_class",
        "synthesis_type", "polyphony",
    ]

    matched = 0
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        f.flush()

        for i, synth in enumerate(synths):
            try:
                row = process_synth(synth["manufacturer"], synth["name"])
            except Exception as e:
                print(f"[{i+1}/{len(synths)}] ! {e}")
                row = {fn: "" for fn in fieldnames}
                row["manufacturer"] = synth["manufacturer"]
                row["name"] = synth["name"]
                row["exists_in_dbpedia"] = False

            if row["exists_in_dbpedia"]:
                matched += 1
                tags = [row["top_level_class"], row["sound_generation"]]
                tags = [t for t in tags if t]
                print(f"[{i+1}/{len(synths)}] ✓ {row['name']} [{' / '.join(tags)}]")
            else:
                print(f"[{i+1}/{len(synths)}] ✗ {row['name']}")

            writer.writerow(row)
            f.flush()
            time.sleep(DELAY)

    print()
    print(f"Matched: {matched} / {len(synths)} ({100*matched//max(len(synths),1)}%)")
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()