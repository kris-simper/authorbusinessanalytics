# Author Business Analytics

A data engineering pipeline that ingests, normalizes, and analyzes royalty revenue across multiple publishing platforms (ACX, Amazon KDP) into a unified analytics warehouse with USD-normalized currency and backward-derived Kindle Unlimited (KENP) royalty allocation.

## Problem Statement

Independent authors receive monthly royalty reports from multiple sales platforms in inconsistent formats — varying schemas, incompatible identifiers, multi-currency transactions, missing transaction dates, and embedded PII (personally identifiable information). This pipeline solves that by:

- **Unifying** disparate export formats into a single canonical schema
- **Normalizing** multi-currency revenue to USD using historical ECB exchange rates
- **Deriving** Kindle Unlimited (KENP) royalties via backward calculation from Summary and Combined Sales tabs
- **Enriching** transaction records with a custom book catalog (series, format, edition)
- **Persisting** clean data into a relational SQLite warehouse with dual fact tables
- **Analyzing** revenue trends via SQL queries and visualizations

## Architecture

**Raw Excel/CSV Exports → Normalization → Currency Conversion → Catalog Enrichment → SQLite Warehouse → Visualizations**

- ACX New (.xlsx) → Schema Mapping → Catalog Enrichment → SQLite
- ACX Legacy (.xls) → Cross-tab Unpivot → Catalog Enrichment → SQLite
- Amazon KDP Combined Sales (.xlsx) → Schema Mapping → Currency Conversion → Catalog Enrichment → SQLite
- Amazon KDP KENP (.xlsx) → Backward Rate Derivation → USD Conversion → Equivalent Copies → SQLite

### Pipeline Stages

1. **Ingestion** — Platform-specific loaders parse Excel files with openpyxl and pandas
2. **Normalization** — Dictionary-based column mapping unifies disparate schemas to snake_case
3. **Privacy** — PII columns (author names, royalty earners) stripped before any processing
4. **Date Extraction** — Reporting month parsed from filenames via regex (ACX reports lack date columns)
5. **Currency Conversion** — Non-USD royalty amounts converted using historical ECB reference rates (nearest available business day for weekends/holidays)
6. **KENP Royalty Derivation** — Kindle Unlimited page reads monetized via backward calculation from Summary tab residuals
7. **Catalog Enrichment** — Hybrid matching strategy links transactions to book metadata (including KENP page counts)
8. **Persistence** — Filtered DataFrames loaded into SQLite star schema with dual fact tables and indexes
9. **Analytics** — 8 SQL query patterns covering time series, rankings, regional analysis, KENP engagement, and format breakdowns
10. **Visualization** — 8 publication-quality charts generated from the warehouse

## Key Technical Decisions

### Hybrid Entity Resolution

Sales records arrive with different identifier types across platforms — ASINs for Kindle ebooks, ISBN-13s for paperbacks/hardcovers, and internal ACX product IDs for audiobooks. The pipeline resolves these through a two-stage approach:

- **Stage 1 (Deterministic):** Exact ID match against a normalized catalog of ASINs, ISBN-10s, ISBN-13s, and internal IDs. Identifiers are normalized (hyphens stripped, float coercion handled, whitespace trimmed) to ensure cross-platform compatibility.
- **Stage 2 (Heuristic Fallback):** Fuzzy title matching via `difflib.SequenceMatcher` with regex preprocessing (strips parentheticals, normalizes `&`/`and`) — only runs on unmatched rows

**Result:** 100% match rate across 9,416 records (5,891 sales + 3,525 KENP reads) spanning 3 source formats.

### Identifier Normalization

A critical data quality challenge: catalog ISBNs are stored with hyphens (`978-1-7324611-2-3`) while KDP exports them as plain numbers (`9781732461123`). Additionally, Excel can coerce numeric ISBNs to floats (`9781732461123.0`). The pipeline normalizes all identifiers through a unified function that strips hyphens, removes float artifacts, handles Excel apostrophe prefixes, and uppercases for consistent comparison.

### Multi-Currency Normalization

