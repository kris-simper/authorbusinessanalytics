"""
Kobo royalty loaders for direct sales and subscription reads.

Contains two loaders sharing common utility functions:
- load_kobo_data(): Kobo Store direct sales (per-transaction grain)
- load_kobo_plus_data(): Kobo Plus subscription reads (per-period grain)

Both parse monthly .xlsx exports with a 'Details' sheet. Uses eISBN as
primary identifier for catalog enrichment. Currency is preserved in raw form
(royalty_amount in Payable Currency) and converted to USD using historical
ECB rates (to_usd()).

Kimball compliance: Separate fact tables due to different grains:
- fact_kobo_sales: transaction-level (sale or refund per book-country-date)
- fact_kobo_plus_reads: period-level (aggregated subscription reads per book-region)
"""

from pathlib import Path

import pandas as pd


# ===================================================================
# COLUMN MAPPINGS TO STANDARDIZED SCHEMA
# ===================================================================

COLUMN_MAP = {
    'Date': 'sale_date',
    'Country': 'country',
    'State': 'state',
    'Zip Code': 'zip_code',
    'Content Type': 'content_type',
    'Total Qty': 'quantity',
    'Refund Reason': 'refund_reason',
    'DealID': 'deal_id',
    'Publisher Name': None,               # Dropped (metadata, not analytically useful)
    'Imprint': 'imprint',                 # Kept (publishing imprint analytics)
    'eISBN': 'book_identifier',
    'Author': None,                       # Dropped (PII)
    'Title': 'title',                     # Kept for unmatched-row reference
    'List Price': 'list_price',
    'Tax Excluded List Price': 'tax_excluded_list_price',
    'COGS %': 'cogs_percentage',
    'COGS Amount (LP Currency)': 'cogs_amount_lp',
    'LP Currency': 'lp_currency',
    'Foreign Exchange Rate to Payable Currency': 'fx_rate',
    'COGS (Payable Currency)': 'cogs_payable',
    'COGS based LP': 'cogs_based_lp',
    'COGS based LP excluding tax': 'cogs_based_lp_excl_tax',
    'COGS based LP Currency': 'cogs_based_lp_currency',
    'COGS Adjustment (Payable Currency)': 'cogs_adjustment',
    'Net Due (Payable Currency)': 'royalty_amount',  # Standardized (Option B)
    'Payable Currency': 'currency',
    'Total Tax (Payable Currency)': 'total_tax',
}

KOBO_PLUS_COLUMN_MAP = {
    'Read Period': 'sale_date',
    'Publisher name': None,               # Dropped (metadata)
    'eISBN': 'book_identifier',
    'Author': None,                       # Dropped (PII)
    'Title': 'title',
    'List price (TaxIn)': 'list_price_tax_in',
    'List price (TaxOut)': 'list_price_tax_out',
    'List price currency': 'list_price_currency',
    'Region': 'region',
    'Read threshold (%)': 'read_threshold_pct',
    'Reads': 'quantity',                  # Subscription reads (fact measure)
    'Total payable': 'total_payable_raw',
    'Foreign exchange to payable currency': 'fx_rate',
    'Total in payable currency': 'total_payable_converted',
    'Payable Currency': 'currency',
    'Value Per Minute': 'value_per_minute',
    'Total Minutes': 'total_minutes',
    'Revenue earned per title': 'revenue_per_title',
    'Publisher revenue share (%)': 'royalty_rate',
    'Total publisher revenue share in payable currency ($)': 'royalty_amount',
    'Total Tax in Payable Currency': 'total_tax',
    'Content Type': 'content_type',
}


# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def _normalize_isbn(isbn_value) -> str | None:
    """
    Normalize eISBN to clean string without hyphens.

    Handles Excel float coercion (.0 suffix), hyphens, and whitespace.
    Validates length (ISBN-10 or ISBN-13).

    Args:
        isbn_value: ISBN value from Kobo xlsx

    Returns:
        Clean ISBN string, or None if invalid/empty
    """
    if isbn_value is None or pd.isna(isbn_value):
        return None

    s = str(isbn_value).strip()

    if not s:
        return None

    # Handle Excel float coercion artifact (.0 suffix)
    if s.endswith('.0'):
        s = s[:-2]

    s = s.replace('-', '').replace(' ', '')

    if len(s) not in [10, 13]:
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
# KOBO STORE — DIRECT SALES LOADER
# ===================================================================

