"""
WooCommerce sales loader for direct-store product analytics.

Parses WooCommerce product analytics CSV exports and maps them to the
fact_woo_sales table. Date ranges are extracted from filenames since
WooCommerce exports do not include date columns in the data itself.
Product titles are matched against the book catalog via fuzzy matching
since WooCommerce SKUs are not populated.

Supports both single-month exports and multi-range files — duplicate
product-period combinations are automatically aggregated to prevent
double-counting.

Grain: One row per product-period (monthly aggregate, not individual transactions).
Kimball compliance: Separate fact table due to product-level grain without
ISBN identifiers and WooCommerce-specific fields (orders, categories).
"""

import re
from difflib import SequenceMatcher  # noqa: F401 — used by _match_titles_to_catalog
from pathlib import Path

import pandas as pd

from src.matching import _match_titles_to_catalog


# ===================================================================
# COLUMN MAPPING TO STANDARDIZED SCHEMA
# ===================================================================

COLUMN_MAP = {
    'Product title': 'product_name',
    'SKU': 'sku',
    'Items sold': 'items_sold',
    'Net sales': 'net_sales',
    'Orders': 'orders_count',
    'Category': 'category',
}


# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def _clean_title(title) -> str:
    """
    Normalize a title for comparison: lowercase, replace & with and, strip.

    Used for substring and fuzzy matching against catalog display titles.

    Args:
        title: Title string (may be NaN)

    Returns:
        Cleaned lowercase string, or empty string if input is NaN/non-string
    """
    if pd.isna(title) or not isinstance(title, str):
        return ''
    return title.lower().replace('&', 'and').strip()


def parse_date_range_from_filename(filename: str) -> tuple:
    """
    Extract date range from WooCommerce export filename.

    Supports two patterns:
    - Standard: ...after-YYYY-MM-DD_before-YYYY-MM-DD.csv
    - Fallback: MonthName_YYYY.csv (e.g., January_2024.csv)

    Args:
        filename: WooCommerce CSV filename string

    Returns:
        Tuple of (period_start, period_end) as Timestamps, or (None, None)
    """
    match = re.search(r'after-(\d{4}-\d{2}-\d{2})_before-(\d{4}-\d{2}-\d{2})', filename)
    if match:
        start = pd.to_datetime(match.group(1))
        end = pd.to_datetime(match.group(2))
        return start, end

    # Fallback: Month name + year pattern (e.g., "January_2024.csv")
    month_match = re.search(
        r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
        r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|'
        r'Dec(?:ember)?)_(\d{4})',
        filename,
        re.IGNORECASE,
    )
    if month_match:
        month_names = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }
        month_num = month_names.get(month_match.group(1).lower()[:3])
        year = int(month_match.group(2))
        if month_num:
            start = pd.Timestamp(year=year, month=month_num, day=1)
            end = start + pd.offsets.MonthEnd(0)
            return start, end

    return None, None


# ===================================================================
# MAIN LOADER FUNCTION
# ===================================================================

