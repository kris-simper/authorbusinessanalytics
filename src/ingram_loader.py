"""
IngramSpark royalty loader for print book sales.

Parses monthly .xls compensation reports. Each row represents one
book-market-currency-month aggregation (not individual transactions).
Uses ISBN-13 as primary identifier for catalog enrichment. Currency is
preserved in raw form (royalty_amount in reporting_currency_code) and
converted to USD using historical ECB rates (to_usd()).

Only MTD (Month-To-Date) columns are ingested — YTD columns are dropped
to prevent double-counting across monthly loads.

Ingram .xls quirks handled:
- Auto-detects file format (true .xls vs disguised text/CSV/HTML)
- Parses period_name (e.g., 'MAY-26') into proper date
- Maps Ingram binding_type labels to standard edition_format values
- Strips 'LS-' prefix from market values for clean country names

Grain: One row per book-market-currency-month aggregation.
Kimball compliance: Separate fact table to preserve Ingram-specific fields
(print charges, wholesale economics, deferral tracking).
"""

import re
from pathlib import Path

import pandas as pd


# ===================================================================
# COLUMN MAPPING TO STANDARDIZED SCHEMA
# ===================================================================

COLUMN_MAP = {
    # Identifiers & dimensions
    'isbn_13': 'book_identifier',
    'isbn': 'isbn_legacy',
    'parent_isbn': 'parent_isbn',
    'title': 'title',
    'binding_type': 'binding_type_raw',
    'book_type_id': 'book_type_id',
    'page_count': 'page_count',
    'publisher_imprint': 'publisher_imprint',
    'market': 'market_raw',
    'sales_category': 'sales_category',
    'returns_flag_value': 'returns_flag',

    # Pricing & discount metadata
    'list_price': 'list_price',
    'wholesale_discount_%': 'wholesale_discount_pct',

    # MTD measures (ONLY MTD — YTD columns dropped to avoid double-counting)
    'MTD_net_quantity': 'quantity',
    'MTD_avg_list_price': 'mtd_avg_list_price',
    'MTD_extended_list': 'mtd_extended_list',
    'MTD_avg_discount_%': 'mtd_avg_discount_pct',
    'MTD_extended_discount': 'mtd_extended_discount',
    'MTD_avg_wholesale_price': 'mtd_avg_wholesale_price',
    'MTD_extended_wholesale': 'mtd_extended_wholesale',
    'MTD_avg_print_charge': 'mtd_avg_print_charge',
    'MTD_extended_print_charge': 'mtd_extended_print_charge',
    'MTD_gross_pub_comp': 'mtd_gross_pub_comp',
    'MTD_extended_adjustments': 'mtd_extended_adjustments',
    'MTD_extended_recovery': 'mtd_extended_recovery',
    'MTD_pub_comp': 'royalty_amount',
    'MTD_return_quantity': 'mtd_return_quantity',
    'MTD_return_wholesale': 'mtd_return_wholesale',
    'MTD_return_charge': 'mtd_return_charge',
    'MTD_return_total': 'mtd_return_total',
    'MTD_net_wholesale': 'mtd_net_wholesale',
    'MTD_net_pub_comp': 'mtd_net_pub_comp',

    # MTD taxes & fees
    'MTD_wholesale_tax': 'mtd_wholesale_tax',
    'MTD_print_charge_tax': 'mtd_print_charge_tax',
    'MTD_return_wholesale_tax': 'mtd_return_wholesale_tax',
    'MTD_return_charge_tax': 'mtd_return_charge_tax',
    'Mtd_global_distribution_fee': 'mtd_global_distribution_fee',
    'Mtd_global_distribution_fee_tax': 'mtd_global_distribution_fee_tax',

    # Period & currency
    'period_name': 'period_name',
    'reporting_currency_code': 'currency',

    # Status flags
    'title_status_flag_value': 'title_status_flag',
}


