"""
Draft2Digital royalty loader for wide-distribution ebook sales.

Parses monthly CSV exports containing distributed retailer transactions.
Each row represents one book-retailer-country-period combination with
net unit sales and revenue breakdowns. Uses EAN ISBN (all numbers, no hyphens)
as primary identifier for catalog enrichment. Currency is preserved in raw form
(royalty_amount) and converted to USD using historical ECB rates (to_usd()).

Grain: One row per distributor-book-country-sale period transaction.
Kimball compliance: Separate fact table due to distributor/vendor dimension
granularity not present in sales_fact.
"""

from pathlib import Path

import pandas as pd


# ===================================================================
# COLUMN MAPPING TO STANDARDIZED SCHEMA
# ===================================================================

COLUMN_MAP = {
    'Start Date': None,                    # End Date suffices as sale_date
    'End Date': 'sale_date',               # Sale date per handoff spec
    'Title ID': None,                      # Internal D2D identifier — dropped
    'Ebook ISBN': 'book_identifier',       # Primary key for catalog matching
    'Title': None,                         # Retained via catalog.enrich() only
    'Primary Author': None,                # PII — dropped
    'Distributor': 'distributor',          # Retailer (Apple, Kobo, Google Play, etc.)
    'Vendor': 'vendor',                    # D2D vendor code (contextual)
    'Country': 'country',                  # Region/country code
    'Units Sold': None,                    # Implicitly captured via Net Unit Sales
    'Units Returned': 'units_returned',    # Returns count (audit trail)
    'Net Unit Sales': 'quantity',          # Net units after returns (fact measure)
    'Sales Model': None,                   # Transactional vs subscription — not analytically essential
    'Retailer': 'distributor_alt',         # Secondary distributor reference
    'List Price Per Unit': 'list_price',
    'Currency Code': 'currency',
    'Offer Price Per Unit': 'offer_price',
    'Royalty Percent': 'royalty_rate',
    'Sales Channel Fee/Taxes Per Unit': 'fee_per_unit',
    'Sales Channel Revenue Per Unit': None,# Derivable downstream if needed
    'Extended Sales Channel Revenue': None,# Derivable downstream if needed
    'Sales Channel Share': None,           # Not analytically essential
    'D2D Share': None,                     # Platform fee % — context only
    'Publisher Share': 'royalty_amount',   # Standardized column name (Option B)
    'Publisher Share USD (estimated)': None,  # Use our own ECB conversion instead
    'Verified': None,                      # Metadata flag — not analytically useful
}

DROP_COLUMNS = ['distributor_alt']


# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def _normalize_isbn(isbn_value) -> str | None:
    """
    Normalize Ebook ISBN to clean string without hyphens.

    D2D exports ISBNs as plain integers (e.g., 9781732461123) but catalog may
    store them with hyphens (978-1-7324611-2-3). Strips formatting artifacts
    for consistent matching. Also handles Excel float coercion (.0 suffix).

    Args:
        isbn_value: ISBN value from D2D CSV (may be int, float, or string)

    Returns:
        Clean ISBN string with no hyphens or decimals, or None if invalid
    """
    if isbn_value is None or pd.isna(isbn_value):
        return None

    s = str(isbn_value).strip()

    # Handle Excel float coercion artifact (.0 suffix)
    if s.endswith('.0'):
        s = s[:-2]

    s = s.replace('-', '').replace(' ', '')

    if len(s) not in [10, 13]:
        print(f"[WARN] Invalid ISBN length ({len(s)}): {s}")
        return None

    return s


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


# ===================================================================
# MAIN LOADER FUNCTION
# ===================================================================

