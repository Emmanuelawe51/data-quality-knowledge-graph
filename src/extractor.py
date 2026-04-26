import re
import csv
import shutil
import argparse
from pathlib import Path

try:
    import spacy
    _SPACY_OK = True
except ImportError:
    _SPACY_OK = False

# Lookup tables

METRIC_CUES = {
    "completeness", "accuracy", "consistency", "timeliness", "validity",
    "uniqueness", "precision", "reliability", "relevance", "credibility",
    "currentness", "conformance", "conformity", "availability",
    "accessibility", "portability", "recoverability", "traceability",
    "understandability", "compliance", "integrity", "plausibility",
    "fitness", "freshness", "volatility", "latency", "provenance",
    "metric", "metrics", "formula", "measurement", "measure", "score",
    "ratio", "rate", "index", "percentage", "indicator", "proportion",
    "degree", "extent", "level", "count", "threshold", "benchmark",
    "data quality", "dq dimension", "quality dimension",
    "quality characteristic", "quality attribute", "quality factor",
    "quality property", "data value", "value of information",
    "value of data", "error", "mean absolute error", "mean squared error",
    "root mean squared", "coefficient", "standard deviation", "variance",
    "stability", "mae", "mse", "rmse", "cv",
    "measured", "computed", "calculated", "quantified",
    "average", "sum", "total",
    # Zaveri survey-specific cues
    "conciseness", "interlink", "dereference", "dereferenceability",
    "syntax", "throughput", "trust", "trustworthiness", "reputation",
    "interpretability", "interoperability", "versatility",
    "annotation", "labelling", "classification", "serialization",
    "sparql", "rdf", "uri", "vocabulary", "ontology",
    "no. of", "total no.", "detection", "checking",
}
_CUE_PATTERNS = {c: re.compile(rf"\b{re.escape(c)}\b", re.I) for c in METRIC_CUES}

BOILERPLATE_TERMS = [
    "present document", "etsi", "copyright", "liability", "trademark",
    "intellectual property", "ipr", "all rights reserved", "disclaimer",
    "prevailing version", "published by", "approved by", "edition",
    "normative references", "bibliography", "annex", "foreword",
    "terms and definitions", "scope of this", "users of the present",
    "3gpp", "reproduced", "utilized", "modification",
    "associate editor", "received", "revised", "accepted manuscript",
    "doi", "creative commons", "abstract data",
    "ieee", "acm", "springer", "elsevier", "journal of", "proceedings",
    "corresponding author", "university of", "department of",
    "acknowledgment", "acknowledgement", "funding", "grant number",
    "table of contents", "list of figures", "list of tables",
    "page", "chapter", "section", "clause", "figure",
]
_BOILERPLATE_RE = re.compile(
    "|".join(re.escape(t) for t in BOILERPLATE_TERMS), re.I
)

_BLACKLISTED_LABELS = {
    # Pronouns / determiners
    "this", "that", "these", "those", "it", "they", "we", "you",
    "he", "she", "one", "some", "any", "all", "both",
    # Generic document structure
    "definition", "example", "conclusion", "introduction", "abstract",
    "summary", "overview", "background", "motivation", "discussion",
    "evaluation", "references", "scope", "foreword",
    "terms and definitions", "normative references", "informative references",
    # Meta-references
    "this dimension", "this paper", "this study", "this survey",
    "this section", "this approach", "this method",
    "the authors", "the paper", "the result", "the results",
    "our approach", "our method", "our model", "our work",
    # Structural labels that aren't metrics
    "measurement formula", "measurement function", "measurement method",
    "a common approach",
}

# Substring match against definition only (cf. METRIC_CUES which uses word-boundary regex on name+definition+sentence).
_MEASURABILITY_CUES = [
    # Quantitative language
    "ratio", "percentage", "proportion", "count", "number of",
    "formula", "calculated", "computed", "measured", "quantified",
    "score", "index", "coefficient", "rate", "frequency",
    "fraction", "sum", "average", "mean", "total",
    "no. of", "total no.",
    # Degree / extent phrases
    "degree to which", "extent to which", "the degree",
    "how much", "how well", "how often", "how many",
    # Statistical / analytical
    "probability", "likelihood",
    "measurable", "quantify", "assess", "evaluate",
    "weighted", "normalized", "normalised",
    # Operators
    "%", "=", ">=", "<=", "/",
    # Action verbs (Zaveri-style descriptions)
    "checking", "detecting", "detection", "computing", "measuring",
    "verifying", "identifying", "obtaining", "assignment",
]

