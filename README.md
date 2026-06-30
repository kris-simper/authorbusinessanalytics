# Author Business Analytics

A data engineering pipeline that ingests, normalizes, and analyzes royalty revenue across ten publishing and distribution platforms (ACX, Amazon KDP, Patreon, WooCommerce, Audiobooks Unleashed, Draft2Digital, Barnes & Noble Press, Kobo Store, Kobo Plus, IngramSpark) into a unified analytics warehouse with USD-normalized currency, backward-derived Kindle Unlimited (KENP) royalty allocation, and multi-format catalog enrichment.

## Problem Statement

Independent authors receive monthly royalty reports from multiple sales platforms in inconsistent formats — varying schemas, incompatible identifiers, multi-currency transactions, missing transaction dates, PDF-formatted statements, and embedded PII (personally identifiable information). This pipeline solves that by:

- **Unifying** disparate export formats (Excel .xlsx/.xls, CSV, PDF) into a single canonical schema
- **Normalizing** multi-currency revenue to USD using historical ECB exchange rates
- **Deriving** Kindle Unlimited (KENP) royalties via backward calculation from Summary and Combined Sales tabs
- **Parsing** PDF royalty statements from wide-distribution audiobook platforms
- **Enriching** transaction records with a custom book catalog (series, format, edition, KENP page counts)
- **Persisting** clean data into a relational SQLite warehouse with ten fact tables
- **Analyzing** revenue trends via SQL queries and visualizations

## Architecture

**Raw Excel/CSV/PDF Exports → Normalization → Currency Conversion → Catalog Enrichment → SQLite Warehouse → Visualizations**

- ACX New (.xlsx) → Schema Mapping → Catalog Enrichment → SQLite
- ACX Legacy (.xls) → Cross-tab Unpivot → Catalog Enrichment → SQLite
- Amazon KDP Combined Sales (.xlsx) → Schema Mapping → Currency Conversion → Catalog Enrichment → SQLite
- Amazon KDP KENP (.xlsx) → Backward Rate Derivation → USD Conversion → Equivalent Copies → SQLite
- Patreon (.csv) → Column Mapping → Numeric Normalization → SQLite
- WooCommerce (.csv) → Filename Date Parsing → Substring + Fuzzy Title Matching → SQLite
- Audiobooks Unleashed (.pdf) → pdfplumber Text Extraction → Multi-Section Parsing → ISBN/ASIN Matching → SQLite
- Draft2Digital (.csv) → Distributor-Level Aggregation → Catalog Enrichment → SQLite
- Barnes & Noble Press (.csv) → Metadata Header Skipping → Formula Wrapper Cleaning → ISBN Matching → SQLite
- Kobo Store (.xlsx) → Sheet Selection → Whitespace Trimming → eISBN Matching → SQLite
- Kobo Plus (.xlsx) → Subscription Read Grain → eISBN Matching → SQLite
- IngramSpark (.xls) → Tab-Delimited Detection → MTD Column Filtering → Period Name Parsing → SQLite

### Pipeline Stages

1. **Ingestion** — Platform-specific loaders parse Excel files with openpyxl/xlrd, CSVs with pandas, and PDFs with pdfplumber
2. **Normalization** — Dictionary-based column mapping unifies disparate schemas to snake_case
3. **Privacy** — PII columns (author names, royalty earners) stripped before any processing
4. **Date Extraction** — From columns (KDP, Patreon), filenames (WooCommerce), PDF text (AU Books), report periods (ACX, IngramSpark), or CSV date fields (D2D, B&N)
5. **Currency Conversion** — Non-USD royalty amounts converted using historical ECB reference rates (nearest available business day for weekends/holidays)
6. **KENP Royalty Derivation** — Kindle Unlimited page reads monetized via backward calculation from Summary tab residuals
7. **Catalog Enrichment** — Multi-strategy matching links transactions to book metadata:
   - Stage 1: Deterministic identifier match (ASIN, ISBN-10, ISBN-13, ACX product codes, eISBN, BN ID)
   - Stage 2a: Substring containment (WooCommerce product names containing catalog titles)
   - Stage 2b: Fuzzy title matching via `difflib.SequenceMatcher` with regex preprocessing
8. **Persistence** — Filtered DataFrames loaded into SQLite star schema with ten fact tables and indexes
9. **Analytics** — Interactive Streamlit dashboard with Plotly visualizations covering time series, rankings, regional analysis, KENP engagement, distributor breakdowns, and YoY growth

## Key Technical Decisions

### Hybrid Entity Resolution

