"""
Pipeline entry point for Author Business Analytics.
Loads all data sources, normalizes currency to USD, and ingests to SQLite.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from src.book_catalog import BookCatalog
from src.loaders import load_all_acx_reports, load_all_acx_legacy_reports, load_all_kdp_reports
from src.analyzer import init_database, ingest_dataframe, get_monthly_summary_query, close_connection
from src.currency import to_usd


def main():
    print("=" * 60)
    print("AUTHOR BUSINESS ANALYTICS PIPELINE")
    print("=" * 60)

    PROJECT_ROOT = Path(__file__).parent
    DATA_DIR = PROJECT_ROOT / 'data'
    CATALOG_FILE = DATA_DIR / 'catalog_products.csv'

    # Step 1: Load the book catalog
    print(f"\nLoading catalog from {CATALOG_FILE}...")
    try:
        catalog = BookCatalog(catalog_path=str(CATALOG_FILE))
        catalog.load()
        if catalog.raw_catalog is None or catalog.match_table is None:
            raise ValueError("Failed to load catalog identifiers")
        num_editions = len(catalog.raw_catalog)
        num_identifiers = len(catalog.match_table)
        print(f"[INFO] Catalog loaded: {num_editions} editions, {num_identifiers} total identifiers indexed")
    except FileNotFoundError:
        print(f"[ERROR] Catalog not found at {CATALOG_FILE}")
        return
    except Exception as e:
        print(f"[ERROR] Failed to load catalog: {e}")
        return

    # Step 2: Load all data sources
    print("\n" + "=" * 60)
    print("STEP 2: BATCH PROCESSING ALL REPORTS")
    print("=" * 60)

    ACX_FOLDER_NEW = DATA_DIR / 'raw' / 'acx-new'
    ACX_FOLDER_OLD = DATA_DIR / 'raw' / 'acx-old'
    KDP_FOLDER = DATA_DIR / 'raw' / 'amazon-kdp'

    df_new = load_all_acx_reports(ACX_FOLDER_NEW, catalog=catalog)
    df_old = load_all_acx_legacy_reports(ACX_FOLDER_OLD, catalog=catalog)
    df_kdp = load_all_kdp_reports(KDP_FOLDER, catalog=catalog)

    all_dfs = [df for df in [df_new, df_old, df_kdp] if not df.empty]

    if not all_dfs:
        print("\n[ERROR] No data was processed from any source.")
        return

    df = pd.concat(all_dfs, ignore_index=True)
    print(f"\n[INFO] Combined {len(df)} total records across all platforms")

    # Step 3: Currency normalization
    print("\n" + "=" * 60)
    print("STEP 3: CURRENCY NORMALIZATION")
    print("=" * 60)

    df['currency'] = df.get('currency', pd.Series(dtype=str)).fillna('USD')

    print("[INFO] Currency distribution:")
    print(df['currency'].value_counts().to_string())

    print("\n[INFO] Converting monetary values to USD...")
    df['royalty_amount_usd'] = df.apply(
        lambda r: to_usd(r['royalty_amount'], r['currency'], r['sale_date']),
        axis=1
    )
    df['price_usd'] = df.apply(
        lambda r: to_usd(r['price'], r['currency'], r['sale_date']),
        axis=1
    )

    converted = df['royalty_amount_usd'].notna().sum()
    print(f"[INFO] {converted}/{len(df)} records converted to USD")

    # Step 4: Display results summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {len(df)} total rows loaded")
    print(f"{'=' * 60}")

    print(f"\nMonthly breakdown:")
    monthly = df.groupby(df['sale_date'].dt.to_period('M')).agg({
        'quantity': 'sum',
        'royalty_amount_usd': 'sum',
        'source_platform': 'first'
    }).round(2)
    monthly.index = monthly.index.astype(str)
    print(monthly.to_string())

    print(f"\nPlatform breakdown:")
    platform_breakdown = df.groupby('source_platform').agg({
        'quantity': 'sum',
        'royalty_amount_usd': 'sum'
    })
    print(platform_breakdown.to_string())

    matched = df['series'].notna().sum()
    total = len(df)
    match_rate = (matched / total * 100) if total > 0 else 0
    print(f"\nCatalog enrichment: {matched}/{total} rows matched ({match_rate:.1f}%)")

    if matched < total:
        unmatched = df[df['series'].isna()][['book_title', 'book_identifier']].head(5)
        print(f"\n[WARN] {total - matched} rows did not match catalog")
        print("Sample unmatched titles:")
        print(unmatched.to_string(index=False))

    # Step 5: Write to SQLite database
    print("\n" + "=" * 60)
    print("STEP 5: INITIALIZING DATABASE")
    print("=" * 60)

    conn = init_database()

    expected_columns = [
        'sale_date', 'source_platform', 'book_identifier', 'canonical_work_slug',
        'series', 'edition_format', 'region',
        'currency',
        'quantity',
        'price', 'price_usd',
        'royalty_amount', 'royalty_amount_usd',
        'royalty_rate',
    ]

    df_for_db = df[[col for col in expected_columns if col in df.columns]].copy()
    print(f"[INFO] Filtering DataFrame to {len(df_for_db.columns)} compatible columns")

    rows_inserted = ingest_dataframe(conn, df_for_db)

    print("\nQuerying database for verification...")
    monthly_results = get_monthly_summary_query(conn)

    if monthly_results:
        print(f"\nDatabase contains {len(monthly_results)} monthly aggregates:")
        for period, platform, units, revenue, txns in monthly_results[:5]:
            print(f"  {period} | {platform:8} | {units:3} units | ${revenue:>7.2f} USD")
        if len(monthly_results) > 5:
            print(f"  ... and {len(monthly_results) - 5} more periods")

    close_connection(conn)

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()