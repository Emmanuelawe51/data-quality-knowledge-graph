# Data Quality Metric Extraction and Knowledge Graph

Final Year Project by Emmanuel Awe.

This project extracts data quality metrics from PDF and DOCX documents, stores
them in a consistent CSV schema, and maps them to RDF using the W3C Data Quality
Vocabulary (DQV), SKOS, and Dublin Core Terms.

The pipeline combines document-specific rules, table parsing, regular
expressions, and spaCy-based sentence processing. It was evaluated against a
manually constructed gold standard containing 123 metric records. The complete
methodology and results are available in the
[project report](docs/Emmanuel_Awe_Final_Year_Project_Report.pdf).

## Pipeline

```text
PDF or DOCX
    -> document ingestion (PyMuPDF / python-docx)
    -> metric extraction (rules, tables, regex, spaCy fallback)
    -> structured CSV
    -> R2RML-F mapping
    -> RDF/Turtle knowledge graph
```

Each extracted metric can include a label, definition, formula, provenance
source, quality dimension, and quantitative or qualitative type.

## Repository structure

```text
src/                     Python ingestion and extraction pipeline
data/Inputs/             Redistributable input and source-document guide
data/Outputs/            Extracted metric CSV files
data/GoldStandard/       Manually constructed evaluation gold standard
data/LLM results/        Comparison outputs used during the evaluation
mappings/                R2RML and DQV taxonomy mappings
output/                  Generated RDF/Turtle files
Evaluation/              Match-analysis script and comparison table
tests/                   Python extraction tests
Tools/r2rml-master/      Vendored MIT-licensed R2RML-F processor
docs/                    Redacted final project report
```

## Requirements

- Python 3.9 or newer
- Java 17 or newer
- Apache Maven

Create a Python environment and install the project dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

On Windows, activate the environment with `.venv\Scripts\activate`.

## Build R2RML-F once

R2RML-F is included as attributed, vendored third-party source. Its generated
`target/` directory is intentionally excluded from Git.

```bash
cd Tools/r2rml-master
mvn clean package
cd ../..
```

The build runs the upstream test suite and creates
`Tools/r2rml-master/target/r2rml-fat.jar`.

## Run the pipeline

The included CC BY 4.0 paper can be used as a reproducible example:

```bash
python3 src/extractor.py \
  --input "data/Inputs/A_Systematic_Survey_of_Data_Value_Models_Metrics_A.pdf" \
  --source "IEEE" \
  --output "data/Outputs/metrics.csv"
```

The extractor writes the CSV and updates `config.properties` for the selected
source. Generate the RDF/Turtle representation with:

```bash
java -jar "Tools/r2rml-master/target/r2rml-fat.jar" config.properties
```

The generated file is written to the `output/` path recorded in
`config.properties`.

## Evaluation

The evaluation compared extracted metrics with the 123-record gold standard.
Match classification and review were performed manually by the author.
`Evaluation/match_analysis.py` supports that review by producing a row-by-row
comparison containing label and definition similarity scores plus dimension
and formula agreement.

```bash
python3 Evaluation/match_analysis.py
```

The evaluated extraction outputs contain 12 ETSI metrics, 69 Zaveri metrics,
38 IEEE/data-value survey metrics, and metrics from the Radulovic quality
model. See the project report for the methodology, results, and limitations.

## Tests

Run the Python tests from the repository root:

```bash
python3 -m pytest tests/ -v
```

Build and test the vendored R2RML-F processor separately:

```bash
cd Tools/r2rml-master
mvn clean package
```

## Public repository notes

This is the public portfolio edition of the submitted UCD Final Year Project.
The core implementation, mappings, derived evaluation data, and generated RDF
outputs are retained. Personal identifiers, non-redistributable source
documents, generated caches, and an unused Oracle JDBC binary are excluded.

Third-party attribution and licensing information is recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