Sales records arrive with different identifier types across platforms — ASINs for Kindle ebooks, ISBN-13s for paperbacks/hardcovers, eISBNs for Kobo, and internal ACX product IDs for audiobooks. The pipeline resolves these through a multi-stage approach:

- **Stage 1 (Deterministic):** Exact ID match against a normalized catalog of ASINs, ISBN-10s, ISBN-13s, and internal IDs. Identifiers are normalized (hyphens stripped, float coercion handled, whitespace trimmed) to ensure cross-platform compatibility.
- **Stage 2 (Heuristic Fallback):** Fuzzy title matching via `difflib.SequenceMatcher` with regex preprocessing (strips parentheticals, normalizes `&`/`and`) — only runs on unmatched rows
- **Stage 2a (Substring Containment):** For WooCommerce products with no SKUs, checks if any catalog display title appears as a substring within the product name. Catches variants like "Carmilla & Laura Deluxe Edition Hardcover" → "Carmilla and Laura".
- **Stage 2b (Fuzzy Fallback):** Only runs on unmatched rows after Stage 2a fails.

**Result:** 100% match rate across all identifier-bearing records. WooCommerce achieves 69% match (remainder is legitimately non-book merchandise).

### Identifier Normalization

A critical data quality challenge: catalog ISBNs are stored with hyphens (`978-1-7324611-2-3`) while KDP exports them as plain numbers (`9781732461123`). Additionally, Excel can coerce numeric ISBNs to floats (`9781732461123.0`). The pipeline normalizes all identifiers through a unified function that strips hyphens, removes float artifacts, handles Excel apostrophe prefixes, and uppercases for consistent comparison.

### Multi-Currency Normalization

KDP and IngramSpark sales span 9+ currencies (USD, EUR, GBP, CAD, AUD, BRL, MXN, INR, JPY). Raw royalty amounts are preserved alongside USD-converted values using the `CurrencyConverter` library with bundled European Central Bank historical reference rates. The converter walks backward up to 30 days to handle weekends, holidays, and recently-unpublished rates.

### KENP Backward Calculation

Amazon's KDP reports do not include per-book KENP (Kindle Unlimited page-read) royalty amounts. The pipeline derives these through a four-step backward calculation:

1. **Isolate residual:** For each month and currency, subtract Combined Sales royalties from the Summary tab's total royalties. The difference is the KENP royalty pool.
2. **Aggregate pages:** Sum KENP page reads by month and currency from the KENP tab.
3. **Derive effective rate:** Divide residual royalty by total pages to get the actual per-page rate Amazon applied.
4. **Allocate to books:** Multiply each book's page count by the effective rate to get per-title royalty in native currency, then convert to USD.

This approach derives the *actual* rates Amazon applied rather than approximating with external crowd-sourced data. The residual always reconciles exactly to Amazon's Summary tab. A validation script confirmed that Combined Sales never exceeds Summary totals across 689 month/currency comparisons.

### KENP Equivalent Copies

Each ebook enrolled in KDP Select has a fixed KENP page count (set by Amazon at publication). The pipeline uses these to calculate "equivalent copies" — total pages read divided by the book's page count — enabling apples-to-apples volume comparison between Kindle Unlimited engagement and direct ebook sales. For books where Amazon's official KENP page count was unavailable, the pipeline estimates it from word count using a derived ratio of ~194 words per KENP page (calibrated from six books with known values, R²=0.99).

### Platform-Specific Parsing Challenges

Each platform presents unique data quality challenges that the pipeline handles:

- **Barnes & Noble Press:** CSV files prepend 5 metadata header rows, wrap values in Excel formula syntax (`="value"`), and append trailing blank rows. The loader uses `skiprows=5`, iterative quote/formula stripping, and null date filtering.
- **IngramSpark:** Files are tab-delimited text disguised as `.xls`. The loader auto-detects format with 5 fallback read methods, reduces 80+ raw columns to ~45 MTD-only columns (YTD dropped to prevent double-counting), and parses custom period names like "MAY-26" with 2-digit year correction.
- **Kobo:** Excel column headers have leading/trailing whitespace. The loader applies `df.columns.str.strip()` after read.
- **Draft2Digital:** Uses `End Date` as sale date, `Ebook ISBN` as book identifier, and skips D2D's own USD estimate in favor of pipeline ECB conversion.

### Privacy-First Design

- PII stripped immediately after file load, before any processing or export
- Raw data files excluded from version control via `.gitignore`
- No customer-level data enters the pipeline — all records aggregate to book/title level

### Batch Processing