# Maps keywords in metric name/definition to DQV dimension slugs.
_DIMENSION_KEYWORDS = {
    "completeness": "completeness",
    "accuracy": "semanticAccuracy",
    "consistency": "consistency",
    "credibility": "trustworthiness",
    "believability": "trustworthiness",
    "currentness": "timeliness",
    "timeliness": "timeliness",
    "accessibility": "availability",
    "compliance": "consistency",
    "confidentiality": "security",
    "efficiency": "performance",
    "precision": "semanticAccuracy",
    "traceability": "semanticAccuracy",
    "provenance": "semanticAccuracy",
    "understandability": "understandability",
    "availability": "availability",
    "portability": "interoperability",
    "recoverability": "availability",
    "reliability": "consistency",
    "redundancy": "conciseness",
    # Zaveri survey dimension headers (exact matches)
    "licensing": "licensing",
    "interlinking": "interlinking",
    "security": "security",
    "performance": "performance",
    "syntactic validity": "syntacticValidity",
    "semantic accuracy": "semanticAccuracy",
    "conciseness": "conciseness",
    "relevancy": "relevancy",
    "trustworthiness": "trustworthiness",
    "interoperability": "interoperability",
    "interpretability": "interpretability",
    "versatility": "versatility",
    "representationalconciseness": "representationalConciseness",
}
_KNOWN_DIMENSIONS = set(_DIMENSION_KEYWORDS.values()) | set(_DIMENSION_KEYWORDS.keys())

_AUTHOR_RE = re.compile(
    r"^[A-Z]\.\s*[A-Z][a-z]+$|^[A-Z][a-z]+\s+et\s+al\.?$|^[A-Z][a-z]+\s*,\s*[A-Z]\.$"
)

MIN_DEF_WORDS = 5
OUT_CSV = Path(__file__).resolve().parents[1] / "data" / "Outputs" / "metrics.csv"

_DEMO_TEXT = (
    "The Completeness metric measures the degree to which all required "
    "information is present.\n"
    "Accuracy is the degree to which data correctly describes real-world events."
)

# Common short English words that should NOT be treated as subscript artefacts
_COMMON_SHORT = frozenset(
    "a an as at be by do go if in is it no of on or so to up us we am and are "
    "but can for has its may not our out own the too was who all any had her him "
    "his how let new now old one per set she two use via way yet also been both "
    "data each from have into just like more most much must near next only over "
    "same some such than that them then they this thus very were what when will "
    "with about after being below could every lower often other shall since their "
    "these those under using value where which while would common".split()
)

# Regex patterns

_ZWSP_RE = re.compile(r"[​‌‍﻿]")

_TRUNCATION_RE = re.compile(
    r"\s*\b(?:However|Note|For example|For instance|See also|"
    r"In addition|Furthermore|Moreover|Although|Conversely|"
    r"It should be noted|N\.?B\.?)\b", re.I,
)

_DIMENSION_HEADING_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*$"
)
_STRUCTURAL_HEADING_RE = re.compile(
    r"^\s*\d+(?:\.\d+)*\s+(?:Definition|Measurement\s+Formula|"
    r"Measurement\s+Function|Measurement\s+Method|Introduction|Scope|"
    r"Overview|Background|References|Example|General|Description)\b", re.I,
)

# Abbreviation may contain spaces/zwsp from OMML subscript expansion
_ABBR_CHAR = r"[\s​‌‍﻿A-Za-z0-9]"
_METRIC_ABBR_RE = re.compile(
    rf"^(?:\d+(?:\.\d+)*\s+)?"
    rf"((?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*))"
    rf"\s*\(([A-Z]{_ABBR_CHAR}{{0,9}})\)\s*[:.]?\s*(.+)", re.S,
)
_METRIC_COLON_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+)?"
    r"((?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+))\s*:\s*(.+)", re.S,
)

_ALT_INLINE_RE = re.compile(
    rf"[.:]\s*Alternatively,?\s+"
    rf"((?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*))"
    rf"\s*\(([A-Z]{_ABBR_CHAR}{{0,9}})\)\s+(.+)", re.S,
)
_ALT_LINE_RE = re.compile(
    rf"^Alternatively,?\s+((?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*))"
    rf"\s*\(([A-Z]{_ABBR_CHAR}{{0,9}})\)",
)

_FORMULA_PH_RE = re.compile(r"\[\[FORMULA:\s*(.+?)\]\]")
_FORMULA_SIGNAL_RE = re.compile(r"[=∑∏√]|/(?![^\w])")

# Tidying patterns
_HOLLOW_LET_RE = re.compile(r"\bLet\s+.{1,40}?\s+be\b[^.]*\.\s*", re.I)
_HOLLOW_WHERE_RE = re.compile(r"\bWhere:\s+is\b[^.]*\.\s*", re.I)
_TRAILING_PREAMBLE_RE = re.compile(
    r"\.\s+For\s+.{5,120}?\b(?:measures|metrics|methods|formulas|approaches)\s*[:.]?\s*$",
    re.I,
)
_PUNCT_FIXES = [
    (re.compile(r":\s*\."), "."),
    (re.compile(r"\)\s*\.\s*\."), ")."),
    (re.compile(r"\.\s*\."), "."),
    (re.compile(r";\s*\."), "."),
    (re.compile(r":\s*$"), "."),
    (re.compile(r"[;:.,\s]+$"), "."),
]

# Utilities

nlp = None
if _SPACY_OK:
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        pass


def _zwsp(s: str) -> str:
    """Strip zero-width space characters."""
    return _ZWSP_RE.sub("", s)


