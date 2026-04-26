"""
Unit tests for the extraction pipeline (extractor.py + ingest.py).

Run:  python -m pytest tests/test_extractor.py -v
"""

import re, sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extractor import (
    _zwsp, _extract_formulas, _tidy, _extract_structured,
    _extract_zaveri_tables, _extract_triplet_tables, _has_table_abbrs,
    extract_metrics,
    infer_dimension, infer_type, gate_candidate, deduplicate,
    _BLACKLISTED_LABELS, _AUTHOR_RE, _METRIC_ABBR_RE, slugify,
)


# ── Label extraction ────────────────────────────────────────────────────────

def test_abbr_regex_extracts_clean_name():
    m = _METRIC_ABBR_RE.match("Attribute Completeness (AC) The ratio of values.")
    assert m and m.group(1).strip() == "Attribute Completeness"


def test_dimension_heading_skipped():
    text = (
        "6.1 Completeness\n"
        "6.1.1 Definition\nCompleteness is a quality characteristic.\n"
        "Attribute Completeness (AC) The ratio of non-null values "
        "to the total number of values for a given attribute in a dataset.\n"
    )
    names = [r["name"] for r in _extract_structured(text)]
    assert "Completeness" not in names
    assert "Attribute Completeness" in names


# ── Zero-width spaces ───────────────────────────────────────────────────────

def test_zwsp_stripped():
    assert _zwsp("hello\u200bworld") == "helloworld"
    assert _zwsp("\ufeffABC") == "ABC"


# ── Gate: determiners, authors, positive case ───────────────────────────────

def test_gate_rejects_and_accepts():
    # determiners rejected
    ok, _ = gate_candidate("This dimension", "This dimension measures the degree to which data is complete.")
    assert not ok
    ok2, _ = gate_candidate("Our approach", "Our approach computes the ratio of valid to total records.")
    assert not ok2
    # author names rejected
    assert _AUTHOR_RE.match("J. Smith")
    assert _AUTHOR_RE.match("Wang et al.")
    # real metric accepted
    ok3, _ = gate_candidate("Accuracy Rate", "The ratio of correct values to total values, calculated as a percentage.")
    assert ok3


# ── Blacklist via gate ──────────────────────────────────────────────────────

@pytest.mark.parametrize("label", ["this", "measurement formula"])
def test_blacklisted_rejected_by_gate(label):
    ok, reasons = gate_candidate(label, "The ratio of correct values to total values, calculated as a percentage.")
    assert not ok and any("blacklist" in r.lower() for r in reasons)


# ── Dimension inference ─────────────────────────────────────────────────────

def test_dimension_mapping():
    assert infer_dimension("Accuracy Rate", "x") == "semanticAccuracy"
    assert infer_dimension("COMPLETENESS INDEX", "x") == "completeness"
    assert infer_dimension("Redundancy Ratio", "x") == "conciseness"
    assert infer_dimension("Foo Bar", "unrelated text here") == "unknown"


# ── Type inference ──────────────────────────────────────────────────────────

def test_type_inference():
    assert infer_type("The ratio of correct values to total values.") == "quantitative"
    assert infer_type("Based on expert judgement and manual review.") == "qualitative"


# ── Formula extraction ──────────────────────────────────────────────────────

def test_formula_extraction():
    # equation goes to formula column
    cleaned, formula = _extract_formulas("The metric is [[FORMULA: AC = N/T]] per attribute.")
    assert "AC = N/T" in formula and "[[FORMULA" not in cleaned
    # lone symbol stays inline (not a formula)
    cleaned2, formula2 = _extract_formulas("The value of [[FORMULA: N]] should be positive.")
    assert formula2 == "" and "N" in cleaned2


# ── Quality gate rejections ──────────────────────────────────────────────────

def test_gate_rejects_bad_candidates():
    # dimension definition
    ok, reasons = gate_candidate(
        "Completeness",
        "Completeness is a quality characteristic that describes whether all required information is present in the dataset.",
    )
    assert not ok and any("dimension" in r.lower() for r in reasons)
    # no measurability signal
    ok2, _ = gate_candidate("Freshness", "Freshness indicates how recent the data is in a general sense.")
    assert not ok2
    # boilerplate
    ok3, _ = gate_candidate("ETSI Standard", "The present document defines a metric for data quality assessment.")
    assert not ok3


