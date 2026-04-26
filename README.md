# Automated Extraction and Knowledge Graph Representation of Data Quality Metrics

**Final Year Project — Emmanuel Awe**

Extracts data quality (DQ) metrics from heterogeneous documents (PDF/DOCX), maps them to the W3C Data Quality Vocabulary (DQV), serialises as RDF/Turtle, and evaluates extraction quality against a manually constructed gold standard.

---

## Project Structure

```
Final Year Project/
├── src/
│   ├── extractor.py        # Main extraction pipeline (rules, tables, spaCy fallback)
│   └── ingest.py           # Document ingestion (PDF via PyMuPDF, DOCX via python-docx)
├── data/
│   ├── Inputs/             # Source documents (PDF/DOCX)
│   ├── Outputs/            # Extracted CSVs per source
│   └── GoldStandard/       # Gold Standard.csv (123 records)
├── output/                 # Generated RDF Turtle files (.ttl)
├── mappings/               # R2RML mapping file
├── Evaluation/
│   ├── match_analysis.py   # Similarity scoring tool - outputs match_analysis.csv
│   └── match_analysis.csv  # Row-by-row comparison of extracted vs gold standard
├── Tools/
│   └── r2rml-master/       # R2RML-F processor (fat jar pre-built)
├── tests/
│   └── test_extractor.py
├── config.properties       # R2RML configuration
└── requirements.txt
```

---

## Setup

**Prerequisites:** Python 3.9+, Java 11+ (for R2RML)

The R2RML processor is included in `Tools/r2rml-master/` and the fat jar is pre-built at `Tools/r2rml-master/target/r2rml-fat.jar` — no build step required.

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

---

## Running the Pipeline

### 1 — Extract metrics from a source document

```bash
python3 src/extractor.py \
  --input  "data/Inputs/<filename>.pdf" \
  --source "<SourceLabel>" \
  --output "data/Outputs/<SourceLabel>_metrics.csv"   # optional; auto-named if omitted
```

The extractor selects the appropriate strategy automatically (table-based for ETSI/IEEE/survey sources, sentence-based for Zaveri-style prose). It writes:
- `data/Outputs/<source>_metrics.csv` — extracted metrics
- `metrics.csv` — copy used by R2RML
- `config.properties` — updated with correct CSV/TTL filenames

### 2 — Generate RDF Turtle via R2RML

```bash
java -jar "Tools/r2rml-master/target/r2rml-fat.jar" config.properties
```

Output is written to `output/<source>_output.ttl`.

### Example (Zaveri survey)

```bash
python3 src/extractor.py \
  --input  "data/Inputs/zaveri-et-al-2015-quality-assessment-for-linked-data-a-survey.pdf" \
  --source "Zaveri"

java -jar "Tools/r2rml-master/target/r2rml-fat.jar" config.properties
```

---

## Evaluated Sources

| Source | Document type | Metrics extracted |
|--------|--------------|-------------------|
| ETSI   | DOCX standard | 12 |
| Zaveri | PDF survey    | 69 |
| IEEE   | PDF standard  | 38 |

---

## Evaluation

`match_analysis.py` computes label and definition similarity scores between each extracted metric and its closest gold standard match. The output (`match_analysis.csv`) was used as the basis for manual classification and evaluation.

```bash
python3 Evaluation/match_analysis.py
```

---

## Tests

```bash
python3 -m pytest tests/ -v
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `PyMuPDF` | PDF text extraction |
| `python-docx` | DOCX ingestion |
| `spaCy` (en_core_web_sm) | Sentence segmentation / dependency parsing |
| `lxml` | OMML formula parsing (DOCX) |
| `pytest` | Test suite |

R2RML-F (Java) is used for CSV-to-RDF mapping and is located in `Tools/r2rml-master/`.