def slugify(name: str) -> str:
    """Convert name to a lowercase, hyphen-separated URI-safe slug."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.strip().lower())).strip("-") or "metric"


def _truncate(definition: str) -> str:
    """Cut at semicolons and discourse markers; ensure trailing period."""
    if not definition:
        return definition
    definition = definition.split(";")[0].strip()
    m = _TRUNCATION_RE.search(definition)
    if m:
        definition = definition[:m.start()].strip()
    if definition and not definition.endswith("."):
        definition = definition.rstrip(",;: ") + "."
    return definition


def _extract_formulas(text: str) -> tuple[str, str]:
    """Split [[FORMULA: ...]] placeholders into (cleaned_text, formulas_joined).
    Real formulas (containing = or math operators) go to the Formula column; lone symbols are inlined.
    """
    real: list[str] = []

    def _repl(m):
        body = m.group(1).strip()
        if _FORMULA_SIGNAL_RE.search(body):
            real.append(body)
            return ""
        return body

    cleaned = _FORMULA_PH_RE.sub(_repl, text)
    return " ".join(cleaned.split()), " ; ".join(real)


def _tidy(text: str) -> str:
    """Final cleanup pass on a definition after formula extraction."""
    if not text:
        return text

    # Fix OMML subscript spacing ("M req" -> "M_req")
    def _sub_fix(m):
        if m.group(2) in _COMMON_SHORT:
            return m.group(0)
        return f"{m.group(1)}_{m.group(2)}"

    text = re.sub(r"\b([A-Z])\s+([a-z]{1,6})\b", _sub_fix, text)

    text = _HOLLOW_LET_RE.sub("", text)
    text = _HOLLOW_WHERE_RE.sub("", text)

    m = _TRAILING_PREAMBLE_RE.search(text)
    if m:
        text = text[:m.start()] + "."

    text = " ".join(text.split())
    for pat, repl in _PUNCT_FIXES:
        text = pat.sub(repl, text)
    text = " ".join(text.split()).strip()

    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    if text and not text.endswith("."):
        text = text.rstrip(",;: ") + "."
    return text


def _clean_and_tidy(raw: str) -> str:
    """Strip zero-width chars, normalise whitespace, truncate, tidy."""
    return _tidy(_truncate(_zwsp(raw)))


def infer_dimension(name: str, definition: str) -> str:
    """Infer the DQV dimension slug for a metric by keyword match.

    Searches name first, then definition, against _DIMENSION_KEYWORDS.
    Returns "unknown" if no keyword matches.
    """
    for kw, slug in _DIMENSION_KEYWORDS.items():
        if kw in name.lower():
            return slug
    for kw, slug in _DIMENSION_KEYWORDS.items():
        if kw in definition.lower():
            return slug
    return "unknown"


def infer_type(definition: str) -> str:
    """Classify a metric as "qualitative" (subjective/expert-driven) or "quantitative" (default)."""
    d = definition.lower()
    for c in ("expert", "subjective", "judgement", "judgment", "likert",
              "questionnaire", "survey", "interview", "manual review",
              "qualitative", "opinion"):
        if c in d:
            return "qualitative"
    return "quantitative"


# Quality gate

def gate_candidate(name, definition, sentence="", formula=""):
    """Run all quality checks. Returns (accepted: bool, reasons: list[str])."""
    clean = name.strip().lower()

    # Blacklisted or author-name label
    if clean in _BLACKLISTED_LABELS:
        return False, [f"REJECT: blacklisted label: '{clean}'"]
    if _AUTHOR_RE.match(name.strip()):
        return False, [f"REJECT: author name: '{name}'"]
    if re.match(r"^(This|That|These|Those|Our|Their|Its)\s", name):
        return False, [f"REJECT: determiner-led label: '{name}'"]

    # Boilerplate
    combined = f"{name} {definition}".lower()
    bp = _BOILERPLATE_RE.search(combined)
    if bp:
        return False, [f"REJECT: boilerplate: '{bp.group()}'"]

    # Too short
    if len(definition.split()) < MIN_DEF_WORDS:
        return False, [f"REJECT: too short ({len(definition.split())} words)"]

    # Dimension definition, not a metric
    dl = definition.lower()
    if ("dimension" in dl or "quality characteristic" in dl) and \
       not any(w in dl for w in ("metric", "formula", "measurement", "calculated")):
        return False, ["REJECT: dimension definition, not a metric"]

    # Must match a metric cue
    full = f"{name} {definition} {sentence}"
    cue_reason = None
    for cue, pat in _CUE_PATTERNS.items():
        if pat.search(full):
            cue_reason = f"matched cue: '{cue}'"
            break
    if not cue_reason:
        return False, ["REJECT: no metric cue found"]

    # Must show measurability (or have a formula)
    if formula:
        meas_reason = "has formula"
    else:
        meas_reason = None
        for cue in _MEASURABILITY_CUES:
            if cue in dl:
                meas_reason = f"measurability cue: '{cue}'"
                break
    if not meas_reason:
        return False, ["REJECT: no measurability signal in definition"]

    return True, [f"ACCEPT: {cue_reason}, {meas_reason}"]


# Deduplication

def deduplicate(rows):
    """Keep first occurrence; only replace if existing def is very short."""
    seen, order = {}, []
    for row in rows:
        key = (re.sub(r"\s+", " ", row["MetricLabel"].strip().lower()), row["Source"])
        if key not in seen:
            seen[key] = row
            order.append(key)
        elif len(seen[key]["Definition"].split()) < MIN_DEF_WORDS \
                and len(row["Definition"].split()) > len(seen[key]["Definition"].split()):
            seen[key] = row
    return [seen[k] for k in order]


# spaCy extraction (fallback for unstructured text)

def _extract_spacy(text):
    """Fallback extractor using spaCy dependency parsing.
    Looks for noun-phrase + is/measures/refers-to patterns. Returns [] if spaCy unavailable.
    """
    if not nlp:
        return []
    doc = nlp(text)
    candidates = []
    stop = {"this", "that", "these", "those", "it", "they", "we", "you", "he", "she"}
    verbs = {"is", "measure", "refer", "mean", "be"}

    for sent in doc.sents:
        if not sent.text.strip():
            continue
        for token in sent:
            if token.lemma_ not in verbs and token.text.lower() not in \
               {"is", "measures", "refers", "means"}:
                continue
            subjects = [t for t in token.lefts if t.dep_ in ("nsubj", "nsubjpass", "nmod")]
            if not subjects:
                continue

            subj = subjects[0]
            toks = sorted(
                [c for c in subj.lefts if c.dep_ in ("compound", "amod", "det")] + [subj]
                + [c for c in token.children if c.dep_ == "amod" and subj.i < c.i < token.i],
                key=lambda t: t.i,
            )
            name = re.sub(r"^the\s+", "", " ".join(t.text for t in toks).strip(), flags=re.I).strip()
            if name.lower() in stop or len(name) < 3:
                continue
            if not any(t.pos_ in ("NOUN", "PROPN") for t in toks):
                continue
            name = name[0].upper() + name[1:]

            raw_def = " ".join(doc[token.i:sent.end].text.split())
            raw_def = re.sub(r'\s+([.,;!?])', r'\1', raw_def)
            raw_def = _truncate(raw_def)

            if len(raw_def) > 10 and raw_def.endswith('.'):
                clean_def, formulas = _extract_formulas(raw_def)
                candidates.append({
                    "name": name,
                    "description": _clean_and_tidy(clean_def) if clean_def else raw_def,
                    "sentence": sent.text.strip(),
                    "dimension": None,
                    "formula": formulas,
                })
                break
    return candidates


# Table extraction (for survey-style PDFs like Zaveri)

# Zaveri-style abbreviation anchor: 1-4 uppercase letters + 1-2 digits
_TABLE_ABBR_RE = re.compile(r"^([A-Z]{1,4}\d{1,2})\s+(.+)")

# Maps dimension header text to DQV slugs.
_ZAVERI_DIM_MAP = {
    "availability":                "availability",
    "licensing":                   "licensing",
    "interlinking":                "interlinking",
    "security":                    "security",
    "performance":                 "performance",
    "syntactic validity":          "syntacticValidity",
    "semantic accuracy":           "semanticAccuracy",
    "consistency":                 "consistency",
    "conciseness":                 "conciseness",
    "completeness":                "completeness",
    "relevancy":                   "relevancy",
    "trustworthiness":             "trustworthiness",
    "understandability":           "understandability",
    "timeliness":                  "timeliness",
    "representationalconciseness": "representationalConciseness",
    "interoperability":            "interoperability",
    "interpretability":            "interpretability",
    "versatility":                 "versatility",
}

# Authoritative name lookup: abbreviation -> exact metric name as it appears in Zaveri et al. (2015).
_ZAVERI_METRIC_NAMES = {
    "A1":  "accessibility of the SPARQL endpoint and the server",
    "A2":  "accessibility of the RDF dumps",
    "A3":  "dereferenceability of the URI",
    "A4":  "no misreported content types",
    "A5":  "dereferenced forward-links",
    "L1":  "machine-readable indication of a license",
    "L2":  "human-readable indication of a license",
    "L3":  "specifying the correct license",
    "I1":  "detection of good quality interlinks",
    "I2":  "existence of links to external data providers",
    "I3":  "dereferenced back-links",
    "S1":  "usage of digital signatures",
    "S2":  "authenticity of the dataset",
    "P1":  "usage of slash-URIs",
    "P2":  "low latency",
    "P3":  "high throughput",
    "P4":  "scalability of a data source",
    "SV1": "no syntax errors of the documents",
    "SV2": "syntactically accurate values",
    "SV3": "no malformed datatype literals",
    "SA1": "no outliers",
    "SA2": "no inaccurate values",
    "SA3": "no inaccurate annotations, labellings or classifications",
    "SA4": "no misuse of properties",
    "SA5": "detection of valid rules",
    "CS1": "no use of entities as members of disjoint classes",
    "CS2": "no misplaced classes or properties",
    "CS3": "no misuse of owl:DatatypeProperty or owl:ObjectProperty",
    "CS4": "members of owl:DeprecatedClass or owl:DeprecatedProperty not used",
    "CS5": "valid usage of inverse-functional properties",
    "CS6": "absence of ontology hijacking",
    "CS7": "no negative dependencies/correlation among properties",
    "CS8": "no inconsistencies in spatial data",
    "CS9": "correct domain and range",
    "CS10":"no inconsistent values",
    "CN1": "high intensional conciseness",
    "CN2": "high extensional conciseness",
    "CN3": "usage of unambiguous annotations/labels",
    "CM1": "schema completeness",
    "CM2": "property completeness",
    "CM3": "population completeness",
    "CM4": "interlinking completeness",
    "R1":  "relevant terms within metainformation attributes",
    "R2":  "coverage",
    "T1":  "trustworthiness of statements",
    "T2":  "trustworthiness through reasoning",
    "T3":  "trustworthiness of statements, datasets and rules",
    "T4":  "trustworthiness of a resource",
    "T5":  "trustworthiness of the information provider",
    "T6":  "trustworthiness of information provided (content trust)",
    "T7":  "reputation of the dataset",
    "U1":  "human-readable labelling of classes, properties and entities as well as presence of metadata",
    "U2":  "indication of one or more exemplary URIs",
    "U3":  "indication of a regular expression that matches the URIs of a dataset",
    "U4":  "indication of an exemplary SPARQL query",
    "U5":  "indication of the vocabularies used in the dataset",
    "U6":  "provision of message boards and mailing lists",
    "TI1": "freshness of datasets based on currency and volatility",
    "TI2": "freshness of datasets based on their data source",
    "RC1": "keeping URIs short",
    "RC2": "no use of prolix RDF features",
    "IO1": "re-use of existing terms",
    "IO2": "re-use of existing vocabularies",
    "IN1": "use of self-descriptive formats",
    "IN2": "detecting the interpretability of data",
    "IN3": "invalid usage of undefined classes and properties",
    "IN4": "no misinterpretation of missing values",
    "V1":  "provision of the data in different serialization formats",
    "V2":  "provision of the data in various languages",
}


def _has_table_abbrs(text):
    """Return True if text contains >= 5 Zaveri-style abbreviation anchors (e.g. A1, CS5)."""
    count = sum(1 for line in text.splitlines() if _TABLE_ABBR_RE.match(line.strip()))
    return count >= 5


def _extract_zaveri_tables(text):
    """Extract metrics from Zaveri-style PDF tables using the authoritative name lookup.
    Returns candidates with _table_sourced=True to bypass the quality gate.
    """
    lines = text.splitlines()
    candidates = []
    dim_slug = "unknown"

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Dimension header
        low = line.lower()
        if low in _ZAVERI_DIM_MAP:
            dim_slug = _ZAVERI_DIM_MAP[low]
            i += 1
            continue

        # Metric row: starts with an abbreviation anchor
        m = _TABLE_ABBR_RE.match(line)
        if m:
            abbr = m.group(1)
            rest = m.group(2).strip()

            # Gather continuation lines until QN/QL, next abbr, or blank
            parts = [rest]
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    break
                if nxt in ("QN", "QL"):
                    j += 1
                    break
                if _TABLE_ABBR_RE.match(nxt):
                    break
                if nxt.lower() in _ZAVERI_DIM_MAP:
                    break
                parts.append(nxt)
                j += 1

            raw = " ".join(parts)
            # Strip citation references like [17,29]
            raw = re.sub(r"\s*\[\d+(?:,\s*\d+)*\]", "", raw).strip()

            # Name / description split using authoritative lookup
            known_name = _ZAVERI_METRIC_NAMES.get(abbr)
            if known_name:
                # Normalise ligatures for comparison
                norm_raw = raw.replace("ﬁ", "fi").replace("ﬂ", "fl")
                norm_name = known_name.replace("ﬁ", "fi").replace("ﬂ", "fl")

                if norm_raw.lower().startswith(norm_name.lower()):
                    name = known_name
                    desc = raw[len(norm_name):].strip()
                else:
                    # Fallback: fuzzy prefix match (PDF may have minor diffs)
                    name = known_name
                    desc = raw
            else:
                # Unknown abbreviation -- simple word-count heuristic
                tokens = raw.split()
                split_at = min(6, len(tokens))
                name = " ".join(tokens[:split_at])
                desc = " ".join(tokens[split_at:])

            # Clean up name
            name = re.sub(r"[\s,;:]+$", "", name).strip()
            if not name or len(name) < 2:
                i = j
                continue

            # Clean up description
            desc = re.sub(r"^[\s,;:.]+", "", desc).strip()
            desc = re.sub(r"^\((?:i|ii|iii|minimum|maximum)\)\s*", "", desc).strip()

            if desc:
                desc = _clean_and_tidy(desc)
            if not desc or len(desc.split()) < 3:
                # No separate description -- synthesise from name and dimension.
                dim_label = dim_slug.replace("_", " ") if dim_slug != "unknown" else "data quality"
                desc = (f"Metric for {dim_label}: {name}. "
                        f"Assessed as part of the Zaveri linked data quality survey.")

            candidates.append({
                "name":       name,
                "description": desc,
                "sentence":   f"[{abbr}] {raw[:120]}",
                "dimension":  dim_slug,
                "formula":    "",
                "_table_sourced": True,   # signal to skip quality gate
            })

            i = j
            continue

        i += 1

    return candidates


# Triplet-table extraction (survey-style PDFs)

# Matches "TABLE N: Data Value Metrics for <Dimension> Dimension ..."
_TRIPLET_HDR_RE = re.compile(
    r"^TABLE\s+\d+\s*[:.]\s*Data\s+Value\s+Metrics\s+for\s+"
    r"(.+?)\s+Dimension", re.I | re.M,
)
# Type-marker line: standalone S, O, or S, O (with optional trailing junk)
_TYPE_MARKER_RE = re.compile(r"^([SO](?:\s*,\s*[SO])?)(?:\s|$)")
# Column header lines to skip
_COL_HEADERS = frozenset({"metric", "description", "type"})

# Maps table header dimension text to DQV slugs; extends _DIMENSION_KEYWORDS.
_TRIPLET_DIM_MAP = {
    "financial":          "unknown",
    "content-uniqueness": "unknown",
    "usage":              "unknown",
    "utility":            "unknown",
}
_TRIPLET_DIM_MAP.update({k: v for k, v in _DIMENSION_KEYWORDS.items()})


def _has_triplet_tables(text):
    """Return True if the text contains at least 2 triplet-style table headers."""
    return len(_TRIPLET_HDR_RE.findall(text)) >= 2


def _extract_triplet_tables(text):
    """Extract metrics from survey-style triplet tables (Metric / Description / Type rows).
    Incomplete triplets are dropped rather than salvaged with fragile heuristics.
    """
    lines = text.splitlines()
    candidates = []
    in_table = False
    dim_slug = "unknown"
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Detect table header
        hdr = _TRIPLET_HDR_RE.match(line)
        if hdr:
            raw_dim = hdr.group(1).strip().lower().replace(" ", "-")
            dim_slug = _TRIPLET_DIM_MAP.get(
                raw_dim,
                _TRIPLET_DIM_MAP.get(raw_dim.replace("-", " "), "unknown"),
            )
            in_table = True
            i += 1
            continue

        if not in_table:
            i += 1
            continue

        # Skip column header lines
        if line.lower() in _COL_HEADERS:
            i += 1
            continue

        # End-of-table detection
        if line.startswith("TABLE") and not _TRIPLET_HDR_RE.match(line):
            in_table = False
            i += 1
            continue
        # Blank line -- skip but stay in table
        if not line:
            i += 1
            continue

        # Read metric name
        name = line
        # If this looks like a bare type marker, we're out of sync -- skip
        if _TYPE_MARKER_RE.match(name) and len(name) < 6:
            i += 1
            continue
        # Numbered section heading (e.g. "5) Utility-based Models") -> end table
        if re.match(r"^\d+\)\s", name):
            in_table = False
            i += 1
            continue
        # Very long line is prose, not a metric name -> end table
        if len(name) > 120:
            in_table = False
            i += 1
            continue

        # Read description lines until type marker
        j = i + 1
        desc_parts = []
        while j < len(lines):
            nxt = lines[j].strip()
            # Next table header -> stop gathering
            if _TRIPLET_HDR_RE.match(nxt) or \
               (nxt.startswith("TABLE") and not _TRIPLET_HDR_RE.match(nxt)):
                break
            # Blank line -- skip (page-break noise) but keep gathering
            if not nxt:
                j += 1
                continue
            # Type marker -> triplet is complete
            if _TYPE_MARKER_RE.match(nxt):
                j += 1
                break
            # Otherwise it's a continuation of the description
            desc_parts.append(nxt)
            j += 1

        # No description gathered -> incomplete triplet, skip
        if not desc_parts:
            i = j
            continue

        # Clean up name and description
        desc = " ".join(desc_parts)
        name = re.sub(r"\s*\[\d+(?:[,\s]*\d+)*\]", "", name).strip()
        desc = re.sub(r"\s*\[\d+(?:[,\s]*\d+)*\]", "", desc).strip()
        name = re.sub(r"[\s,;:]+$", "", name).strip()
        if desc:
            desc = _clean_and_tidy(desc)

        if not name or len(name) < 2 or not desc:
            i = j
            continue

        sentence = f"{name}: {desc[:100]}"
        candidates.append({
            "name":        name,
            "description": desc,
            "sentence":    sentence,
            "dimension":   dim_slug,
            "formula":     "",
            "_table_sourced": True,   # bypass quality gate (curated table)
        })

        i = j
        continue

    return candidates


# Structured extraction (standards-style DOCX)

def _is_continuation_stop(clean_line):
    """Return True if clean_line starts a new section/metric/heading."""
    if re.match(r"^\d+(?:\.\d+)+\s+", clean_line):
        return True
    if _METRIC_ABBR_RE.match(clean_line):
        return True
    if _METRIC_COLON_RE.match(clean_line):
        return True
    if _DIMENSION_HEADING_RE.match(clean_line):
        return True
    if _ALT_LINE_RE.match(clean_line):
        return True
    return False


def _gather_continuation(lines, start, stop_fn=_is_continuation_stop):
    """Collect continuation lines from start until a stop condition."""
    parts, j = [], start
    while j < len(lines):
        nxt = lines[j].strip()
        if not nxt or stop_fn(_zwsp(nxt)):
            break
        parts.append(nxt)
        j += 1
    return parts, j


def _make_candidate(name, definition, line, dim_slug, formula=""):
    """Build a candidate metric dict with default fields filled in."""
    return {"name": name, "description": definition, "sentence": line,
            "dimension": dim_slug or "unknown", "formula": formula}


def _extract_structured(text):
    """Extract metrics from standards-style structured text.
    Dispatches on dimension headings, metric-abbreviation patterns, and name-colon patterns.
    Handles inline and next-line 'Alternatively, ...' variants.
    """
    lines = text.splitlines()
    candidates = []
    dim_slug = None
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        cl = _zwsp(line)

        # Dimension heading
        m = _DIMENSION_HEADING_RE.match(cl)
        if m:
            dn = m.group(2).strip().lower()
            if dn in _KNOWN_DIMENSIONS:
                dim_slug = _DIMENSION_KEYWORDS.get(dn, dn)
                i += 1
                continue

        # Structural sub-heading (skip)
        if _STRUCTURAL_HEADING_RE.match(cl):
            i += 1
            continue

        # --- Metric (ABBR) pattern ---
        m = _METRIC_ABBR_RE.match(cl)
        if m:
            metric_name, def_start = m.group(1).strip(), m.group(3).strip()
            cont, j = _gather_continuation(lines, i + 1)
            definition = _truncate(" ".join([def_start] + cont))
            definition = _zwsp(definition)
            definition = " ".join(definition.split())

            # Handle "Alternatively, Name (ABBR) ..." on the next line
            alt_candidates = []
            if j < len(lines):
                alt_cl = _zwsp(lines[j].strip())
                alt_m = _ALT_LINE_RE.match(alt_cl)
                if alt_m:
                    alt_name = alt_m.group(1).strip()
                    alt_rest = re.sub(
                        r"^Alternatively,?\s+" + re.escape(alt_name)
                        + r"\s*\([A-Z][A-Za-z0-9]{0,5}\)\s*", "", alt_cl,
                    ).strip()
                    k = j + 1
                    alt_parts = [alt_rest] if alt_rest else []
                    if alt_rest.rstrip().endswith(":"):
                        if k < len(lines) and _FORMULA_PH_RE.search(lines[k].strip()):
                            alt_parts.append(lines[k].strip())
                            k += 1
                    else:
                        extra, k = _gather_continuation(lines, k)
                        alt_parts.extend(extra)
                    alt_def = _clean_and_tidy(" ".join(alt_parts))
                    if alt_name.lower() not in _KNOWN_DIMENSIONS \
                       and len(alt_def.split()) >= MIN_DEF_WORDS:
                        alt_candidates.append(_make_candidate(
                            alt_name, alt_def, lines[j].strip(), dim_slug))
                    j = k

            # Handle inline "Alternatively, Name (ABBR) ..." within definition
            split_m = _ALT_INLINE_RE.search(definition)
            if split_m:
                first = _clean_and_tidy(definition[:split_m.start()].strip())
                second_name = split_m.group(1).strip()
                second_def = _clean_and_tidy(split_m.group(3).strip())
                if first and len(first.split()) >= MIN_DEF_WORDS:
                    definition = first
                if second_name.lower() not in _KNOWN_DIMENSIONS \
                   and len(second_def.split()) >= MIN_DEF_WORDS:
                    alt_candidates.append(_make_candidate(
                        second_name, second_def,
                        f"Alternatively, {second_name}", dim_slug))

            if metric_name.lower() in _KNOWN_DIMENSIONS:
                i = j
                continue

            cdef, formulas = _extract_formulas(definition)
            cdef = _clean_and_tidy(cdef) if cdef else definition
            if cdef and len(cdef.split()) >= MIN_DEF_WORDS:
                candidates.append(_make_candidate(metric_name, cdef, line, dim_slug, formulas))

            for dc in alt_candidates:
                dc_clean, dc_f = _extract_formulas(dc["description"])
                dc["description"] = _clean_and_tidy(dc_clean) if dc_clean else dc["description"]
                dc["formula"] = dc_f
            candidates.extend(alt_candidates)

            i = j
            continue

        # --- Name: definition fallback ---
        m = _METRIC_COLON_RE.match(cl)
        if m:
            metric_name, def_start = m.group(1).strip(), m.group(2).strip()
            cont, j = _gather_continuation(lines, i + 1)
            definition = _truncate(" ".join([def_start] + cont))
            definition = _zwsp(definition)
            definition = " ".join(definition.split())

            if metric_name.lower() in _KNOWN_DIMENSIONS:
                i = j
                continue
            if metric_name.strip().lower() in _BLACKLISTED_LABELS:
                i = j
                continue

            if len(definition.split()) >= MIN_DEF_WORDS:
                cdef, formulas = _extract_formulas(definition)
                cdef = _clean_and_tidy(cdef) if cdef else definition
                candidates.append(_make_candidate(metric_name, cdef, line, dim_slug, formulas))
            i = j
            continue

        i += 1
    return candidates


def _has_structured_sections(text):
    """Return True if text contains at least 2 dimension-style headings (e.g. "4.1 Completeness")."""
    count = 0
    for line in text.splitlines():
        m = _DIMENSION_HEADING_RE.match(line.strip())
        if m and m.group(2).strip().lower() in _KNOWN_DIMENSIONS:
            count += 1
            if count >= 2:
                return True
    return False


# Main pipeline

def extract_metrics(text, source="manual-demo-text", debug_rejects=False):
    """Extract metrics -> yield accepted row dicts."""
    if _has_structured_sections(text):
        print("Using structured extraction ...")
        raw = _extract_structured(text)
        print(f"  Found {len(raw)} raw candidates")
    elif _has_table_abbrs(text):
        print("Using table extraction (Zaveri et al. 2015) ...")
        raw = _extract_zaveri_tables(text)
        print(f"  Found {len(raw)} raw candidates")
    elif _has_triplet_tables(text):
        print("Using triplet-table extraction (Metric/Description/Type) ...")
        raw = _extract_triplet_tables(text)
        print(f"  Found {len(raw)} raw candidates")
    elif nlp:
        print("Using spaCy extraction ...")
        raw = _extract_spacy(text)
    else:
        raw = []

    if not raw:
        print("No candidates found.")
        extract_metrics._last_rejected = []
        return

    accepted, rejected = [], []
    for c in raw:
        name    = c["name"]
        desc    = c["description"]
        sentence = c["sentence"]
        formula  = c["formula"]
        dim      = c["dimension"]
        table_sourced = c.get("_table_sourced", False)

        # Table-extracted candidates (Zaveri or triplet tables) come from
        # curated survey tables -- skip the general-purpose quality gate.
        if table_sourced:
            ok, reasons = True, ["ACCEPT: table-sourced (curated survey table)"]
        else:
            ok, reasons = gate_candidate(name, desc, sentence, formula)
        if ok:
            accepted.append({
                "MetricID": slugify(name),
                "MetricLabel": name,
                "Definition": desc,
                "Formula": formula if formula.strip() else "NULL",
                "Source": source,
                "Dimension": dim if dim else infer_dimension(name, desc),
                "MetricType": infer_type(desc),
            })
        else:
            rejected.append({
                "MetricLabel": name,
                "Definition": desc,
                "Reasons": "; ".join(reasons),
                "SentenceSnippet": sentence[:120],
            })

    accepted = deduplicate(accepted)
    print(f"  {len(raw)} raw: {len(accepted)} accepted, {len(rejected)} rejected")
    yield from accepted
    extract_metrics._last_rejected = rejected


# CLI

def main():
    """CLI entry point: ingest a file, extract metrics, write CSV + R2RML config."""
    ap = argparse.ArgumentParser(description="Extract DQ metric definitions.")
    ap.add_argument("--input", "-i", type=str, default=None)
    ap.add_argument("--source", "-s", type=str, default=None)
    ap.add_argument("--output", "-o", type=str, default=None)
    ap.add_argument("--debug-rejects", action="store_true", default=False)
    args = ap.parse_args()

    print("spaCy loaded" if nlp else "spaCy not available")

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"File not found: {input_path}")
            return
        print(f"Ingesting {input_path.name} ...")
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from ingest import ingest
        text = ingest(str(input_path))
        print(f"  {len(text):,} chars ingested")
        source = args.source or input_path.stem
    else:
        print("No --input; using demo text.")
        text = _DEMO_TEXT
        source = args.source or "manual-demo-text"

    safe = re.sub(r"[^a-zA-Z0-9_]", "_", source)

    if args.output:
        out_csv = Path(args.output)
    else:
        out_csv = OUT_CSV.parent / f"{safe}_metrics.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    fields = ["MetricID", "MetricLabel", "Definition", "Formula",
              "Source", "Dimension", "MetricType"]
    rows = list(extract_metrics(text, source=source, debug_rejects=args.debug_rejects))

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} metrics to {out_csv}")

    if args.debug_rejects:
        rej = getattr(extract_metrics, "_last_rejected", [])
        if rej:
            rcsv = out_csv.with_name(out_csv.stem + "_rejects.csv")
            rf = ["MetricLabel", "Definition", "Reasons", "SentenceSnippet"]
            with rcsv.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rf)
                writer.writeheader()
                writer.writerows(rej)
            print(f"Wrote {len(rej)} rejects to {rcsv}")

    fixed_csv = OUT_CSV.parent / "metrics.csv"
    shutil.copy2(out_csv, fixed_csv)
    print(f"Copied to {fixed_csv.name}")

    out_ttl = OUT_CSV.parent.parent.parent / "output" / f"{safe}_output.ttl"
    config_path = OUT_CSV.parent.parent.parent / "config.properties"
    config_path.write_text(
        f"# R2RML-F config (auto-generated for source: {source})\n"
        f"CSVFiles = {fixed_csv.relative_to(config_path.parent)}\n"
        f"mappingFile = mappings/dqv-mapping.ttl\n"
        f"outputFile = {out_ttl.relative_to(config_path.parent)}\n"
        f"format = TURTLE\n",
        encoding="utf-8",
    )
    out_ttl.parent.mkdir(parents=True, exist_ok=True)
    print(f"Config updated: CSV={out_csv.name}, TTL={out_ttl.name}")


if __name__ == "__main__":
    main()