# ── Deduplication ────────────────────────────────────────────────────────────

def test_dedup_keeps_first():
    rows = [
        {"MetricLabel": "Accuracy Rate", "Source": "S1", "Definition": "The ratio of correct values to total values in a dataset."},
        {"MetricLabel": "Accuracy Rate", "Source": "S1", "Definition": "Another definition of accuracy that is longer than five."},
    ]
    assert len(deduplicate(rows)) == 1


# ── Subscript normalisation ─────────────────────────────────────────────────

def test_subscript_fix():
    assert "M_req" in _tidy("The value M req should be positive.")
    assert "M_is" not in _tidy("M is the total count of records.")


# ── End-to-end structured extraction ────────────────────────────────────────

_MINI_DOC = (
    "6.1 Completeness\n6.1.1 Definition\nCompleteness is a quality characteristic.\n"
    "Attribute Completeness (AC) The ratio of non-null attribute values to total attribute values for a given dataset.\n"
    "Record Completeness (RC) The ratio of complete records to total records in the dataset, calculated as a percentage.\n"
    "6.2 Accuracy\n"
    "Error Rate (ER) The ratio of erroneous data items to the total number of data items in the dataset.\n"
)


def test_structured_extraction():
    rows = _extract_structured(_MINI_DOC)
    names = [r["name"] for r in rows]
    assert set(names) == {"Attribute Completeness", "Record Completeness", "Error Rate"}
    by = {r["name"]: r for r in rows}
    assert by["Attribute Completeness"]["dimension"] == "completeness"
    assert by["Error Rate"]["dimension"] == "semanticAccuracy"


# ── Alternatively splitting ──────────────────────────────────────────────────

def test_alternatively_splits():
    text = (
        "6.1 Redundancy\n"
        "Record Redundancy Ratio (RRR) The proportion of duplicate records "
        "in the dataset. Alternatively, Duplicate Count (DC) The total "
        "number of exact duplicate records found in the dataset.\n"
    )
    names = [r["name"] for r in _extract_structured(text)]
    assert "Record Redundancy Ratio" in names and "Duplicate Count" in names


# ── OMML conversion ─────────────────────────────────────────────────────────

try:
    from lxml import etree
    _NS_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    _HAS_LXML = True
except ImportError:
    _HAS_LXML = False


@pytest.mark.skipif(not _HAS_LXML, reason="lxml not installed")
def test_omml_multiple_runs_preserved():
    """Dict bug: multiple <m:r> siblings must all appear in output."""
    from ingest import _omml_to_text
    xml = (
        f'<m:oMath xmlns:m="{_NS_M}">'
        f'<m:r><m:t>a</m:t></m:r><m:r><m:t>+</m:t></m:r><m:r><m:t>b</m:t></m:r>'
        f'</m:oMath>'
    )
    result = _omml_to_text(etree.fromstring(xml))
    assert "a" in result and "+" in result and "b" in result


# ── DOCX placeholder integration ────────────────────────────────────────────

_DOCX_PATH = Path(__file__).resolve().parents[1] / "data" / "Inputs" / "DATA-00104180v004 (1).docx"

try:
    from ingest import ingest_docx
    _HAS_DOCX = True
except ImportError:
    _HAS_DOCX = False


@pytest.mark.skipif(not _HAS_DOCX, reason="python-docx not installed")
@pytest.mark.skipif(not _DOCX_PATH.exists(), reason="ETSI DOCX not present")
def test_docx_emits_formula_placeholders():
    """Verify ingest_docx actually produces [[FORMULA: …]] with real content."""
    text = ingest_docx(str(_DOCX_PATH))
    matches = re.findall(r"\[\[FORMULA:\s*.+?\]\]", text)
    assert len(matches) >= 1
    eq_matches = [m for m in matches if "=" in m]
    assert len(eq_matches) >= 1, "Expected at least one Name = … formula"