# Columns to explicitly DROP (PII, redundant, or YTD double-count risk)
DROP_COLUMNS = [
    'publisher_number', 'publisher_name', 'author', 'sku',
    'cancelled_date', 'nonreturnable_date',
    'deferral_balance', 'original_deferral_amount',
    'customer_flexfield1', 'customer_flexfield2', 'customer_flexfield3',
    'customer_flexfield4', 'customer_flexfield5',
    # YTD columns — would double-count across monthly loads
    'YTD_quantity', 'YTD_avg_list_price', 'YTD_extended_list_price',
    'YTD_avg_discount_%', 'YTD_extended_discount', 'YTD_avg_wholesale_price',
    'YTD_extended_wholesale', 'YTD_avg_print_charge', 'YTD_extended_print_charge',
    'YTD_gross_pub_comp', 'YTD_extended_adjustments', 'YTD_extended_recovery',
    'YTD_pub_comp', 'YTD_return_quantity', 'YTD_return_wholesale',
    'YTD_return_charge', 'YTD_return_total', 'YTD_net_quantity',
    'YTD_net_wholesale', 'YTD_net_pub_comp',
    'YTD_wholesale_tax', 'YTD_print_charge_tax', 'YTD_return_wholesale_tax',
    'YTD_return_charge_tax', 'Ytd_global_distribution_fee',
    'Ytd_global_distribution_fee_tax',
]


# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def _normalize_isbn(isbn_value) -> str | None:
    """
    Normalize ISBN to clean digit string without hyphens.

    Handles Excel float coercion (.0 suffix), hyphens, and whitespace.
    Validates length (ISBN-10 or ISBN-13).

    Args:
        isbn_value: ISBN value from Ingram file (may be int, float, or string)

    Returns:
        Clean ISBN string (10 or 13 digits), or None if invalid/empty
    """
    if isbn_value is None or pd.isna(isbn_value):
        return None

    s = str(isbn_value).strip()

    if not s:
        return None

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


def _parse_period_name(period_value) -> pd.Timestamp | pd._libs.tslibs.nattype.NaTType:
    """
    Parse Ingram period_name (e.g., 'MAY-26') into a proper date.

    Returns the first day of that month (e.g., 2026-05-01). Handles
    2-digit year conversion (26 → 2026) explicitly since pandas can
    interpret 'MAY-26' as year 26 AD.

    Args:
        period_value: Period string from Ingram file

    Returns:
        Timestamp for first day of the period month, or NaT if unparseable
    """
    if pd.isna(period_value):
        return pd.NaT

    s = str(period_value).strip()

    # Handle format like 'MAY-26' or 'APR-26'
    try:
        parts = s.split('-')
        if len(parts) == 2:
            month_str = parts[0].upper()
            year_str = parts[1]

            month_map = {
                'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
            }

            if month_str in month_map:
                month_num = month_map[month_str]
                year_num = int(year_str)

                # Convert 2-digit year to 4-digit (assume 21st century)
                if year_num < 100:
                    year_num += 2000

                return pd.Timestamp(year=year_num, month=month_num, day=1)
    except (ValueError, TypeError, KeyError):
        pass

    # Fallback: let pandas try, fixing 2-digit year interpretation
    try:
        parsed = pd.to_datetime(s, errors='coerce')
        if pd.notna(parsed) and parsed.year < 1900:
            if parsed.year >= 70:
                parsed = parsed.replace(year=parsed.year + 1900)
            else:
                parsed = parsed.replace(year=parsed.year + 2000)
        return parsed
    except (ValueError, TypeError):
        return pd.NaT