def load_kobo_data(filepath: str, catalog=None) -> pd.DataFrame:
    """
    Load Kobo Store monthly earnings xlsx (Details sheet).

    Maps Kobo's invoice export format to the canonical Kimball schema.
    Preserves state/zip granularity and COGS breakdown unique to Kobo.
    Refunds appear as negative quantity and negative royalty_amount.

    Args:
        filepath: Path to Kobo xlsx file (expects sales_invoice_PUB_*.xlsx)
        catalog: BookCatalog instance for eISBN-based enrichment

    Returns:
        DataFrame with renamed columns ready for database ingestion.
        Column mapping aligns with fact_kobo_sales schema in analyzer.py.
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading Kobo Store data from {filepath.name}")

    # Read xlsx — Kobo uses a 'Details' sheet among others in the workbook.
    # Broad exception catch is intentional: openpyxl raises varied exception
    # types (InvalidFileException, ValueError, etc.) and we want to catch all.
    try:
        df = pd.read_excel(filepath, sheet_name='Details', engine='openpyxl')
    except Exception as e:
        print(f"[ERROR] Failed to read Kobo xlsx: {e}")
        return pd.DataFrame()

    # Strip whitespace from column names (Kobo adds them inconsistently)
    df.columns = df.columns.str.strip()

    print(f"[INFO] Kobo xlsx (Details sheet): {len(df)} transaction records")

    # Rename columns according to mapping
    df = df.rename(columns=COLUMN_MAP)
    df = df[[c for c in df.columns if c is not None]]

    # Normalize eISBN identifiers for catalog matching
    print("[INFO] Normalizing eISBN values...")
    if 'book_identifier' in df.columns:
        df['book_identifier'] = df['book_identifier'].apply(_normalize_isbn)

    valid_isbns = df['book_identifier'].notna().sum()
    print(f"[INFO] Valid eISBNs found: {valid_isbns}/{len(df)}")

    # Parse sale_date column
    if 'sale_date' in df.columns:
        df['sale_date'] = pd.to_datetime(df['sale_date'], errors='coerce')
        na_dates = df['sale_date'].isna().sum()
        if na_dates > 0:
            print(f"[WARN] {na_dates} rows have unparseable dates (will be dropped)")
    else:
        print("[ERROR] No sale_date column found — aborting load")
        return pd.DataFrame()

    # Ensure numeric fields are properly typed
    numeric_fields = [
        'quantity', 'list_price', 'tax_excluded_list_price',
        'cogs_percentage', 'cogs_amount_lp', 'fx_rate',
        'cogs_payable', 'cogs_based_lp', 'cogs_based_lp_excl_tax',
        'cogs_adjustment', 'royalty_amount', 'total_tax',
    ]
    for field in numeric_fields:
        if field in df.columns:
            df[field] = _ensure_numeric(df[field], field)

    # Source platform annotation
    df['source_platform'] = 'kobo_store'

    # Currency: default to USD if blank
    df['currency'] = df.get('currency', pd.Series(dtype=str)).fillna('USD')

    # Drop rows with null sale_date (trailing blank/summary rows)
    before = len(df)
    df = df[df['sale_date'].notna()].copy()
    dropped = before - len(df)
    if dropped > 0:
        print(f"[INFO] Dropped {dropped} rows with null sale_date")

    # Catalog enrichment via eISBN matching
    if catalog is not None and 'book_identifier' in df.columns:
        print("[INFO] Enriching with catalog metadata via eISBN...")
        df = catalog.enrich(df, 'book_identifier')
        matched = df['series'].notna().sum() if 'series' in df.columns else 0
        match_rate = (matched / len(df) * 100) if len(df) > 0 else 0
        print(f"[INFO] Total enrichment: {matched}/{len(df)} rows matched ({match_rate:.1f}%)")
    else:
        df['canonical_work_slug'] = None
        df['series'] = None

    # Set default edition format after enrichment
    df['edition_format'] = df.get('edition_format', pd.Series(dtype=str)).fillna('ebook')

    # Select final columns matching fact_kobo_sales schema
    final_columns = [
        'sale_date', 'source_platform', 'book_identifier',
        'canonical_work_slug', 'series', 'edition_format',
        'country', 'state', 'zip_code',
        'content_type', 'imprint', 'title',
        'quantity', 'refund_reason', 'deal_id',
        'list_price', 'tax_excluded_list_price',
        'cogs_percentage', 'cogs_amount_lp', 'lp_currency',
        'fx_rate', 'cogs_payable', 'cogs_based_lp',
        'cogs_based_lp_excl_tax', 'cogs_based_lp_currency',
        'cogs_adjustment', 'currency', 'royalty_amount',
        'total_tax',
    ]
    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    print(f"[INFO] Kobo Store load complete: {len(df_result)} transaction records")

    if not df_result.empty:
        print(f"[INFO] Date range: {df_result['sale_date'].min()} to {df_result['sale_date'].max()}")

        countries = df_result['country'].dropna().unique()
        if countries.size > 0:
            print(f"[INFO] Countries found: {', '.join(sorted(countries))}")

        content_types = df_result['content_type'].dropna().unique()
        if content_types.size > 0:
            print(f"[INFO] Content types: {', '.join(sorted(content_types))}")

        total_royalty = df_result['royalty_amount'].sum()
        unique_currencies = df_result['currency'].nunique()
        print(f"[INFO] Total royalty (raw): ${total_royalty:.2f} across {unique_currencies} currencies")
        print("[NOTE] USD conversion pending — pipeline applies to_usd() after all loaders complete")

    return df_result


# ===================================================================
# KOBO PLUS — SUBSCRIPTION READS LOADER
# ===================================================================

def load_kobo_plus_data(filepath: str, catalog=None) -> pd.DataFrame:
    """
    Load Kobo Plus monthly subscription reads xlsx (Details sheet).

    Kobo Plus is a subscription model where readers pay a monthly fee and
    borrow books. Authors are compensated based on reads, similar to
    Kindle Unlimited (KENP). Each row represents one book-region-read period
    aggregation, not an individual transaction.

    Args:
        filepath: Path to Kobo Plus xlsx file (expects sales_invoice_SUBS_*.xlsx)
        catalog: BookCatalog instance for eISBN-based enrichment

    Returns:
        DataFrame with renamed columns ready for database ingestion.
        Column mapping aligns with fact_kobo_plus_reads schema in analyzer.py.
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading Kobo Plus data from {filepath.name}")

    # Read xlsx — same broad catch rationale as Kobo Store loader
    try:
        df = pd.read_excel(filepath, sheet_name='Details', engine='openpyxl')
    except Exception as e:
        print(f"[ERROR] Failed to read Kobo xlsx: {e}")
        return pd.DataFrame()

    # Strip whitespace from column names
    df.columns = df.columns.str.strip()

    print(f"[INFO] Kobo Plus xlsx (Details sheet): {len(df)} subscription read records")

    # Rename columns according to mapping
    df = df.rename(columns=KOBO_PLUS_COLUMN_MAP)
    df = df[[c for c in df.columns if c is not None]]

    # Normalize eISBN identifiers
    print("[INFO] Normalizing eISBN values...")
    if 'book_identifier' in df.columns:
        df['book_identifier'] = df['book_identifier'].apply(_normalize_isbn)

    valid_isbns = df['book_identifier'].notna().sum()
    print(f"[INFO] Valid eISBNs found: {valid_isbns}/{len(df)}")

    # Parse sale_date (Read Period — single date per row)
    if 'sale_date' in df.columns:
        df['sale_date'] = pd.to_datetime(df['sale_date'], errors='coerce')
        na_dates = df['sale_date'].isna().sum()
        if na_dates > 0:
            print(f"[WARN] {na_dates} rows have unparseable dates (will be dropped)")
    else:
        print("[ERROR] No sale_date column found — aborting load")
        return pd.DataFrame()

    # Ensure numeric fields are properly typed
    numeric_fields = [
        'list_price_tax_in', 'list_price_tax_out', 'read_threshold_pct',
        'quantity', 'total_payable_raw', 'fx_rate', 'total_payable_converted',
        'value_per_minute', 'total_minutes', 'revenue_per_title',
        'royalty_rate', 'royalty_amount', 'total_tax',
    ]
    for field in numeric_fields:
        if field in df.columns:
            df[field] = _ensure_numeric(df[field], field)

    # Source platform annotation
    df['source_platform'] = 'kobo_plus'

    # Currency: default to USD if blank
    df['currency'] = df.get('currency', pd.Series(dtype=str)).fillna('USD')

    # Drop rows with null sale_date
    before = len(df)
    df = df[df['sale_date'].notna()].copy()
    dropped = before - len(df)
    if dropped > 0:
        print(f"[INFO] Dropped {dropped} rows with null sale_date")

    # Catalog enrichment via eISBN matching
    if catalog is not None and 'book_identifier' in df.columns:
        print("[INFO] Enriching with catalog metadata via eISBN...")
        df = catalog.enrich(df, 'book_identifier')
        matched = df['series'].notna().sum() if 'series' in df.columns else 0
        match_rate = (matched / len(df) * 100) if len(df) > 0 else 0
        print(f"[INFO] Total enrichment: {matched}/{len(df)} rows matched ({match_rate:.1f}%)")
    else:
        df['canonical_work_slug'] = None
        df['series'] = None

    # Set default edition format after enrichment
    df['edition_format'] = df.get('edition_format', pd.Series(dtype=str)).fillna('ebook')

    # Select final columns matching fact_kobo_plus_reads schema
    final_columns = [
        'sale_date', 'source_platform', 'book_identifier',
        'canonical_work_slug', 'series', 'edition_format',
        'region', 'content_type', 'title',
        'list_price_tax_in', 'list_price_tax_out', 'list_price_currency',
        'read_threshold_pct', 'quantity', 'total_payable_raw',
        'fx_rate', 'total_payable_converted', 'currency',
        'value_per_minute', 'total_minutes', 'revenue_per_title',
        'royalty_rate', 'royalty_amount', 'total_tax',
    ]
    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    print(f"[INFO] Kobo Plus load complete: {len(df_result)} subscription read records")

    if not df_result.empty:
        print(f"[INFO] Date range: {df_result['sale_date'].min()} to {df_result['sale_date'].max()}")

        regions = df_result['region'].dropna().unique()
        if regions.size > 0:
            print(f"[INFO] Regions found: {', '.join(sorted(regions))}")

        total_reads = df_result['quantity'].sum()
        total_royalty = df_result['royalty_amount'].sum()
        unique_currencies = df_result['currency'].nunique()
        print(f"[INFO] Total reads: {int(total_reads)}")
        print(f"[INFO] Total royalty (raw): ${total_royalty:.2f} across {unique_currencies} currencies")
        print("[NOTE] USD conversion pending — pipeline applies to_usd() after all loaders complete")

    return df_result