def load_woo_data(filepath: str, catalog=None) -> pd.DataFrame:
    """
    Load a single WooCommerce product analytics CSV.

    Uses a three-stage enrichment approach because WooCommerce exports lack
    ISBNs entirely:
        Stage 1: catalog.enrich() identifier match (will mostly fail)
        Stage 2a: Substring containment (catalog title found within product name)
        Stage 2b: Fuzzy title matching via _match_titles_to_catalog()

    Args:
        filepath: Path to the WooCommerce CSV
        catalog: BookCatalog instance for title-based enrichment

    Returns:
        DataFrame with catalog-enriched WooCommerce sales data, or empty
        DataFrame if the file cannot be processed
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading WooCommerce data from {filepath.name}")

    # Parse date range from filename (WooCommerce doesn't include dates in data)
    period_start, period_end = parse_date_range_from_filename(filepath.name)
    if period_start is None:
        print(f"[WARN] Could not parse date range from filename, skipping: {filepath.name}")
        return pd.DataFrame()

    print(f"[INFO] Period: {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}")

    # Read CSV with UTF-8 encoding (fallback to cp1252 for Windows)
    try:
        df = pd.read_csv(filepath, encoding='utf-8')
    except UnicodeDecodeError:
        print("[WARN] UTF-8 failed, falling back to cp1252")
        df = pd.read_csv(filepath, encoding='cp1252')

    # Skip empty exports (header-only files with no product rows)
    if len(df) == 0:
        print(f"[WARN] Empty export, skipping: {filepath.name}")
        return pd.DataFrame()

    print(f"[INFO] WooCommerce CSV: {len(df)} products")

    # Rename columns to match database schema
    df = df.rename(columns=COLUMN_MAP)

    # Tag with date range and source platform
    df['sale_date'] = period_end
    df['period_start'] = period_start
    df['period_end'] = period_end
    df['source_platform'] = 'woocommerce'

    # Convert numeric fields
    df['items_sold'] = pd.to_numeric(df['items_sold'], errors='coerce').fillna(0).astype(int)
    df['net_sales'] = pd.to_numeric(df['net_sales'], errors='coerce').fillna(0.0).astype(float)
    df['orders_count'] = pd.to_numeric(df['orders_count'], errors='coerce').fillna(0).astype(int)
    df['sku'] = df['sku'].fillna('').str.strip()

    # Catalog enrichment — three-stage approach due to lack of ISBNs
    if catalog is not None:
        print("[INFO] Enriching WooCommerce products with catalog metadata...")

        # Stage 1: Identifier-based match (mostly fails — no SKUs/ISBNs)
        df_enriched = catalog.enrich(df, 'product_name')

        # Stage 2a: Substring containment matching for unmatched products
        unmatched_mask = df_enriched['series'].isna()
        if unmatched_mask.any():
            print(f"[INFO] Stage 2a: Substring containment for {unmatched_mask.sum()} unmatched products...")

            if hasattr(catalog, 'raw_catalog') and catalog.raw_catalog is not None:
                cat_titles = catalog.raw_catalog[
                    ['display_title', 'series', 'canonical_work_slug', 'edition_format']
                ].drop_duplicates()
                cat_titles['_clean'] = cat_titles['display_title'].apply(_clean_title)

                for idx in df_enriched[unmatched_mask].index:
                    product = _clean_title(df_enriched.at[idx, 'product_name'])
                    # Find catalog titles that are substrings of the product name
                    matches = cat_titles[
                        cat_titles['_clean'].apply(lambda c: c in product and len(c) > 5)
                    ]
                    if not matches.empty:
                        # Pick the longest matching title (most specific)
                        best = matches.loc[matches['_clean'].str.len().idxmax()]
                        df_enriched.at[idx, 'series'] = best['series']
                        df_enriched.at[idx, 'canonical_work_slug'] = best['canonical_work_slug']

                        # Infer edition format from product name when possible
                        product_lower = product
                        if 'hardcover' in product_lower:
                            df_enriched.at[idx, 'edition_format'] = 'deluxe hardcover'
                        elif 'paperback' in product_lower and 'deluxe' in product_lower:
                            df_enriched.at[idx, 'edition_format'] = 'deluxe paperback'

        # Stage 2b: Fuzzy title matching for still-unmatched products
        # Broad catch is intentional: fuzzy matching can fail in varied ways
        # (import errors, NoneType attributes, difflib edge cases) and we want
        # to continue gracefully with partial enrichment rather than crash.
        still_unmatched = df_enriched['series'].isna()
        if still_unmatched.any():
            try:
                unmatched_rows = df_enriched[still_unmatched].copy()
                unmatched_rows = unmatched_rows.rename(columns={'product_name': 'book_title'})
                for col in ['series', 'canonical_work_slug', 'edition_format']:
                    if col in unmatched_rows.columns:
                        unmatched_rows = unmatched_rows.drop(columns=[col])
                title_matched = _match_titles_to_catalog(unmatched_rows, catalog)
                title_matched = title_matched.rename(columns={'book_title': 'product_name'})

                # Update only the rows that got matched
                for idx in title_matched.index:
                    if pd.notna(title_matched.at[idx, 'series']):
                        df_enriched.at[idx, 'series'] = title_matched.at[idx, 'series']
                        df_enriched.at[idx, 'canonical_work_slug'] = title_matched.at[idx, 'canonical_work_slug']
                        if pd.notna(title_matched.at[idx, 'edition_format']):
                            df_enriched.at[idx, 'edition_format'] = title_matched.at[idx, 'edition_format']
            except Exception as e:
                print(f"[WARN] Fuzzy title matching failed: {e}")
                print("[WARN] Continuing without fuzzy enrichment for remaining products")

        df = df_enriched
        matched = df['series'].notna().sum()
        print(f"[INFO] Catalog enrichment: {matched}/{len(df)} products matched")
    else:
        df['series'] = None
        df['canonical_work_slug'] = df['product_name']
        df['edition_format'] = None

    # Select final columns matching fact_woo_sales schema
    final_columns = [
        'sale_date', 'period_start', 'period_end', 'source_platform',
        'product_name', 'sku', 'category',
        'items_sold', 'net_sales', 'orders_count',
        'canonical_work_slug', 'series', 'edition_format',
    ]
    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    print(f"[INFO] WooCommerce load complete: {len(df_result)} product records")
    return df_result