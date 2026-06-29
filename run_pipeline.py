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
from src.kenp_loader import load_kenp_data
from src.patreon_loader import load_patreon_data
from src.woo_loader import load_woo_data
from src.aubooks_loader import load_aubooks_data
from src.currency import to_usd
from src.analyzer import init_database, init_kenp_table, populate_dim_books, init_patreon_table, init_woo_table, init_aubooks_table, ingest_dataframe, get_monthly_summary_query, get_series_performance_query, close_connection


def main():
    """
    Execute end-to-end author revenue analytics pipeline.
    
    Loads raw royalty exports from ACX, Amazon KDP, Patreon, WooCommerce,
    and Audiobooks Unleashed; normalizes currencies to USD via ECB rates;
    enriches transactions with book metadata from catalog; persists to
    SQLite warehouse; initializes analytical SQL queries.
    
    Pipeline flow:
        1. Reset database for fresh load
        2. Process all source platforms (sales → KENP → Patreon → WooCommerce → AU Books)
        3. Initialize SQLite tables (5 fact tables + 1 dimension table)
        4. Ingest normalized data
        5. Generate results summary
        6. Close connections cleanly
    
    Raises:
        FileNotFoundError: If required data directories or catalog are missing
        KeyError: If unexpected column names in input files
    """
    print("=" * 60)
    print("AUTHOR BUSINESS ANALYTICS PIPELINE")
    print("=" * 60)

    PROJECT_ROOT = Path(__file__).parent
    DATA_DIR = PROJECT_ROOT / 'data'
    CATALOG_FILE = DATA_DIR / 'catalog_products.csv'

    # Step 0: Reset database
    print("=" * 60)
    print("STEP 0: RESETTING DATABASE")
    print("=" * 60)

    db_path = Path("data/author_analytics.db")
    if db_path.exists():
        db_path.unlink()
        print("[INFO] Existing database deleted for fresh load")
    else:
        print("[INFO] No existing database found, starting fresh")
        
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
    print(f"\n[INFO] Combined {len(df)} total sales records across all platforms")

    # Step 2b: Load KENP page reads (separate fact table)
    print("\n" + "=" * 60)
    print("STEP 2B: PROCESSING KENP PAGE READS")
    print("=" * 60)

    KDP_FILE = KDP_FOLDER / "Lifetime Report.xlsx"
    if KDP_FILE.exists():
        df_kenp = load_kenp_data(KDP_FILE, catalog=catalog)
        print(f"[INFO] KENP reads loaded: {len(df_kenp)} records")
    else:
        df_kenp = None
        print("[WARN] KDP file not found, skipping KENP processing")
        
    # Step 2c: Process Patreon earnings
    print("\n" + "=" * 60)
    print("STEP 2C: PATREON EARNINGS")
    print("=" * 60)

    patreon_dir = Path("data/raw/patreon")
    patreon_files = sorted(patreon_dir.glob("*.csv"))

    if patreon_files:
        patreon_dfs = []
        for pf in patreon_files:
            df_pat = load_patreon_data(pf)
            patreon_dfs.append(df_pat)

        df_patreon = pd.concat(patreon_dfs, ignore_index=True)

        # Deduplicate in case of overlapping exports
        df_patreon = df_patreon.drop_duplicates(subset=['sale_date'])

        print(f"\n[Patreon] {len(df_patreon)} unique monthly records ready for ingestion")
    else:
        print("[WARN] No Patreon CSV files found in data/raw/patreon/")
        df_patreon = pd.DataFrame()

    # Step 2d: Process WooCommerce Sales
    print("\n" + "=" * 60)
    print("STEP 2D: WOOCOMMERCE SALES")
    print("=" * 60)

    woo_dir = Path("data/raw/woocommerce")
    woo_files = sorted(woo_dir.glob("*.csv"))

    if woo_files:
        woo_dfs = []
        non_empty_count = 0
        for wf in woo_files:
            df_woo = load_woo_data(wf, catalog=catalog)
            if not df_woo.empty:
                woo_dfs.append(df_woo)
                non_empty_count += 1
                print(f"[INFO] {wf.name}: {len(df_woo)} products ({df_woo['items_sold'].sum():,} units)")

        if woo_dfs:
            # Concatenate all exports first
            df_woocommerce = pd.concat(woo_dfs, ignore_index=True)

            # Check for overlapping date ranges on same product
            dup_check = df_woocommerce.groupby(['product_name', 'period_start', 'period_end']).size()
            actual_duplicates = dup_check[dup_check > 1].count()
            
            if actual_duplicates > 0:
                print(f"[WARN] Found {actual_duplicates} products appearing in multiple files "
                      f"(overlapping date ranges). Aggregating by product + period...")
                
                # Group by product and date range, sum numeric columns
                df_woocommerce = df_woocommerce.groupby(['product_name', 'period_start', 'period_end']).agg({
                    'source_platform': 'first',
                    'sku': 'first',
                    'category': 'first',
                    'items_sold': 'sum',
                    'net_sales': 'sum',
                    'orders_count': 'sum',
                    'canonical_work_slug': 'first',
                    'series': 'first',
                    'edition_format': 'first',
                }).reset_index()
            else:
                print("[INFO] No duplicate product-period combinations detected")

            print(f"\n[WooCommerce] {len(df_woocommerce)} unique product-period records "
                  f"across {non_empty_count} files ready for ingestion")
        else:
            print("[WARN] No valid WooCommerce data loaded")
            df_woocommerce = pd.DataFrame()
    else:
        print("[WARN] No WooCommerce CSV files found in data/raw/woocommerce/")
        df_woocommerce = pd.DataFrame()

    # Step 2e: Process Audiobooks Unleashed
    print("\n" + "=" * 60)
    print("STEP 2E: AUDIOBOOKS UNLEASHED")
    print("=" * 60)

    au_dir = Path("data/raw/audiobooks-unleashed")
    au_files = sorted(au_dir.glob("*.pdf"))

    if au_files:
        au_dfs = []
        for af in au_files:
            df_au = load_aubooks_data(af, catalog=catalog)
            if not df_au.empty:
                au_dfs.append(df_au)

        if au_dfs:
            df_aubooks = pd.concat(au_dfs, ignore_index=True)
            print(f"\n[Audiobooks Unleashed] {len(df_aubooks)} total records "
                  f"ready for ingestion")
        else:
            print("[WARN] No valid AU Books data loaded")
            df_aubooks = pd.DataFrame()
    else:
        print("[WARN] No AU Books PDF files found in data/raw/audiobooks-unleashed/")
        df_aubooks = pd.DataFrame()
    
    # Step 3: Currency normalization (sales data)
    print("\n" + "=" * 60)
    print("STEP 3: CURRENCY NORMALIZATION")
    print("=" * 60)

    df['currency'] = df.get('currency', pd.Series(dtype=str)).fillna('USD')

    print("[INFO] Currency distribution (sales):")
    print(df['currency'].value_counts().to_string())

    print("\n[INFO] Converting sales monetary values to USD...")
    df['royalty_amount_usd'] = df.apply(
        lambda r: to_usd(r['royalty_amount'], r['currency'], r['sale_date']),
        axis=1
    )
    df['price_usd'] = df.apply(
        lambda r: to_usd(r['price'], r['currency'], r['sale_date']),
        axis=1
    )

    converted = df['royalty_amount_usd'].notna().sum()
    print(f"[INFO] {converted}/{len(df)} sales records converted to USD")

    # Step 4: Display results summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {len(df)} sales rows + {len(df_kenp) if df_kenp is not None else 0} KENP rows")
    print(f"{'=' * 60}")

    print(f"\nMonthly breakdown (sales only):")
    monthly = df.groupby(df['sale_date'].dt.to_period('M')).agg({
        'quantity': 'sum',
        'royalty_amount_usd': 'sum',
        'source_platform': 'first'
    }).round(2)
    monthly.index = monthly.index.astype(str)
    print(monthly.to_string())

    if df_kenp is not None and len(df_kenp) > 0:
        print(f"\nKENP monthly summary:")
        kenp_monthly = df_kenp.groupby(df_kenp['sale_date'].dt.to_period('M')).agg({
            'page_count': 'sum',
            'royalty_amount_usd': 'sum'
        }).round(2)
        kenp_monthly.index = kenp_monthly.index.astype(str)
        print(kenp_monthly.tail(12).to_string())

    print(f"\nPlatform breakdown:")
    platform_breakdown = df.groupby('source_platform').agg({
        'quantity': 'sum',
        'royalty_amount_usd': 'sum'
    })
    print(platform_breakdown.to_string())

    matched = df['series'].notna().sum()
    total = len(df)
    match_rate = (matched / total * 100) if total > 0 else 0
    print(f"\nCatalog enrichment (sales): {matched}/{total} rows matched ({match_rate:.1f}%)")

    if df_kenp is not None:
        kenp_matched = df_kenp['series'].notna().sum()
        kenp_total = len(df_kenp)
        kenp_rate = (kenp_matched / kenp_total * 100) if kenp_total > 0 else 0
        print(f"Catalog enrichment (KENP): {kenp_matched}/{kenp_total} rows matched ({kenp_rate:.1f}%)")

    # Step 5: Write to SQLite database
    print("\n" + "=" * 60)
    print("STEP 5: INITIALIZING DATABASE")
    print("=" * 60)

    conn = init_database()
    populate_dim_books(conn, catalog)
    
    init_kenp_table(conn)

    # Ingest sales data
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
    print(f"[INFO] Filtering sales DataFrame to {len(df_for_db.columns)} compatible columns")
    ingest_dataframe(conn, df_for_db)

    # Ingest KENP data into separate table
    if df_kenp is not None and len(df_kenp) > 0:
        ingest_dataframe(conn, df_kenp, table_name='kenp_reads')
        
    # Patreon table
    init_patreon_table(conn)
    if not df_patreon.empty:
        patreon_rows = ingest_dataframe(conn, df_patreon, 'fact_patreon_earnings')

    # WooCommerce table
    init_woo_table(conn)
    if not df_woocommerce.empty:
        woo_rows = ingest_dataframe(conn, df_woocommerce, 'fact_woo_sales')

    # Audiobooks Unleashed table
    init_aubooks_table(conn)
    if not df_aubooks.empty:
        au_rows = ingest_dataframe(conn, df_aubooks, 'fact_aubooks_sales')
        
    # Verify
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