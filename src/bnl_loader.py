"""
Barnes & Noble Press royalty loader for print and ebook sales.

Parses custom date-range CSV exports containing per-transaction sales data.
Each row represents one book-format-sale date transaction. Uses eBook ISBN
as primary identifier (falling back to BN ID as secondary reference).
Currency is preserved in raw form (royalty_amount in Payment Currency) and
converted to USD using historical ECB rates (to_usd()).

B&N CSV quirks handled:
- 5 metadata rows before the actual CSV header (skiprows=5)
- Excel formula wrappers on text fields (="value" → value)
- Quoted fields containing embedded commas
- ISBN values wrapped in extra quotes (needs stripping)

Grain: One row per book-format-sale date transaction.
Kimball compliance: Separate fact table to preserve B&N-specific fields
(list price vs sale price, royalty per unit, dual currency tracking).
"""

from pathlib import Path

import pandas as pd


# ===================================================================
# COLUMN MAPPING TO STANDARDIZED SCHEMA
# ===================================================================

COLUMN_MAP = {
    'Sale Date': 'sale_date',
    'Title': 'title',
    'Format': 'source_format',
    'BN ID / ISBN': 'bn_identifier',
    'eBook ISBN (Optional)': 'book_identifier',
    'Author': None,                    # PII — dropped
    'Publisher': None,                  # PII — dropped
    'List Price': 'list_price',
    'Sale Price': 'sale_price',
    'Selling Currency': 'selling_currency',
    'Units Sold': 'units_sold',         # Gross units (before returns)
    'Units Returned': 'units_returned',
    'Net Units Sold': 'quantity',       # Net units (fact measure)
    'Royalty %': 'royalty_rate',
    'Royalty per Unit': 'royalty_per_unit',
    'Total Royalty': 'royalty_amount',  # Standardized column name (Option B)
    'Payment Currency': 'payment_currency',
}

# Number of metadata rows B&N prepends before the actual CSV header
BNL_SKIP_ROWS = 5

# Text columns that may contain B&N's Excel formula wrapper (="value")
FORMULA_CLEAN_COLUMNS = [
    'title', 'source_format', 'bn_identifier', 'book_identifier',
]


# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def _clean_formula_value(value) -> str | float | None:
    """
    Strip B&N's Excel formula wrapper from cell values.

    Handles multi-layer wrapping like ="..." and surrounding quotes.

    Examples:
        ="Carmilla and Laura"         → Carmilla and Laura
        ""Carmilla and Laura""        → Carmilla and Laura
        "=""2940185885482"" "          → 2940185885482

    Args:
        value: Cell value (may be string, number, or NaN)

    Returns:
        Cleaned value with formula wrapper removed, or original if unchanged
    """
    if pd.isna(value):
        return value

    s = str(value).strip()

    # Strip outer quotes (pandas reads quoted CSV fields literally sometimes)
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]

    # Strip ="...pattern (Excel formula)
    if s.startswith('="') and s.endswith('"'):
        s = s[2:-1]

    # Strip any remaining outer quotes
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]

    # Also handle single-quote-wrapped strings
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]

    return s


def _normalize_isbn(isbn_value) -> str | None:
    """
    Normalize ISBN to clean digit string without hyphens.

    Aggressively cleans quoting, spaces, hyphens, and non-digit artifacts
    before validating length (ISBN-10 or ISBN-13). Handles Excel formula
    wrappers (.0 suffix, nested quotes).

    Args:
        isbn_value: ISBN value from B&N CSV (may be int, float, or string)

    Returns:
        Clean ISBN string (10 or 13 digits), or None if invalid/empty
    """
    if isbn_value is None or pd.isna(isbn_value):
        return None

    s = str(isbn_value).strip()

    # Early exit if empty
    if not s:
        return None

    # Strip all quoting and Excel formula syntax iteratively
    while True:
        cleaned = s.strip()

        # Remove Excel formula = prefix
        if cleaned.startswith('='):
            cleaned = cleaned.lstrip('=').strip()

        # Handle wrap/unwrapped quotes
        if cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = cleaned[1:-1].strip()
        elif cleaned.startswith("'") and cleaned.endswith("'"):
            cleaned = cleaned[1:-1].strip()

        if cleaned == s:  # No change made, break
            break
        s = cleaned

    # Strip ANY remaining quote characters
    s = s.replace('"', '').replace("'", '')

    # Remove all non-digit characters
    numeric_only = ''.join(c for c in s if c.isdigit())

    # Fail gracefully if nothing left
    if not numeric_only:
        return None

    # Validate length
    if len(numeric_only) not in [10, 13]:
        return None

    return numeric_only