KDP sales span 9 currencies (USD, EUR, GBP, CAD, AUD, BRL, MXN, INR, JPY). Raw royalty amounts are preserved alongside USD-converted values using the `CurrencyConverter` library with bundled European Central Bank historical reference rates. The converter walks backward up to 30 days to handle weekends, holidays, and recently-unpublished rates.

### KENP Backward Calculation

Amazon's KDP reports do not include per-book KENP (Kindle Unlimited page-read) royalty amounts. The pipeline derives these through a four-step backward calculation:

1. **Isolate residual:** For each month and currency, subtract Combined Sales royalties from the Summary tab's total royalties. The difference is the KENP royalty pool.
2. **Aggregate pages:** Sum KENP page reads by month and currency from the KENP tab.
3. **Derive effective rate:** Divide residual royalty by total pages to get the actual per-page rate Amazon applied.
4. **Allocate to books:** Multiply each book's page count by the effective rate to get per-title royalty in native currency, then convert to USD.

This approach derives the *actual* rates Amazon applied rather than approximating with external crowd-sourced data. The residual always reconciles exactly to Amazon's Summary tab. A validation script confirmed that Combined Sales never exceeds Summary totals across 689 month/currency comparisons.

### KENP Equivalent Copies

Each ebook enrolled in KDP Select has a fixed KENP page count (set by Amazon at publication). The pipeline uses these to calculate "equivalent copies" — total pages read divided by the book's page count — enabling apples-to-apples volume comparison between Kindle Unlimited engagement and direct ebook sales. For books where Amazon's official KENP page count was unavailable, the pipeline estimates it from word count using a derived ratio of ~194 words per KENP page (calibrated from six books with known values, R²=0.99).

### Privacy-First Design

- PII stripped immediately after file load, before any processing or export
- Raw data files excluded from version control via `.gitignore`
- No customer-level data enters the pipeline — all records aggregate to book/title level

### Batch Processing

