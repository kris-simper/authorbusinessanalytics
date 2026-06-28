# Author Business Analytics

A data engineering pipeline that ingests, normalizes, and analyzes royalty revenue across multiple publishing platforms (ACX, Amazon KDP, Draft2Digital, Barnes & Noble) into a unified analytics warehouse.

## Problem Statement

Independent authors receive monthly royalty reports from multiple sales platforms in inconsistent formats — varying schemas, incompatible identifiers, missing transaction dates, and embedded PII (personally identifiable information). This pipeline solves that by:

- **Unifying** disparate export formats into a single canonical schema
- **Enriching** transaction records with a custom book catalog (series, format, edition)
- **Persisting** clean data into a relational SQLite warehouse
- **Analyzing** revenue trends via SQL queries and visualizations

## Architecture

**Raw Excel/CSV Exports → Normalization Layer → Analytics Layer**

- ACX (.xlsx) → Schema Mapping → SQLite Warehouse (fact/dimension)
- KDP (.xlsx) → PII Removal → SQL Queries
- D2D (.csv) → Date Extraction → Visualizations
- B&N (.csv) → Catalog Enrichment

### Pipeline Stages

1. **Ingestion** — Platform-specific loaders parse Excel/CSV files with openpyxl and pandas
2. **Normalization** — Dictionary-based column mapping unifies disparate schemas to snake_case
3. **Privacy** — PII columns (author names, royalty earners) stripped before any processing
4. **Date Extraction** — Reporting month parsed from filenames via regex (ACX reports lack date columns)
5. **Catalog Enrichment** — Hybrid matching strategy links transactions to book metadata
6. **Persistence** — Filtered DataFrames loaded into SQLite fact/dimension tables with indexes
7. **Analytics** — 6 SQL query patterns covering time series, rankings, regional analysis, and YoY growth

## Key Technical Decisions

### Hybrid Matching Strategy

ACX reports export internal product IDs (`BK_ACX0_XXXXXX`) that don't match ASINs or ISBNs. The pipeline uses a two-stage enrichment approach:

- **Stage 1 (Deterministic):** Exact ID match against catalog `other_id` field — zero ambiguity
- **Stage 2 (Heuristic Fallback):** Fuzzy title matching via `difflib.SequenceMatcher` with regex preprocessing (strips parentheticals, normalizes `&`/`and`) — only runs on unmatched rows

**Result:** 100% match rate (291/291 records) with zero reliance on the fuzzy fallback for known titles.

### Privacy-First Design

- PII stripped immediately after file load, before any processing or export
- Raw data files excluded from version control via `.gitignore`
- No customer-level data enters the pipeline — all records aggregate to book/title level

### Batch Processing

- Scans directories for all `.xlsx` files automatically
- Per-file error isolation (one corrupt file doesn't kill the batch)
- Single `pd.concat` at end for memory-efficient accumulation
- Shared catalog instance across all files (loaded once, reused 24x)

## Data Coverage

| Metric | Value |
|--------|-------|
| Source platform | ACX Audiobooks |
| Files processed | 62 monthly reports |
| Date range | March 2021 - April 2026 |
| Records ingested | 529 transactions |
| Catalog match rate | 100% (529/529) |
| Database tables | 2 (sales_fact + dim_books) |
| SQL indexes | 4 (date, series, platform, region) |

## Tech Stack

- **Python 3.12** — Core language
- **pandas** — Data manipulation and transformation
- **openpyxl** — Excel file parsing (read-only mode for performance)
- **sqlite3** — Embedded analytics database (standard library)
- **matplotlib** — Chart generation
- **difflib** — Fuzzy string matching (standard library)

## Project Structure

**Core Modules (`src/`)**
- `schemas.py` — Column mapping dictionaries and PII config
- `book_catalog.py` — Book metadata crosswalk and hybrid matching
- `loaders.py` — Platform-specific ingestion (ACX, future: KDP, D2D)
- `analyzer.py` — SQLite database layer and analytical queries
- `visualizer.py` — Matplotlib chart generation

**Data**
- `data/catalog_products.csv` — Master book catalog (series, formats, identifiers)
- `data/raw/` — Raw platform exports (gitignored)

**Outputs**
- `results/figures/` — Generated PNG charts

**Root Files**
- `sql_queries.sql` — Showcase analytical SQL queries
- `test_loader.py` — End-to-end pipeline test harness
- `test_sql_queries.py` — SQL validation test suite
- `requirements.txt` — Python dependencies
- `.gitignore` — Excludes raw data, DBs, caches

## Getting Started

### Prerequisites

    pip install -r requirements.txt

### Running the Pipeline

    # 1. Place ACX royalty exports in data/raw/acx-new/
    # 2. Run the full pipeline (ingestion -> enrichment -> SQLite)
    python test_loader.py

    # 3. Validate SQL queries against the database
    python test_sql_queries.py

    # 4. Generate visualizations
    python -m src.visualizer

    # 5. View charts in results/figures/

### Viewing Results

Charts are saved as PNGs in `results/figures/`:

- `monthly_revenue.png` — Monthly royalties and units sold over time
- `series_performance.png` — Revenue by book series
- `regional_distribution.png` — Geographic revenue split
- `top_titles.png` — Top 10 titles by revenue

## Roadmap

- [x] ACX audiobook loader (new format, post-April 2024)
- [ ] Amazon KDP loader (multi-sheet: eBook + Paperback)
- [ ] Draft2Digital loader (CSV format)
- [ ] Barnes & Noble Press loader
- [ ] Legacy ACX format support (pre-April 2024)
- [ ] Automated anomaly detection for revenue spikes/drops
- [ ] Web dashboard (Flask/Streamlit)