def _map_binding_type(binding_raw) -> str:
    """
    Map Ingram binding_type labels to standard edition_format values.

    Ingram uses descriptive labels like 'Perfectbound (Trade Paper'
    rather than simple 'paperback'/'hardcover'.

    Args:
        binding_raw: Binding type string from Ingram file

    Returns:
        Standardized edition_format string
    """
    if pd.isna(binding_raw):
        return 'unknown'

    s = str(binding_raw).lower().strip()

    if 'cloth' in s or 'laminate' in s or 'hard' in s:
        return 'hardcover'
    if 'perfect' in s or 'paper' in s or 'soft' in s:
        return 'paperback'
    if 'ebook' in s or 'digital' in s:
        return 'ebook'
    if 'board' in s:
        return 'board_book'
    if 'spiral' in s or 'wire' in s:
        return 'spiral_bound'

    return 'unknown'


def _clean_market(market_value) -> str | None:
    """
    Strip Ingram's 'LS-' prefix from market values.

    Handles both 'LS-United States' and 'LS - Australia' (with spaces).

    Args:
        market_value: Market string from Ingram file

    Returns:
        Clean country/region name, or None if input is NaN
    """
    if pd.isna(market_value):
        return None

    s = str(market_value).strip()

    s = re.sub(r'^LS\s*[-]\s*', '', s, flags=re.IGNORECASE)

    return s.strip()


def _read_ingram_xls(filepath: Path) -> pd.DataFrame:
    """
    Read Ingram file with automatic format detection.

    Ingram exports .xls files that may actually be: true binary .xls,
    .xlsx renamed to .xls, HTML disguised as .xls, or tab/pipe-delimited
    text with a .xls extension. This function tries each format in order.

    Broad exception catches are intentional: each read method raises
    different exception types (xlrd errors, openpyxl errors, parse errors)
    and we need to fall through to the next attempt.

    Args:
        filepath: Path to .xls file

    Returns:
        DataFrame, or empty DataFrame if all methods fail
    """
    # Attempt 1: Check if it's actually plain text (tab/pipe/comma delimited)
    try:
        with open(filepath, 'rb') as f:
            header_bytes = f.read(200)
            header_text = header_bytes.decode('utf-8', errors='ignore').strip()

        if header_text and header_text[0].isalpha():
            print("[INFO] File detected as text format (misnamed .xls)")

            if '\t' in header_text:
                sep, delim_name = '\t', 'Tab'
            elif '|' in header_text:
                sep, delim_name = '|', 'Pipe'
            elif ',' in header_text:
                sep, delim_name = ',', 'Comma'
            else:
                sep, delim_name = '\t', 'Tab (default)'

            print(f"[INFO] Delimiter detected: {delim_name}")
            return pd.read_csv(filepath, sep=sep, encoding='utf-8')
    except Exception:
        pass

    # Attempt 2: pandas auto-detect Excel
    try:
        return pd.read_excel(filepath)
    except Exception:
        pass

    # Attempt 3: xlrd engine (true .xls binary format)
    try:
        return pd.read_excel(filepath, engine='xlrd')
    except Exception:
        pass

    # Attempt 4: openpyxl (.xlsx disguised as .xls)
    try:
        return pd.read_excel(filepath, engine='openpyxl')
    except Exception:
        pass

    # Attempt 5: HTML table
    try:
        tables = pd.read_html(filepath)
        if tables:
            print("[INFO] File was HTML disguised as .xls")
            return tables[0]
    except Exception:
        pass

    print(f"[ERROR] Could not read {filepath.name} with any method")
    return pd.DataFrame()


# ===================================================================
# MAIN LOADER FUNCTION
# ===================================================================

