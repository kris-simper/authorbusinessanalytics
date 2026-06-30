# 📝 Author Business Analytics — Coding Standards

## Version 1.0 | June 29, 2026

---

## 1. DOCSTRING CONVENTIONS

### Module-Level Docstrings (Required)
Every `.py` file must begin with a triple-quoted description:

```
"""
Audiobooks Unleashed royalty loader for wide-distribution audiobook sales.

Parses "Royalty Detail" PDF statements using pdfplumber for text extraction.
Each PDF contains multiple book sections (identified by title + ISBN headers),
with data rows containing: accrued date, distributor source, quantity, location,
and a money flow chain (Gross → Received → Fee → Payable → Percent → Royalty).

ISBNs from section headers are matched against the book catalog for series/work
enrichment. Currency is parsed from the PDF header and converted to USD.
"""
```

#### Structure:

- Line 1: One-sentence summary of module purpose
- Lines 2–N: Detailed explanation of inputs, outputs, transformations
- Last line before imports: Optional technical notes or caveats

### Function Docstrings (Required)

All public functions need docstrings describing arguments, returns, and exceptions:

```
def load_aubooks_data(filepath, catalog=None):
	"""
	Load Audiobooks Unleashed royalty detail PDF.

	Parses line-by-line text extraction with regex pattern matching.
	Tracks book sections via ISBN headers to attribute each row to
	the correct title.

	Args:
		filepath: Path to the AU Books PDF
		catalog: BookCatalog instance for ISBN-based enrichment

	Returns:
		DataFrame with parsed royalty data ready for database ingestion

	Raises:
		FileNotFoundError: If PDF cannot be read
		ValueError: If no data rows parsed
	"""
```

#### Required Fields:

- Args: — All parameters with brief description
- Returns: — What the function outputs (omit if None)
- Raises: — Any exceptions that may propagate (optional for internal helpers)

### Private Helper Functions (Optional)

Functions prefixed with _ may omit full docstrings if self-explanatory:

```
def _parse_money(s):
	"""Clean and parse a monetary string."""  # ← One-liner sufficient
```

## 2. COMMENT STANDARDS

### Section Headers (Visual Dividers)

Use comment blocks to separate major logical sections:

```
# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================
```

### Inline Comments

Explain ***why***, not ***what***:

```
# BAD (explains the code itself):
tokens = tokens[:-1]  # Remove last token

# GOOD (explains the reason):
tokens = tokens[:-1]  # Drop trailing empty string from split()
```

### TODO/FIXME Markers

Flag incomplete work with context:

```
# TODO: Add Kobo Plus subscriber rate derivation logic (Q3 2026)
# FIXME: European decimal format fails on multi-thousand amounts
```

### Warning Labels for Edge Cases

Highlight non-obvious behaviors:

```
# WARNING: ACX legacy loader omits quantity columns — filled with NULL
```

## 3. NAMING CONVENTIONS
|Element|Convention|Example|Notes|
|-------|----------|-------|-----|
|Modules|snake_case|aubooks_loader.py|Underscore-separated filenames|
|Classes|PascalCase|BookCatalog| |
|Functions|snake_case|load_patreon_data()|Verbs for actions|
|Variables|snake_case|df_kenp, all_dfs|Prefix with source type (df_, conn_)|
|Constants|UPPER_SNAKE_CASE|DATABASE_PATH|Global module constants|
|Private funcs|underscore prefix|\_parse_money()|Internal helpers only|
|DataFrame vars|df_\* prefix|df_sales, df_filtered|Makes column-heavy ops readable|
|Database vars|conn/\* prefix|conn, cursor_db|Identifies SQLite connections|

## 4. IMPORT ORGANIZATION

Imports follow strict ordering within each file:

```
import re
import sqlite3
from pathlib import Path

import pandas as pd
import pdfplumber

from src.book_catalog import BookCatalog
from src.currency import to_usd
from src.schemas import ACX_NEW_FORMAT
```

### Rules:

1. Python standard library first (re, pathlib, sqlite3)
2. Third-party libraries next (pandas, pdfplumber)
3. Project-local modules last (from src.*)
4. Group logically; blank line between groups
5. Avoid wildcard imports (from X import *)

## 5. TYPE HINT POLICY

### Required When:

- Function signatures in public API modules (analyzer.py, loaders.py)
- Return types are non-obvious (DataFrames vs dicts vs None)
- Chained operations where inference breaks down

### Optional When:

- Simple primitive args/returns (str, int, bool)
- Private helper functions (_private_func())
- Temporary scripts or one-off debug tools

#### Example:

```
def to_usd(amount: float, currency_code: str, txn_date: date) -> float:
    """Convert amount to USD using ECB historical rates."""
```

## 6. ERROR HANDLING PATTERNS

### Specific Exception Types

Prefer specific catches over bare Exception:

```
try:
    cursor = conn.execute(query)
except sqlite3.OperationalError as e:
    print(f"[ERROR] Query failed: {e}")
    return None
```