def load_d2d_data(filepath: str, catalog=None) -> pd.DataFrame:
    """
    Load Draft2Digital monthly earnings CSV.

    Maps D2D's distributed retailer export format to the canonical Kimball
    schema. Preserves distributor/vendor granularity unlike sales_fact which
    lumps all direct platform sales together. Multiple retailers sold through
    D2D appear as separate rows within the same report, enabling distributor-
    level analytics.

    Currency handling uses standardized ECB-to-usd() conversion rather than
    trusting D2D's built-in USD estimate. Outputs column named royalty_amount
    (standardized per Option B).

    Args:
        filepath: Path to D2D CSV file (expects YYYY-MM-* naming pattern)
        catalog: BookCatalog instance for ISBN-based hybrid enrichment

    Returns:
        DataFrame with renamed columns ready for database ingestion.
        Column mapping aligns with fact_d2d_sales schema in analyzer.py.
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading Draft2Digital data from {filepath.name}")

    # Read CSV with UTF-8 encoding (fallback to cp1252 for Windows exports)
    try:
        df = pd.read_csv(filepath, encoding='utf-8')
    except UnicodeDecodeError:
        print("[WARN] UTF-8 failed, falling back to cp1252")
        df = pd.read_csv(filepath, encoding='cp1252')

    print(f"[INFO] D2D CSV: {len(df)} distributor-level records")

    # Rename and filter columns according to mapping
    df = df.rename(columns=COLUMN_MAP)
    df = df[[c for c in df.columns if c is not None]]
    df = df.drop(columns=DROP_COLUMNS, errors='ignore')

    # Normalize ISBN identifiers for catalog matching
    print("[INFO] Normalizing Ebook ISBN values...")
    df['book_identifier'] = df['book_identifier'].apply(_normalize_isbn)
    valid_isbns = df['book_identifier'].notna().sum()
    print(f"[INFO] Valid ISBNs found: {valid_isbns}/{len(df)}")

    # Parse sale_date column
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
        'quantity', 'units_returned', 'list_price',
        'offer_price', 'royalty_rate', 'fee_per_unit', 'royalty_amount',
    ]
    for field in numeric_fields:
        if field in df.columns:
            df[field] = _ensure_numeric(df[field], field)

    # Source platform annotation (for UNION ALL queries in dashboard)
    df['source_platform'] = 'draft2digital'

    # Catalog enrichment — pass full DataFrame, left merge handles NaN gracefully
    if catalog is not None and 'book_identifier' in df.columns:
        print("[INFO] Enriching with catalog metadata via ISBN...")
        df = catalog.enrich(df, 'book_identifier')
        matched = df['series'].notna().sum() if 'series' in df.columns else 0
        print(f"[INFO] Total: {matched}/{len(df)} rows enriched")
    else:
        df['canonical_work_slug'] = None
        df['series'] = None

    # Set default edition format after enrichment (prevents column collision)
    df['edition_format'] = df.get('edition_format', pd.Series(dtype=str)).fillna('ebook')

    # Select final columns matching fact_d2d_sales schema
    final_columns = [
        'sale_date', 'source_platform', 'book_identifier',
        'canonical_work_slug', 'series', 'edition_format',
        'distributor', 'vendor', 'country',
        'quantity', 'units_returned', 'list_price',
        'offer_price', 'currency', 'royalty_amount',
        'royalty_rate', 'fee_per_unit',
    ]
    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    # Drop rows with null sale_date (trailing blank/summary rows)
    before = len(df_result)
    df_result = df_result[df_result['sale_date'].notna()].copy()
    dropped = before - len(df_result)
    if dropped > 0:
        print(f"[INFO] Dropped {dropped} rows with null sale_date")

    print(f"[INFO] D2D load complete: {len(df_result)} distributor-transaction records")

    if not df_result.empty:
        print(f"[INFO] Date range: {df_result['sale_date'].min()} to {df_result['sale_date'].max()}")
        distributors = df_result['distributor'].dropna().unique()
        if distributors.size > 0:
            print(f"[INFO] Distributors found: {', '.join(sorted(distributors))}")
        print(f"[INFO] Total royalty (raw): ${df_result['royalty_amount'].sum():.2f} "
              f"across {df_result['currency'].nunique()} currencies")
        print("[NOTE] USD conversion pending — pipeline applies to_usd() after all loaders complete")

    return df_result