# ── Slugify ─────────────────────────────────────────────────────────────────

def test_slugify():
    assert slugify("Attribute Completeness") == "attribute-completeness"
    assert slugify("Error Rate (%)") == "error-rate"
    assert slugify("") == "metric"


# ── Zaveri table extraction ──────────────────────────────────────────────────

def test_zaveri_table_detection():
    """_has_table_abbrs returns True when ≥5 abbreviation anchors found."""
    text = "\n".join([
        "availability",
        "A1 accessibility of the SPARQL endpoint checking whether ...",
        "QN",
        "A2 accessibility of the RDF dumps checking whether ...",
        "QN",
        "A3 dereferenceability of the URI checking (i) for dead links",
        "QN",
        "licensing",
        "L1 machine-readable indication of a license detection of ...",
        "QL",
        "L2 human-readable indication of a license detection of ...",
        "QL",
    ])
    assert _has_table_abbrs(text)


def test_zaveri_table_extraction():
    """Table extractor produces correct names, descriptions and dimensions."""
    text = "\n".join([
        "availability",
        "A1 accessibility of the SPARQL endpoint and the server checking whether the server responds to a SPARQL query",
        "QN",
        "A2 accessibility of the RDF dumps checking whether an RDF dump is provided and can be downloaded",
        "QN",
        "consistency",
        "CS5 valid usage of inverse-functional properties (i) by checking the uniqueness of values",
        "QN",
        "CS7 no negative dependencies/correlation among properties using association rules",
        "QN",
    ])
    cands = _extract_zaveri_tables(text)
    names = {c["name"] for c in cands}
    assert "accessibility of the SPARQL endpoint and the server" in names
    assert "accessibility of the RDF dumps" in names
    assert "valid usage of inverse-functional properties" in names
    assert "no negative dependencies/correlation among properties" in names

    # Dimensions should be mapped correctly
    by_name = {c["name"]: c for c in cands}
    assert by_name["accessibility of the SPARQL endpoint and the server"]["dimension"] == "availability"
    assert by_name["valid usage of inverse-functional properties"]["dimension"] == "consistency"

    # All should be table-sourced (bypass gate)
    assert all(c.get("_table_sourced") for c in cands)


def test_zaveri_table_extraction_descriptions():
    """Descriptions are cleanly separated from metric names."""
    text = "\n".join([
        "availability",
        "A1 accessibility of the SPARQL endpoint and the server checking whether the server responds to a SPARQL query",
        "QN",
        "security",
        "S1 usage of digital signatures by signing a document containing an RDF serialization",
        "QN",
    ])
    cands = _extract_zaveri_tables(text)
    by_name = {c["name"]: c for c in cands}

    a1 = by_name["accessibility of the SPARQL endpoint and the server"]
    assert a1["description"].lower().startswith("checking whether")

    s1 = by_name["usage of digital signatures"]
    assert "signing" in s1["description"].lower()


# ── Table-sourced gate bypass ───────────────────────────────────────────────

def test_table_sourced_candidates_bypass_gate():
    """Candidates with _table_sourced=True skip the quality gate,
    even if they lack standard metric cues."""
    # "Sentimental value" has no metric cue — the gate would reject it.
    # But as a triplet-table candidate it should be accepted directly.
    text = "\n".join([
        "TABLE 4: Data Value Metrics for Financial Dimension.",
        "Metric",
        "Description",
        "Type",
        "Sentimental value",
        "An estimate of the emotional or personal significance attached to a data asset.",
        "S, O",
        "TABLE 5: Data Value Metrics for Usage Dimension.",
        "Metric",
        "Description",
        "Type",
        "Access interval",
        "A time series measure weighted towards data most recently created.",
        "O",
    ])
    rows = list(extract_metrics(text, source="test-triplet"))
    names = {r["MetricLabel"] for r in rows}
    # Both should be accepted despite lacking standard metric cues
    assert "Sentimental value" in names, f"Expected 'Sentimental value' in {names}"
    assert "Access interval" in names, f"Expected 'Access interval' in {names}"
    assert len(rows) == 2