***Exception***: When catching RateNotFoundError from CurrencyConverter, use except Exception because RateNotFoundError is not a subclass of ValueError — the broader catch ensures fallback logic executes. This is a documented and intentional deviation from the specificity rule.

### Fail-Fast Validation

Validate early, return gracefully:

```
if not db_path.exists():
    print(f"[ERROR] Database not found at {db_path}")
    print("Run `python run_pipeline.py` first.")
    return  # Don't crash hard
```

### Logging vs Printing

Current convention uses bracketed console output:

```
print("[INFO] Pipeline completed successfully")
print("[WARN] File skipped: missing date column")
print("[ERROR] Could not convert GBP to USD for 2026-05-01")
```

***Future upgrade path***: Replace with logging module when moving to production-grade deployment. See the Long-Term Development Plan Phase 0 for the planned migration.

## 7. DEPRECATION MARKERS

Files or functions being phased out must show explicit deprecation in two places:

### Warning Declaration

```
import warnings
warnings.warn(
    "validate_queries.py is deprecated. Dashboard handles validation automatically.",
    DeprecationWarning,
    stacklevel=2
)
```

### Module Docstring

```
"""
DEPRECATED: Query validation suite.

These tests verified database integrity during development. Now handled
automatically by cached dashboard queries (@st.cache_data(ttl=300)) which
fail gracefully on errors rather than crashing.

Kept for: Educational reference on SQL validation patterns and error handling.
"""
```

## 8. LOGICAL CODE STRUCTURE

### Single Responsibility Principle

Each function does one thing well:

```
# GOOD: Focused utility function
def _parse_money(s):
    """Parse monetary string to float."""
    ...
	
# AVOID: Monolithic loaders with 200 lines
def load_and_parse_and_enrich_and_convert(...):
    ...
```

### Early Return Pattern

Reduce nesting depth:

```
# GOOD: Guard clause
if not all_rows:
    print("[WARN] No data rows parsed")
    return pd.DataFrame()
# Main logic continues without indent

# AVOID: Deeply nested if-statements
if len(all_rows) > 0:
    if df is not None:
        ...
```

### Pipeline Step Annotation

Major pipeline stages in run_pipeline.py use banner-style headers:

```
print("\n" + "=" * 60)
print("STEP 2B: PROCESSING KENP PAGE READS")
print("=" * 60)
```

This keeps terminal output scannable when debugging long pipeline runs.

## 9. DOCUMENTATION FILE LOCATIONS

|Document|Location|Purpose|
|--------|--------|-------|
|This formatting guide|CODING_STANDARDS.md|Developer onboarding and conventions|
|Source format notes|source format notes.txt|Platform schema mappings and headers|
|Roadmap & priorities|README.md → Roadmap section|Feature backlog|
|Git commit conventions|CODING_STANDARDS.md → §12|Commit message standards|
|Change history|Future: CHANGELOG.md|Release notes|
|Contribution guidelines|Future: CONTRIBUTING.md|External developer instructions|

## 10. CODE REVIEW CHECKLIST

### Before committing new code, verify:

- Module has triple-quoted description at top
- Public functions have Arg/Return/Raise docstrings
- Imports are grouped by origin (stdlib → third-party → local)
- Section dividers mark major logical chunks
- Inline comments explain why, not what
- Naming follows snake_case / PascalCase conventions
- Error messages include actionable guidance ("Run X first")
- Deprecated code shows warnings.warn() marker
- No PII in committed code or data files
- New fact tables follow Kimball principles (see §13)
- Currency conversion uses to_usd() with fallback logic
- Print statements use [INFO] / [WARN] / [ERROR] prefixes
- New platform loaders handle empty DataFrames gracefully

## 11. REFERENCE FILES

### Gold Standard Examples:

- ✅ src/aubooks_loader.py — Module docstring, section dividers, utility functions, catalog enrichment pattern
- ✅ src/kenp_loader.py — Multi-step pipeline with numbered section headers, formula documentation, sample logging
- ✅ run_pipeline.py — Pipeline orchestration with step banners, error handling, results summary
- ✅ src/analyzer.py — Schema definitions with inline SQL comments, init functions per table
- ✅ validate_queries.py — Deprecation pattern with both warning and docstring

### Patterns to Avoid:

- ❌ Hardcoded file paths (use Path(__file__).parent relative paths)
- ❌ Bare except: with no exception type
- ❌ Silent failures (always log or print on caught exceptions)
- ❌ Functions over 80 lines (extract helpers)
- ❌ Importing inside functions (move to module level, except lazy imports to avoid circular deps)

## 12. GIT COMMIT MESSAGE STANDARDS

This project follows ***Conventional Commits***. Commit messages must conform to this specification.

### Message Structure

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

|Type|When to Use|Example|
|----|-----------|-------|
|feat|New feature, loader, or dashboard page|feat: Add Draft2Digital CSV loader|
|fix|Bug fix|fix: Correct ISBN hyphen normalization in catalog|
|refactor|Code restructuring, no behavior change|refactor: Extract _parse_money into shared utility|
|docs|Documentation changes|docs: Update README with 5-platform data coverage|
|chore|Maintenance, deps, config|chore: Remove deprecated matplotlib from requirements.txt|
|test|Adding or modifying tests|test: Add currency conversion edge case tests|
|deprecate|Marking code as deprecated|deprecate: Retire src/visualizer.py|