- Scans directories for all `.xlsx`/`.xls` files automatically
- Per-file error isolation (one corrupt file doesn't kill the batch)
- Single `pd.concat` at end for memory-efficient accumulation
- Shared catalog instance across all files (loaded once, reused 63x)

### Dimensional Modeling

- **Star schema:** `sales_fact` (transactions) + `kenp_reads` (page reads) + `dim_books` (book metadata)
- **7 indexes:** date, series, platform, region (sales) + date, series, region (KENP)
- **Dual currency storage:** Both raw source amounts and USD-normalized amounts for auditability
- **Separate fact tables:** Sales and KENP reads have fundamentally different grains (per-sale vs. per-read), so they're stored in separate tables to avoid nullable column anti-patterns

## Data Coverage

| Metric | Value |
|--------|-------|
| Source platforms | ACX (audiobooks), Amazon KDP (ebooks, paperbacks, KENP) |
| Source formats | 2 (ACX new .xlsx, ACX legacy .xls, KDP .xlsx) |
| Files processed | 63 monthly reports |
| Date range | June 2018 – June 2026 |
| Sales records ingested | 5,891 transactions |
| KENP records ingested | 3,525 page-read events |
| Total records | 9,416 |
| Currencies handled | 9 (USD, EUR, GBP, CAD, AUD, BRL, MXN, INR, JPY) |
| Catalog editions | 45 across 6 formats |
| Catalog identifiers indexed | 85 (ASINs, ISBN-10s, ISBN-13s, internal IDs) |
| KENP rates derived | 663 effective rates across 9 currencies |
| Book formats tracked | ebook, paperback, hardcover, audiobook, special editions |
| Database tables | 3 (sales_fact + kenp_reads + dim_books) |
| SQL indexes | 7 |
| Visualizations | 8 charts |

## Tech Stack

- **Python 3.12** — Core language
- **pandas** — Data manipulation and transformation
- **openpyxl** — Excel file parsing (.xlsx, read-only mode for performance)
- **xlrd** — Legacy Excel file parsing (.xls)
- **sqlite3** — Embedded analytics database (standard library)
- **matplotlib** — Chart generation
- **numpy** — Numerical operations for visualizations
- **CurrencyConverter** — Historical ECB exchange rate conversion
- **difflib** — Fuzzy string matching (standard library)

## Project Structure

**Core Modules (`src/`)**
- `schemas.py` — Column mapping dictionaries and PII config
- `book_catalog.py` — Book metadata crosswalk with identifier normalization and hybrid matching
- `loaders.py` — Platform-specific ingestion (ACX new, ACX legacy, Amazon KDP)
- `kenp_loader.py` — KENP page-read ingestion with backward rate derivation and equivalent copies calculation
- `analyzer.py` — SQLite database layer, schema definition (3 tables), and analytical queries
- `currency.py` — USD currency conversion using historical ECB reference rates
- `visualizer.py` — Matplotlib chart generation (8 charts)

**Data**
- `data/catalog_products.csv` — Master book catalog (series, formats, identifiers, KENP page counts)
- `data/raw/acx-new/` — ACX .xlsx reports (Apr 2024 – Apr 2026)
- `data/raw/acx-old/` — ACX legacy .xls reports (Mar 2021 – Mar 2024)
- `data/raw/amazon-kdp/` — Amazon KDP .xlsx reports (Combined Sales, Summary, KENP tabs)

**Outputs**
- `results/figures/` — Generated PNG charts

**Root Files**
- `sql_queries.sql` — Showcase analytical SQL queries (YoY, rankings, regional)
- `run_pipeline.py` — End-to-end pipeline entry point
- `validate_queries.py` — SQL validation test suite
- `requirements.txt` — Python dependencies
- `.gitignore` — Excludes raw data, DBs, caches

## Getting Started

### Prerequisites

    pip install -r requirements.txt

### Running the Pipeline

    # 1. Place royalty exports in their respective data/raw/ subdirectories:
    #    - data/raw/acx-new/     (ACX .xlsx files)
    #    - data/raw/acx-old/     (ACX legacy .xls files)
    #    - data/raw/amazon-kdp/  (KDP .xlsx files with Combined Sales, Summary, KENP tabs)

    # 2. Run the full pipeline (ingestion → currency conversion → KENP derivation → enrichment → SQLite)
    python run_pipeline.py

    # 3. Validate SQL queries against the database
    python validate_queries.py

    # 4. Generate visualizations
    python -m src.visualizer

    # 5. View charts in results/figures/

### Viewing Results

Charts are saved as PNGs in `results/figures/`:

- `monthly_revenue.png` — Monthly royalties (USD) and units sold over time
- `series_performance.png` — Revenue by book series
- `regional_distribution.png` — Geographic revenue split
- `top_titles.png` — Top 10 titles by revenue
- `platform_comparison.png` — Stacked bar chart of monthly revenue by source platform
- `format_breakdown.png` — Dual-panel: revenue share (pie) + units sold (bar) by edition format
- `marketplace_ranking.png` — Triple-panel: top markets by revenue, volume, and avg transaction value
- `kenp_analysis.png` — Dual-panel: direct ebook copies vs KENP equivalent copies (stacked bar) + KENP pages read with derived revenue (bar + line)

## Roadmap

### Completed
- [x] ACX audiobook loader (new format, post-April 2024)
- [x] ACX audiobook loader (legacy format, pre-April 2024, cross-tab unpivot)
- [x] Amazon KDP loader (Combined Sales sheet, multi-format)
- [x] Multi-currency normalization to USD (9 currencies via ECB rates)
- [x] Identifier normalization (ISBN hyphens, float coercion, cross-platform matching)
- [x] KENP backward rate derivation (actual Amazon rates, not approximations)
- [x] KENP equivalent copies calculation (apples-to-apples comparison vs direct sales)
- [x] Expanded visualizations (4 → 8 charts)
- [x] Privacy-first PII stripping

### Planned
- [ ] KOLL (Kindle Owners' Lending Library) borrow tracking (deprecated ~2018, relevant for multi-author rollout)
- [ ] Amazon KDP Orders Processed loader (daily order-level detail)
- [ ] Draft2Digital loader (CSV format)
- [ ] Barnes & Noble Press loader
- [ ] pytest unit tests
- [ ] GitHub Actions CI/CD
- [ ] PostgreSQL migration + Docker
- [ ] Streamlit web dashboard