- Scans directories for all `.xlsx`/`.xls`/`.csv`/`.pdf` files automatically
- Per-file error isolation (one corrupt file doesn't kill the batch)
- Single `pd.concat` at end for memory-efficient accumulation
- Shared catalog instance across all files (loaded once, reused across all platforms)

### Dimensional Modeling

- **Star schema:** Ten fact tables + `dim_books` dimension table
- **Fact tables:** `sales_fact`, `kenp_reads`, `fact_patreon_earnings`, `fact_woo_sales`, `fact_aubooks_sales`, `fact_d2d_sales`, `fact_bnl_sales`, `fact_kobo_sales`, `fact_kobo_plus_reads`, `fact_ingram_sales`
- **Indexes:** Date, series, platform, region, ISBN, category
- **Dual currency storage:** Both raw source amounts and USD-normalized amounts for auditability
- **Database reset:** Fresh database on each pipeline run prevents duplicate accumulation

## Data Coverage

| Metric | Value |
|--------|-------|
| Source platforms | ACX, Amazon KDP, Patreon, WooCommerce, Audiobooks Unleashed, Draft2Digital, Barnes & Noble Press, Kobo Store, Kobo Plus, IngramSpark |
| Source formats | 4 (Excel .xlsx, Excel .xls, CSV, PDF) |
| Files processed | 100+ monthly reports across all platforms |
| Date range | June 2018 – June 2026 |
| Total records | 11,777+ across 10 fact tables |
| Currencies handled | 9+ (USD, EUR, GBP, CAD, AUD, BRL, MXN, INR, JPY) |
| Catalog editions | 45+ across 6+ formats |
| Catalog identifiers indexed | 85+ (ASINs, ISBN-10s, ISBN-13s, ACX codes, other IDs) |
| KENP rates derived | 663 effective rates across 9 currencies |
| Book formats tracked | ebook, paperback, hardcover, audiobook, deluxe hardcover, deluxe paperback, special editions |
| AU Books distributors | 25+ (ACX, BookBeat, Storytel, OverDrive, Spotify, Scribd, Kobo, etc.) |
| Database tables | 10 fact tables + 1 dimension table |

## Tech Stack

- **Python 3.12** — Core language
- **pandas** — Data manipulation and transformation
- **openpyxl** — Excel file parsing (.xlsx, read-only mode for performance)
- **xlrd** — Legacy Excel file parsing (.xls)
- **sqlite3** — Embedded analytics database (standard library)
- **Streamlit** — Interactive web dashboard framework
- **Plotly** — Interactive charting and data visualization
- **pdfplumber** — PDF text extraction (Audiobooks Unleashed statements)
- **CurrencyConverter** — Historical ECB exchange rate conversion
- **difflib** — Fuzzy string matching (standard library)

## Project Structure

**Core Modules (`src/`)**
- `schemas.py` — Column mapping dictionaries and PII config
- `book_catalog.py` — Book metadata crosswalk with identifier normalization and hybrid matching
- `amazon_loader.py` — Amazon platform ingestion (ACX new, ACX legacy, KDP Combined Sales)
- `kenp_loader.py` — KENP page-read ingestion with backward rate derivation and equivalent copies calculation
- `patreon_loader.py` — Monthly earnings aggregation with fee breakdowns
- `woo_loader.py` — Product-level sales with filename date parsing and title-based enrichment
- `aubooks_loader.py` — PDF statement parsing with multi-section book header detection
- `d2d_loader.py` — Draft2Digital distributor-level CSV with ISBN enrichment
- `bnl_loader.py` — Barnes & Noble Press CSV with metadata header and formula wrapper handling
- `kobo_loader.py` — Kobo Store sales + Kobo Plus subscription reads from .xlsx exports
- `ingram_loader.py` — IngramSpark tab-delimited reports with MTD column filtering
- `matching.py` — Shared fuzzy title matching utility (used by all loaders with title-based fallback)
- `analyzer.py` — SQLite database layer, schema definition (11 tables: 10 fact + 1 dimension), and data ingestion
- `currency.py` — USD currency conversion using historical ECB reference rates

**Data**
- `data/catalog_products.csv` — Master book catalog (series, formats, identifiers, KENP page counts)
- `data/raw/acx-new/` — ACX .xlsx reports (Apr 2024 – Apr 2026)
- `data/raw/acx-old/` — ACX legacy .xls reports (Mar 2021 – Mar 2024)
- `data/raw/amazon-kdp/` — Amazon KDP .xlsx reports (Combined Sales, Summary, KENP tabs)
- `data/raw/patreon/` — Patreon monthly earnings CSV exports
- `data/raw/woocommerce/` — WooCommerce product analytics CSV exports
- `data/raw/audiobooks-unleashed/` — AU Books "Royalty Detail" PDF statements
- `data/raw/draft2digital/` — Draft2Digital distributor sales CSV exports
- `data/raw/barnes-noble/` — Barnes & Noble Press royalty CSV exports
- `data/raw/kobo/` — Kobo Store and Kobo Plus .xlsx exports
- `data/raw/ingram-spark/` — IngramSpark royalty reports (tab-delimited .xls)

**Outputs**
- `streamlit_app.py` — Interactive Streamlit dashboard (Plotly charts, date filtering, cached queries)

**Root Files**
- `run_pipeline.py` — End-to-end pipeline entry point
- `streamlit_app.py` — Interactive web dashboard
- `requirements.txt` — Python dependencies
- `.gitignore` — Excludes raw data, DBs, caches
- `sql_queries.sql` — *(Deprecated)* Showcase analytical SQL queries — retained for educational reference
- `validate_queries.py` — *(Deprecated)* SQL validation suite — retained for educational reference

## Getting Started

### Prerequisites

    pip install -r requirements.txt

### Running the Pipeline

    # 1. Place royalty exports in their respective data/raw/ subdirectories:
    #    - data/raw/acx-new/                (ACX .xlsx files)
    #    - data/raw/acx-old/                (ACX legacy .xls files)
    #    - data/raw/amazon-kdp/             (KDP .xlsx files with Combined Sales, Summary, KENP tabs)
    #    - data/raw/patreon/                (Patreon monthly earnings CSV exports)
    #    - data/raw/woocommerce/            (WooCommerce product analytics CSV exports)
    #    - data/raw/audiobooks-unleashed/   (AU Books "Royalty Detail" PDF statements)
    #    - data/raw/draft2digital/           (Draft2Digital CSV exports)
    #    - data/raw/barnes-noble/            (B&N Press royalty CSV exports)
    #    - data/raw/kobo/                    (Kobo Store and Kobo Plus .xlsx exports)
    #    - data/raw/ingram-spark/            (IngramSpark tab-delimited .xls reports)

    # 2. Run the full pipeline (ingestion → currency conversion → KENP derivation → enrichment → SQLite)
    python run_pipeline.py

    # 3. Launch the interactive dashboard
    streamlit run streamlit_app.py

## SQL Techniques Demonstrated

The pipeline and dashboard leverage advanced analytical SQL patterns beyond basic CRUD operations. Showcase queries with explanations live in `sql_queries.sql`; validation tests in `validate_queries.py` confirm they execute against real data.

| Technique | Query | Application |
|-----------|-------|-------------|
| **Window functions** (`ROW_NUMBER()`, `SUM() OVER`, `AVG() OVER`) | Series Contribution Ranking, Pareto Analysis, Moving Averages, TTM Run Rate | Ranking within partitions, cumulative calculations, rolling averages |
| **Frame clause specification** (`ROWS BETWEEN x PRECEDING AND CURRENT ROW`) | 3-Month & 12-Month Moving Averages, Trailing 12-Month Run Rate | Sliding window aggregation for time-series smoothing |
| **`LAG()` window function** | Month-over-Month Growth Rate | Accessing prior row values for period-over-period differencing |
| **Recursive CTE** | Revenue Gap Detection | Generating continuous month sequences to find missing periods |
| **Correlated subquery** | Dominant Platform Per Month | Finding the maximum-revenue platform for each period without window functions |
| **Recursive CTE + LEFT JOIN** | Month Gap Detection | Synthetic time series generation joined against actual data to identify gaps |
| **Self-join** | Platform Diversification Analysis | Computing per-period market share and concentration risk |
| **Multi-CTE pipeline** (4+ nested CTEs) | Pareto, Diversification | Breaking complex analytical logic into composable, readable stages |
| **`UNION ALL`** (10-table aggregation) | All dashboard queries | Unifying fact tables with different schemas into a single result set |
| **`strftime()` date manipulation** | All time-series queries | SQLite-native date formatting for grouping by month/year |
| **`COALESCE()`** for null handling | Distribution, Pareto | Graceful substitution for missing dimension values |

### Where to find these patterns

- **`sql_queries.sql`** — 8 annotated showcase queries with explanatory headers (deprecated file, retained for educational reference)
- **`validate_queries.py`** — 18-test validation suite confirming all queries execute against the real database
- **`streamlit_app.py`** — Production queries embedded in the dashboard (CTEs, window functions, UNION ALL, date manipulation across 6 pages and 10+ charts)

## Roadmap

### Completed
- [x] ACX audiobook loader (new format, post-April 2024)
- [x] ACX audiobook loader (legacy format, pre-April 2024, cross-tab unpivot)
- [x] Amazon KDP loader (Combined Sales sheet, multi-format)
- [x] Multi-currency normalization to USD (9 currencies via ECB rates)
- [x] Identifier normalization (ISBN hyphens, float coercion, cross-platform matching)
- [x] KENP backward rate derivation (actual Amazon rates, not approximations)
- [x] KENP equivalent copies calculation (apples-to-apples comparison vs direct sales)
- [x] Privacy-first PII stripping
- [x] Patreon monthly earnings loader (aggregate subscription income)
- [x] WooCommerce product analytics loader (subtitle matching + fuzzy fallback)
- [x] Audiobooks Unleashed PDF parser (multi-section detail extraction)
- [x] Draft2Digital loader (CSV format, distributor-level grain)
- [x] Barnes & Noble Press loader (metadata header skipping, formula wrapper cleaning)
- [x] Kobo Store & Kobo Plus loaders (Excel parsing, subscription read grain)
- [x] IngramSpark loader (tab-delimited text detection, MTD column filtering)
- [x] Multi-platform integration (10 fact tables, 11,777+ total records)
- [x] Interactive Streamlit dashboard (Plotly charts, date filtering, cached queries, 6 pages)
- [x] AU Books distributor breakdown chart (revenue, units, avg transaction by distributor)
- [x] Streamlit web dashboard (real-time analytics interface, interactive filtering)
- [x] Revenue concentration / Pareto analysis (dual-axis combo chart, window functions)
- [x] Forecasting page (seasonality heatmap, moving averages, TTM run rate, diversification trend)
- [x] WooCommerce books vs. merchandise breakdown (stacked bar, category share)
- [x] Platform channel share over time (100% stacked bar)
- [x] dim_books dimension table population (star schema completion)
- [x] Advanced SQL showcase library (8 analytical patterns with validation suite)
- [x] Code review against CODING_STANDARDS.md (all modules reviewed, cleaned, and standardized)

### Near-Term Targets
- [ ] Square transactions (merchant payments, tip jar data)
- [ ] Redbubble shop sales (artist marketplace income)
- [ ] Kickstarter campaign funding (project-based revenue tracking)
- [ ] BN ID matching in book_catalog.py for B&N print edition enrichment
- [ ] Distributor name normalization across D2D and AU Books for combined dashboard charts

### Long-Term Exploration
- [ ] KOLL (Kindle Owners' Lending Library) borrow tracking (deprecated ~2018, relevant for multi-author rollout)
- [ ] Amazon KDP Orders Processed loader (daily order-level detail)
- [ ] Editorial editing work invoices (PayPal receipt parsing + service revenue categorization)
- [ ] Etsy store analytics (digital downloads, physical merch, custom commissions)
- [ ] Ko-fi memberships & tips (micro-tipping + recurring subscriptions)
- [ ] itch.io game/assets revenue (interactive media sales tracking)

### Infrastructure Improvements
- [ ] pytest unit tests (loader validation, currency conversion edge cases, schema integrity)
- [ ] GitHub Actions CI/CD (automated linting, test suite execution on PRs)
- [ ] PostgreSQL migration + Docker containerization (scalability beyond SQLite limits)
- [ ] API integration layer (replace manual file exports with automated API pulls for platforms that support them — Patreon, WooCommerce, Square, itch.io)
- [ ] Additional dashboard charts (cumulative revenue waterfall, cohort retention analysis, anomaly detection alerts)
- [ ] Streamlit dashboard enhancements (platform filter wiring, scheduled dashboard generation)
- [ ] Scheduled ETL runs (Airflow or cron-based automation for weekly/monthly refresh cycles)
- [ ] Cross-platform revenue forecasting models (predictive analytics using historical trends)


## Deprecated Files

The following files remain in the repository for educational reference but are no longer part of the active pipeline:

- **`src/visualizer.py`** — Static matplotlib PNG chart generation. Superseded by the Streamlit dashboard with interactive Plotly charts. Will be removed in v2.0.
- **`sql_queries.sql`** — Standalone SQL showcase queries (CTEs, UNION ALL, window functions, date manipulation). Superseded by embedded queries in the dashboard but retained to demonstrate raw SQL proficiency.
- **`validate_queries.py`** — Query validation suite used during development. Dashboard queries now fail gracefully with user-facing error messages.

To explore the data interactively: `streamlit run streamlit_app.py`