### Rules

1. Subject line — Imperative mood ("Add", not "Added" or "Adding"), lowercase, no period, max 72 characters
2. Scope (optional) — Module or platform affected: (acx), (kdp), (kenp), (dashboard), (catalog), (schema)
3. Body (optional) — Wrap at 72 chars, explain why not what, blank line after subject
4. Footer (optional) — Reference issues or note breaking changes with BREAKING CHANGE:
5. One logical change per commit — Don't mix a new loader with a dashboard refactor

### Examples From This Project's History

```
feat: Complete 6-chart dashboard + advanced SQL showcase library

feat(kdp): Add KENP backward calculation and equivalent copies

fix(catalog): Resolve ISBN hyphen mismatch causing paperback misclassification

chore: Remove deprecated matplotlib and numpy from requirements.txt

deprecate: Archive src/visualizer.py — superseded by Streamlit dashboard
```

### Multi-File Commits

When a commit touches multiple areas, lead with the most significant change:

```
feat: Add Patreon, WooCommerce, and AU Books loaders

Three new platform loaders with dedicated fact tables. Includes
fuzzy matcher fix for WooCommerce product names, DB reset on
pipeline run, and README update reflecting 5-platform coverage.
```

## 13. DATA WAREHOUSE DESIGN STANDARD — KIMBALL DIMENSIONAL MODELING

This project adheres to Kimball dimensional modeling principles. All schema decisions must be evaluated against these rules. This is non-negotiable — mixing grains or snowflaking dimensions introduces silent data corruption that surfaces as incorrect analytics.

### Core Principles

1. Star schema — Fact tables at center, dimension tables radiating outward. No snowflaking (dimension tables do not reference other dimensions).

2. One fact table per business process grain — Different grains never share a table. This is why we have sales_fact, kenp_reads, fact_patreon_earnings, fact_woo_sales, and fact_aubooks_sales as separate tables rather than one mega-table with nullable columns.

3. Grain declaration — Every fact table has an explicitly defined grain:
    - sales_fact → one row per transaction (platform × book × region × date)
    - kenp_reads → one row per book × marketplace × date (page-read event)
    - fact_patreon_earnings → one row per month (aggregate subscription income)
    - fact_woo_sales → one row per product × date range
    - fact_aubooks_sales → one row per distributor × book × date

4. Conformed dimensions — dim_books is shared across all fact tables. The same book_identifier key means the same book everywhere. No platform-specific dimension tables.

5. Surrogate keys — Each fact table has an autoincrement id column as surrogate primary key. Natural keys (book_identifier, sale_date) are indexed but not used as PKs to handle duplicates gracefully during staging.

6. No null fact measures — Use DEFAULT 0 on numeric columns. A missing sale is 0.0, not NULL. This prevents SUM() from silently dropping rows.

7. Dual currency storage — Raw source currency (royalty_amount) and normalized USD (royalty_amount_usd) are both stored. This provides auditability and allows re-derivation if conversion methodology changes.

8. Indexes on all foreign keys and common filter columns — Date, series, platform, region, ISBN, category (12 total). Added at table creation time, not retroactively.

9. Database reset on each pipeline run — Prevents duplicate accumulation. The pipeline deletes the DB file at Step 0 before any ingestion occurs.

## When Adding a New Platform

Before writing any loader code, answer these questions:

1. What is the grain? — One row equals what real-world business event?
2. Does it share a grain with an existing fact table? — If yes, consider appending to that table. If no, create a new fact table.
3. What foreign keys link to dim_books? — Which identifier does this platform provide (ASIN, ISBN, product code)?
4. What measures does it carry? — Revenue, units, pages, fees? Define column types and defaults.
5. Does it need currency conversion? — If non-USD, follow the to_usd() pattern with 30-day backward walk.
6. What indexes are needed? — At minimum, index the date column and the book_identifier/foreign key.

### Anti-Patterns to Reject

- ❌ Single unified fact table with platform-specific nullable columns — causes SUM() to silently exclude rows and makes grain ambiguous
- ❌ Embedding dimension attributes (title, series) directly in fact tables without a dimension table — denormalizes data, prevents updates to book metadata without re-ingestion
- ❌ Using natural keys as primary keys — breaks on duplicate records during re-ingestion or batch overlap
- ❌ Mixing grains in one table (e.g., daily transactions and monthly summaries together) — makes COUNT(*) and AVG() meaningless
- ❌ Snowflaking dimensions (a dimension table that references another dimension table) — adds JOIN overhead for no benefit at this scale

---

### Revision History
|Date|Version|Changes|Author|
|----|-------|-------|------|
|2026-06-29|1.0|Initial draft — all 13 sections|Team|

Last Updated: June 29, 2026 
Next Review: Before Draft2Digital loader commit