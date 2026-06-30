"""
Pipeline entry point for Author Business Analytics.

Loads royalty data from 10 platforms, normalizes currencies to USD via
historical ECB rates, enriches transactions with book metadata from
catalog, and persists to a SQLite star-schema warehouse with 10 fact
tables and 1 dimension table.

Platforms: ACX, Amazon KDP (sales + KENP), Patreon, WooCommerce,
Audiobooks Unleashed, Draft2Digital, Barnes & Noble Press, Kobo Store,
Kobo Plus (subscription reads), IngramSpark.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from src.book_catalog import BookCatalog
from src.amazon_loader import load_all_acx_reports, load_all_acx_legacy_reports, load_all_kdp_reports
from src.kenp_loader import load_kenp_data
from src.patreon_loader import load_patreon_data
from src.woo_loader import load_woo_data
from src.aubooks_loader import load_aubooks_data
from src.d2d_loader import load_d2d_data
from src.bnl_loader import load_bnl_data
from src.kobo_loader import load_kobo_data, load_kobo_plus_data
from src.ingram_loader import load_ingram_data
from src.currency import to_usd
from src.analyzer import (
    init_database, init_kenp_table, populate_dim_books,
    init_patreon_table, init_woo_table, init_aubooks_table,
    init_d2d_table, init_bnl_table, init_kobo_table,
    init_kobo_plus_table, init_ingram_table,
    ingest_dataframe, get_monthly_summary_query,
    close_connection,
)


def main() -> None:
    """
    Execute end-to-end author revenue analytics pipeline.
    
    Loads raw royalty exports from 10 platforms, normalizes currencies
    to USD via ECB rates, enriches transactions with book metadata from
    catalog, and persists to a SQLite warehouse with 10 fact tables
    and 1 conformed dimension table.
    
    Pipeline flow:
        1. Reset database for fresh load
        2. Load catalog and process all 10 source platforms
        3. Normalize all currencies to USD
        4. Display results summary
        5. Initialize SQLite tables and ingest all data
        6. Verify and close connections cleanly
    
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
        df_kenp = pd.DataFrame()
        print("[WARN] KDP file not found, skipping KENP processing")
        
    # Step 2c: Process Patreon earnings
    print("\n" + "=" * 60)
    print("STEP 2C: PATREON EARNINGS")
    print("=" * 60)

    patreon_dir = DATA_DIR / 'raw' / 'patreon'
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

    woo_dir = DATA_DIR / 'raw' / 'woocommerce'
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

    au_dir = DATA_DIR / 'raw' / 'audiobooks-unleashed'
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
            print("[WARN] No valid Audiobooks Unleashed data loaded")
            df_aubooks = pd.DataFrame()
    else:
        print("[WARN] No Audiobooks Unleashed PDF files found in data/raw/audiobooks-unleashed/")
        df_aubooks = pd.DataFrame()
    
    # Step 2f: Process Draft2Digital
    print("\n" + "=" * 60)
    print("STEP 2F: DRAFT2DIGITAL SALES")
    print("=" * 60)

    d2d_dir = DATA_DIR / 'raw' / 'draft2digital'
    d2d_files = sorted(d2d_dir.glob("*.csv"))

    if d2d_files:
        d2d_dfs = []
        for d2d_file in d2d_files:
            df_d2d = load_d2d_data(d2d_file, catalog=catalog)
            if not df_d2d.empty:
                d2d_dfs.append(df_d2d)

        if d2d_dfs:
            df_draft2digital = pd.concat(d2d_dfs, ignore_index=True)
            print(f"\n[Draft2Digital] {len(df_draft2digital)} distributor-level records "
                  f"ready for ingestion")
        else:
            print("[WARN] No valid D2D data loaded")
            df_draft2digital = pd.DataFrame()
    else:
        print("[WARN] No D2D CSV files found in data/raw/draft2digital/")
        df_draft2digital = pd.DataFrame()
     
    # Step 2g: Process Barnes & Noble Press
    print("\n" + "=" * 60)
    print("STEP 2G: BARNES & NOBLE PRESS")
    print("=" * 60)

    bnl_dir = DATA_DIR / 'raw' / 'barnes-noble'
    bnl_files = sorted(bnl_dir.glob("*.csv"))

    if bnl_files:
        bnl_dfs = []
        for bf in bnl_files:
            df_bnl = load_bnl_data(bf, catalog=catalog)
            if not df_bnl.empty:
                bnl_dfs.append(df_bnl)

        if bnl_dfs:
            df_barnes_noble = pd.concat(bnl_dfs, ignore_index=True)
            print(f"\n[B&N] {len(df_barnes_noble)} transaction records ready for processing")
        else:
            print("[WARN] No valid B&N data loaded")
            df_barnes_noble = pd.DataFrame()
    else:
        print("[WARN] No B&N CSV files found in data/raw/barnes-noble/")
        df_barnes_noble = pd.DataFrame()
    
    # Step 2h: Process Kobo Store
    print("\n" + "=" * 60)
    print("STEP 2H: KOBO STORE")
    print("=" * 60)

    kobo_dir = DATA_DIR / 'raw' / 'kobo'
    kobo_files = sorted(kobo_dir.glob("*PUB*.xlsx"))

    if kobo_files:
        kobo_dfs = []
        for kf in kobo_files:
            df_kobo = load_kobo_data(kf, catalog=catalog)
            if not df_kobo.empty:
                kobo_dfs.append(df_kobo)

        if kobo_dfs:
            df_kobo_store = pd.concat(kobo_dfs, ignore_index=True)
            print(f"\n[Kobo] {len(df_kobo_store)} transaction records ready for processing")
        else:
            print("[WARN] No valid Kobo data loaded")
            df_kobo_store = pd.DataFrame()
    else:
        print("[WARN] No Kobo PUB xlsx files found in data/raw/kobo/")
        df_kobo_store = pd.DataFrame()

    # Step 2i: Process Kobo Plus (subscription reads)
    print("\n" + "=" * 60)
    print("STEP 2I: KOBO PLUS (SUBSCRIPTION READS)")
    print("=" * 60)

    kobo_plus_dir = Path("data/raw/kobo")
    kobo_plus_files = sorted(kobo_plus_dir.glob("*SUBS*.xlsx"))

    if kobo_plus_files:
        kobo_plus_dfs = []
        for kpf in kobo_plus_files:
            df_kobo_plus = load_kobo_plus_data(kpf, catalog=catalog)
            if not df_kobo_plus.empty:
                kobo_plus_dfs.append(df_kobo_plus)

        if kobo_plus_dfs:
            df_kobo_plus = pd.concat(kobo_plus_dfs, ignore_index=True)
            print(f"\n[Kobo Plus] {len(df_kobo_plus)} subscription read records ready for processing")
        else:
            print("[WARN] No valid Kobo Plus data loaded")
            df_kobo_plus = pd.DataFrame()
    else:
        print("[WARN] No Kobo Plus SUBS xlsx files found in data/raw/kobo/")
        df_kobo_plus = pd.DataFrame()

    # Step 2j: Process IngramSpark
    print("\n" + "=" * 60)
    print("STEP 2J: INGRAMSPARK")
    print("=" * 60)

    ingram_dir = DATA_DIR / 'raw' / 'ingram-spark'
    ingram_files = sorted(ingram_dir.glob("*.xls"))

    if ingram_files:
        ingram_dfs = []
        for ifile in ingram_files:
            df_ingram = load_ingram_data(ifile, catalog=catalog)
            if not df_ingram.empty:
                ingram_dfs.append(df_ingram)

        if ingram_dfs:
            df_ingram = pd.concat(ingram_dfs, ignore_index=True)
            print(f"\n[Ingram] {len(df_ingram)} compensation records ready for processing")
        else:
            print("[WARN] No valid Ingram data loaded")
            df_ingram = pd.DataFrame()
    else:
        print("[WARN] No Ingram .xls files found in data/raw/ingram-spark/")
        df_ingram = pd.DataFrame()
        
    # Step 3: Currency normalization (ALL sales data including D2D)
    print("\n" + "=" * 60)
    print("STEP 3: CURRENCY NORMALIZATION")
    print("=" * 60)

    # ACX/KDP conversion
    df['currency'] = df.get('currency', pd.Series(dtype=str)).fillna('USD')
    
    # Add D2D to currency normalization list
    if not df_draft2digital.empty:
        df_draft2digital['currency'] = df_draft2digital.get('currency', pd.Series(dtype=str)).fillna('USD')
        print(f"[INFO] D2D currency distribution:")
        print(df_draft2digital['currency'].value_counts().to_string())
    
    print("\n[INFO] Converting sales monetary values to USD...")
    
    # Convert ACX/KDP sales
    df['royalty_amount_usd'] = df.apply(
        lambda r: to_usd(r['royalty_amount'], r['currency'], r['sale_date']),
        axis=1
    )
    df['price_usd'] = df.apply(
        lambda r: to_usd(r['price'], r['currency'], r['sale_date']),
        axis=1
    )
    
    # Convert D2D sales
    if not df_draft2digital.empty:
        df_draft2digital['royalty_amount_usd'] = df_draft2digital.apply(
            lambda r: to_usd(r['royalty_amount'], r['currency'], r['sale_date']),
            axis=1
        )
        converted_d2d = df_draft2digital['royalty_amount_usd'].notna().sum()
        pct = (converted_d2d / len(df_draft2digital) * 100) if len(df_draft2digital) > 0 else 0
        print(f"[INFO] {converted_d2d}/{len(df_draft2digital)} D2D records converted to USD ({pct:.1f}%)")

    # NEW: Convert B&N royalty to USD (uses payment_currency since that's what royalty is denominated in)
    if not df_barnes_noble.empty:
        df_barnes_noble['royalty_amount_usd'] = df_barnes_noble.apply(
            lambda r: to_usd(r['royalty_amount'], r['payment_currency'], r['sale_date']),
            axis=1
        )
        converted_bnl = df_barnes_noble['royalty_amount_usd'].notna().sum()
        pct = (converted_bnl / len(df_barnes_noble) * 100) if len(df_barnes_noble) > 0 else 0
        print(f"[INFO] {converted_bnl}/{len(df_barnes_noble)} B&N records converted to USD ({pct:.1f}%)")

    # Convert Kobo Store royalty to USD
    if not df_kobo_store.empty:
        df_kobo_store['royalty_amount_usd'] = df_kobo_store.apply(
            lambda r: to_usd(r['royalty_amount'], r['currency'], r['sale_date']),
            axis=1
        )
        converted_kobo = df_kobo_store['royalty_amount_usd'].notna().sum()
        pct = (converted_kobo / len(df_kobo_store) * 100) if len(df_kobo_store) > 0 else 0
        print(f"[INFO] {converted_kobo}/{len(df_kobo_store)} Kobo records converted to USD ({pct:.1f}%)")

    # Convert Kobo Plus royalty to USD
    if not df_kobo_plus.empty:
        df_kobo_plus['royalty_amount_usd'] = df_kobo_plus.apply(
            lambda r: to_usd(r['royalty_amount'], r['currency'], r['sale_date']),
            axis=1
        )
        converted_kp = df_kobo_plus['royalty_amount_usd'].notna().sum()
        pct = (converted_kp / len(df_kobo_plus) * 100) if len(df_kobo_plus) > 0 else 0
        print(f"[INFO] {converted_kp}/{len(df_kobo_plus)} Kobo Plus records converted to USD ({pct:.1f}%)")

    # Convert Ingram royalty to USD
    if not df_ingram.empty:
        df_ingram['royalty_amount_usd'] = df_ingram.apply(
            lambda r: to_usd(r['royalty_amount'], r['currency'], r['sale_date']),
            axis=1
        )
        converted_ingram = df_ingram['royalty_amount_usd'].notna().sum()
        pct = (converted_ingram / len(df_ingram) * 100) if len(df_ingram) > 0 else 0
        print(f"[INFO] {converted_ingram}/{len(df_ingram)} Ingram records converted to USD ({pct:.1f}%)")
        
    # Step 4: Display results summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {len(df)} sales rows + {len(df_kenp)} KENP rows")
    print(f"{'=' * 60}")

    print(f"\nMonthly breakdown (sales only):")
    monthly = df.groupby(df['sale_date'].dt.to_period('M')).agg({
        'quantity': 'sum',
        'royalty_amount_usd': 'sum',
        'source_platform': 'first'
    }).round(2)
    monthly.index = monthly.index.astype(str)
    print(monthly.to_string())

    if not df_kenp.empty:
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

    if not df_kenp.empty:
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
    if not df_kenp.empty:
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
        
    # Draft2Digital table
    init_d2d_table(conn)
    if not df_draft2digital.empty:
        d2d_rows = ingest_dataframe(conn, df_draft2digital, 'fact_d2d_sales')
        
    # Barnes & Noble table
    init_bnl_table(conn)
    if not df_barnes_noble.empty:
        bnl_rows = ingest_dataframe(conn, df_barnes_noble, 'fact_bnl_sales')
        
    # Kobo Store table
    init_kobo_table(conn)
    if not df_kobo_store.empty:
        kobo_rows = ingest_dataframe(conn, df_kobo_store, 'fact_kobo_sales')     

    # Kobo Plus reads table
    init_kobo_plus_table(conn)
    if not df_kobo_plus.empty:
        kobo_plus_rows = ingest_dataframe(conn, df_kobo_plus, 'fact_kobo_plus_reads')

    # IngramSpark table
    init_ingram_table(conn)
    if not df_ingram.empty:
        ingram_rows = ingest_dataframe(conn, df_ingram, 'fact_ingram_sales')
        
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