def _ensure_numeric(series: pd.Series, name: str) -> pd.Series:
    """
    Safely convert a Series to numeric, replacing errors with 0.0.

    Args:
        series: Pandas Series to convert
        name: Field name for error logging

    Returns:
        Numeric Series with NaNs filled to 0.0
    """
    return pd.to_numeric(series, errors='coerce').fillna(0.0)


def _infer_edition_format(row) -> str:
    """
    Map B&N source_format labels to standard edition_format values.

    Defined at module level per CODING_STANDARDS §9 (Logical Structure).

    Args:
        row: DataFrame row with 'edition_format' and 'source_format' keys

    Returns:
        Standardized edition_format string
    """
    # Prefer existing edition_format from catalog enrichment
    ef = row.get('edition_format')
    if pd.notna(ef) and isinstance(ef, str) and ef.strip():
        return ef

    # Infer from B&N's source_format field
    sf = str(row.get('source_format', '')).lower()
    if 'nook' in sf or 'ebook' in sf or 'digital' in sf:
        return 'ebook'
    if 'paper' in sf or 'soft' in sf:
        return 'paperback'
    if 'hard' in sf:
        return 'hardcover'

    return 'ebook'


# ===================================================================
# MAIN LOADER FUNCTION
# ===================================================================

def load_bnl_data(filepath: str, catalog=None) -> pd.DataFrame:
    """
    Load Barnes & Noble Press royalty CSV.

    Maps B&N's custom date-range export format to the canonical Kimball
    schema. Handles B&N CSV quirks: 5 metadata header rows, Excel formula
    wrappers on text fields, and quoted fields with embedded commas.

    Uses eBook ISBN as primary identifier with BN ID fallback for print
    formats that lack an eBook ISBN (per Option C decision).

    Args:
        filepath: Path to B&N CSV file
        catalog: BookCatalog instance for ISBN-based hybrid enrichment

    Returns:
        DataFrame with renamed columns ready for database ingestion.
        Column mapping aligns with fact_bnl_sales schema in analyzer.py.
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading Barnes & Noble data from {filepath.name}")

    # Read CSV — B&N prepends 5 metadata rows before the actual header
    try:
        df = pd.read_csv(filepath, encoding='utf-8-sig', delimiter=',', skiprows=BNL_SKIP_ROWS)
    except UnicodeDecodeError:
        print("[WARN] UTF-8 failed, falling back to cp1252")
        df = pd.read_csv(filepath, encoding='cp1252', delimiter=',', skiprows=BNL_SKIP_ROWS)

    print(f"[INFO] B&N CSV: {len(df)} transaction records")

    # Clean Excel formula wrappers ("=value" → value) on text columns
    print("[INFO] Cleaning B&N Excel formula wrappers...")
    for col in FORMULA_CLEAN_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(_clean_formula_value)

    # Rename columns according to mapping
    df = df.rename(columns=COLUMN_MAP)

    # Filter out columns mapped to None (dropped entirely — PII)
    df = df[[c for c in df.columns if c is not None]]

    # Normalize both ISBN columns
    print("[INFO] Normalizing ISBN values...")
    if 'book_identifier' in df.columns:
        df['book_identifier'] = df['book_identifier'].apply(_normalize_isbn)
    if 'bn_identifier' in df.columns:
        df['bn_identifier'] = df['bn_identifier'].apply(_normalize_isbn)

    primary_isbns = df['book_identifier'].notna().sum()
    secondary_isbns = df['bn_identifier'].notna().sum()
    print(f"[INFO] Primary ISBNs (eBook): {primary_isbns}/{len(df)}")
    print(f"[INFO] Secondary IDs (BN): {secondary_isbns}/{len(df)}")

    # Parse sale_date column (single date per row)
    if 'sale_date' in df.columns:
        df['sale_date'] = pd.to_datetime(df['sale_date'], errors='coerce')
        na_dates = df['sale_date'].isna().sum()
        if na_dates > 0:
            print(f"[WARN] {na_dates} rows have unparseable dates (will be NULL)")
    else:
        print("[ERROR] No sale_date column found — aborting load")
        return pd.DataFrame()

    # Ensure numeric fields are properly typed
    numeric_fields = [
        'list_price', 'sale_price', 'quantity',
        'units_sold', 'units_returned', 'royalty_rate',
        'royalty_per_unit', 'royalty_amount',
    ]
    for field in numeric_fields:
        if field in df.columns:
            df[field] = _ensure_numeric(df[field], field)

    # Source platform annotation
    df['source_platform'] = 'barnes_noble'

    # Currency: default to USD if blank
    df['selling_currency'] = df.get('selling_currency', pd.Series(dtype=str)).fillna('USD')
    df['payment_currency'] = df.get('payment_currency', pd.Series(dtype=str)).fillna('USD')

    # Catalog enrichment via ISBN matching
    if catalog is not None and 'book_identifier' in df.columns:
        print("[INFO] Enriching with catalog metadata via eBook ISBN...")

        # Pass full DataFrame — catalog.enrich() uses how='left' merge
        df = catalog.enrich(df, 'book_identifier')

        total = len(df)
        matched = df['series'].notna().sum() if 'series' in df.columns else 0
        match_rate = (matched / total * 100) if total > 0 else 0
        print(f"[INFO] Total enrichment: {matched}/{total} rows matched ({match_rate:.1f}%)")

        unmatched_isbn_null = df['book_identifier'].isna().sum()
        if unmatched_isbn_null > 0:
            print(f"[NOTE] {unmatched_isbn_null} rows had no eBook ISBN — not enriched (print editions)")
    else:
        df['canonical_work_slug'] = None
        df['series'] = None

    # Set edition_format after enrichment (prevents column collision)
    df['edition_format'] = df.apply(_infer_edition_format, axis=1)
    print(f"[INFO] Edition format distribution:")
    print(df['edition_format'].value_counts(dropna=False).to_string())

    # Prepare for database ingestion — select final columns matching fact_bnl_sales schema
    final_columns = [
        'sale_date', 'source_platform', 'book_identifier', 'bn_identifier',
        'canonical_work_slug', 'series', 'edition_format',
        'title', 'source_format',
        'list_price', 'sale_price',
        'selling_currency', 'payment_currency',
        'units_sold', 'units_returned', 'quantity',
        'royalty_rate', 'royalty_per_unit', 'royalty_amount',
    ]
    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    # Drop rows with null sale_date (trailing blank/summary rows)
    before = len(df_result)
    df_result = df_result[df_result['sale_date'].notna()].copy()
    dropped = before - len(df_result)
    if dropped > 0:
        print(f"[INFO] Dropped {dropped} rows with null sale_date")

    print(f"[INFO] B&N load complete: {len(df_result)} transaction records")

    if not df_result.empty:
        print(f"[INFO] Date range: {df_result['sale_date'].min()} to {df_result['sale_date'].max()}")

        formats = df_result['source_format'].dropna().unique()
        if formats.size > 0:
            print(f"[INFO] Formats found: {', '.join(sorted(formats))}")

        total_royalty = df_result['royalty_amount'].sum()
        currencies = df_result['payment_currency'].dropna().unique()
        print(f"[INFO] Total royalty (raw): ${total_royalty:.2f} "
              f"across {len(currencies)} payment currencies: {', '.join(str(c) for c in currencies)}")
        print("[NOTE] USD conversion pending — pipeline applies to_usd() after all loaders complete")

    return df_result