def load_ingram_data(filepath: str, catalog=None) -> pd.DataFrame:
    """
    Load IngramSpark monthly compensation .xls file.

    Maps Ingram's compensation report format to the canonical Kimball
    schema. Only MTD columns are ingested — YTD values are dropped to
    prevent double-counting across monthly loads.

    Uses ISBN-13 as primary identifier with ISBN legacy as fallback.
    Currency from reporting_currency_code is preserved in raw form and
    converted to USD via to_usd() in the pipeline.

    Args:
        filepath: Path to Ingram .xls file
        catalog: BookCatalog instance for ISBN-based enrichment

    Returns:
        DataFrame with renamed columns ready for database ingestion.
        Column mapping aligns with fact_ingram_sales schema in analyzer.py.
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading IngramSpark data from {filepath.name}")

    # Read file with automatic format detection
    df = _read_ingram_xls(filepath)

    if df.empty:
        print("[ERROR] No data loaded from Ingram file")
        return pd.DataFrame()

    # Strip whitespace from column names
    df.columns = df.columns.str.strip()

    print(f"[INFO] Ingram .xls: {len(df)} book-market-currency records")
    print(f"[INFO] Raw column count: {len(df.columns)}")

    # Drop PII/YTD columns first (reduces noise before rename)
    drop_present = [c for c in DROP_COLUMNS if c in df.columns]
    if drop_present:
        df = df.drop(columns=drop_present)
        print(f"[INFO] Dropped {len(drop_present)} PII/YTD columns")

    # Rename columns according to mapping
    df = df.rename(columns=COLUMN_MAP)
    df = df[[c for c in df.columns if c is not None]]

    # Normalize ISBN-13 as primary identifier (fallback to legacy ISBN)
    print("[INFO] Normalizing ISBN-13 values...")
    if 'book_identifier' in df.columns:
        df['book_identifier'] = df['book_identifier'].apply(_normalize_isbn)
    elif 'isbn_legacy' in df.columns:
        print("[WARN] ISBN-13 not found, attempting legacy ISBN")
        df['book_identifier'] = df['isbn_legacy'].apply(_normalize_isbn)
        df = df.drop(columns=['isbn_legacy'])

    valid_isbns = df['book_identifier'].notna().sum()
    print(f"[INFO] Valid ISBNs found: {valid_isbns}/{len(df)}")

    # Parse period_name into sale_date (first day of that month)
    if 'period_name' in df.columns:
        print("[INFO] Parsing period_name values...")
        df['sale_date'] = df['period_name'].apply(_parse_period_name)
        na_dates = df['sale_date'].isna().sum()
        if na_dates > 0:
            print(f"[WARN] {na_dates} rows have unparseable periods (will be dropped)")
    else:
        print("[ERROR] No period_name column found — aborting load")
        return pd.DataFrame()

    # Map binding_type to standard edition_format
    if 'binding_type_raw' in df.columns:
        df['edition_format'] = df['binding_type_raw'].apply(_map_binding_type)
        print(f"[INFO] Binding type distribution:")
        print(df['edition_format'].value_counts(dropna=False).to_string())
    else:
        df['edition_format'] = 'unknown'

    # Clean market values (strip LS- prefix)
    if 'market_raw' in df.columns:
        df['country'] = df['market_raw'].apply(_clean_market)
    else:
        df['country'] = None

    # Ensure numeric fields are properly typed
    numeric_fields = [
        'list_price', 'wholesale_discount_pct', 'page_count',
        'quantity', 'mtd_avg_list_price', 'mtd_extended_list',
        'mtd_avg_discount_pct', 'mtd_extended_discount',
        'mtd_avg_wholesale_price', 'mtd_extended_wholesale',
        'mtd_avg_print_charge', 'mtd_extended_print_charge',
        'mtd_gross_pub_comp', 'mtd_extended_adjustments',
        'mtd_extended_recovery', 'royalty_amount',
        'mtd_return_quantity', 'mtd_return_wholesale',
        'mtd_return_charge', 'mtd_return_total',
        'mtd_net_wholesale', 'mtd_net_pub_comp',
        'mtd_wholesale_tax', 'mtd_print_charge_tax',
        'mtd_return_wholesale_tax', 'mtd_return_charge_tax',
        'mtd_global_distribution_fee', 'mtd_global_distribution_fee_tax',
    ]
    for field in numeric_fields:
        if field in df.columns:
            df[field] = _ensure_numeric(df[field], field)

    # Source platform annotation
    df['source_platform'] = 'ingram_spark'

    # Currency: default to USD if blank
    df['currency'] = df.get('currency', pd.Series(dtype=str)).fillna('USD')

    # Drop rows with null sale_date
    before = len(df)
    df = df[df['sale_date'].notna()].copy()
    dropped = before - len(df)
    if dropped > 0:
        print(f"[INFO] Dropped {dropped} rows with null sale_date")

    # Catalog enrichment via ISBN matching
    if catalog is not None and 'book_identifier' in df.columns:
        print("[INFO] Enriching with catalog metadata via ISBN-13...")

        # Preserve edition_format before enrich (catalog.enrich may overwrite/drop it)
        edition_format_preserve = df['edition_format'].copy()

        df = catalog.enrich(df, 'book_identifier')

        # Restore edition_format if enrichment dropped or overwrote it
        if 'edition_format' not in df.columns or df['edition_format'].isna().all():
            df['edition_format'] = edition_format_preserve.values

        total = len(df)
        matched = df['series'].notna().sum() if 'series' in df.columns else 0
        match_rate = (matched / total * 100) if total > 0 else 0
        print(f"[INFO] Total enrichment: {matched}/{total} rows matched ({match_rate:.1f}%)")
    else:
        df['canonical_work_slug'] = None
        df['series'] = None
        print("[INFO] Skipping catalog enrichment (no catalog or no ISBN column)")

    # Select final columns matching fact_ingram_sales schema
    final_columns = [
        'sale_date', 'source_platform', 'book_identifier',
        'canonical_work_slug', 'series', 'edition_format',
        'country', 'title', 'publisher_imprint',
        'binding_type_raw', 'book_type_id', 'page_count',
        'sales_category', 'returns_flag', 'title_status_flag',
        'parent_isbn',
        'list_price', 'wholesale_discount_pct',
        'quantity', 'mtd_avg_list_price', 'mtd_extended_list',
        'mtd_avg_discount_pct', 'mtd_extended_discount',
        'mtd_avg_wholesale_price', 'mtd_extended_wholesale',
        'mtd_avg_print_charge', 'mtd_extended_print_charge',
        'mtd_gross_pub_comp', 'mtd_extended_adjustments',
        'mtd_extended_recovery', 'royalty_amount',
        'mtd_return_quantity', 'mtd_return_wholesale',
        'mtd_return_charge', 'mtd_return_total',
        'mtd_net_wholesale', 'mtd_net_pub_comp',
        'mtd_wholesale_tax', 'mtd_print_charge_tax',
        'mtd_return_wholesale_tax', 'mtd_return_charge_tax',
        'mtd_global_distribution_fee', 'mtd_global_distribution_fee_tax',
        'currency',
    ]
    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    print(f"[INFO] Ingram load complete: {len(df_result)} compensation records")

    if not df_result.empty:
        print(f"[INFO] Date range: {df_result['sale_date'].min()} to {df_result['sale_date'].max()}")

        countries = df_result['country'].dropna().unique()
        if countries.size > 0:
            print(f"[INFO] Markets: {', '.join(sorted(countries))}")

        formats = df_result['edition_format'].dropna().unique()
        if formats.size > 0:
            print(f"[INFO] Edition formats: {', '.join(sorted(formats))}")

        total_qty = df_result['quantity'].sum()
        total_royalty = df_result['royalty_amount'].sum()
        unique_currencies = df_result['currency'].nunique()
        print(f"[INFO] Total net quantity: {int(total_qty)}")
        print(f"[INFO] Total pub comp (raw): ${total_royalty:.2f} "
              f"across {unique_currencies} currencies: "
              f"{', '.join(df_result['currency'].dropna().unique())}")
        print("[NOTE] USD conversion pending — pipeline applies to_usd() after all loaders complete")

    return df_result