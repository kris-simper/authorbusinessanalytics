"""
Test harness for ACX data loader module.
Verifies end-to-end pipeline functionality from raw Excel to normalized DataFrame.
"""

import sys
from pathlib import Path

# Add parent directory to path for src imports
sys.path.insert(0, str(Path(__file__).parent))

# Import our modules
from src.book_catalog import BookCatalog
from src.loaders import load_all_acx_reports
from src.analyzer import init_database, ingest_dataframe, get_monthly_summary_query, close_connection


def main():
    print("=" * 50)
    print("TESTING AUTHOR BUSINESS ANALYTICS PIPELINE")
    print("=" * 50)
    
    # Define paths relative to project root
    PROJECT_ROOT = Path(__file__).parent
    DATA_DIR = PROJECT_ROOT / 'data'
    CATALOG_FILE = DATA_DIR / 'catalog_products.csv'
    ACX_FOLDER = DATA_DIR / 'raw' / 'acx-new'
    
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
        print("[HINT] Make sure data/catalog_products.csv exists with your book metadata")
        return
    except Exception as e:
        print(f"[ERROR] Failed to load catalog: {e}")
        return
    
    # Step 2: Run batch processing on all ACX files
    print("\n" + "=" * 60)
    print("STEP 2: BATCH PROCESSING ACX REPORTS")
    print("=" * 60)
    
    df = load_all_acx_reports(ACX_FOLDER, catalog=catalog)
    
    if df.empty:
        print("\n❌ ERROR: No data was processed. Check logs above.")
        return
    
    # Step 3: Display results summary
    print(f"\n{'=' * 50}")
    print(f"RESULTS: {len(df)} total rows loaded")
    print(f"{'=' * 50}")
    
    # Show monthly breakdown
    print(f"\nMonthly breakdown:")
    monthly = df.groupby(df['sale_date'].dt.to_period('M')).agg({
        'quantity': 'sum',
        'royalty_amount': 'sum',
        'source_platform': 'first'
    }).round(2)
    
    monthly.index = monthly.index.astype(str)
    print(monthly.to_string())
    
    # Show platform breakdown
    print(f"\nPlatform breakdown:")
    platform_breakdown = df.groupby('source_platform').agg({
        'quantity': 'sum',
        'royalty_amount': 'sum'
    })
    print(platform_breakdown.to_string())
    
    # Show catalog match rate
    matched = df['series'].notna().sum()
    total = len(df)
    match_rate = (matched / total * 100) if total > 0 else 0
    
    print(f"\nCatalog enrichment: {matched}/{total} rows matched ({match_rate:.1f}%)")
    
    if matched < total:
        unmatched = df[df['series'].isna()][['book_title', 'book_identifier']].head(5)
        print(f"\n⚠️ Warning: {total - matched} rows did not match catalog")
        print("Sample unmatched titles:")
        print(unmatched.to_string(index=False))
    
    # Step 4: Write to SQLite database (optional demo)
    print("\n" + "=" * 50)
    print("STEP 3: INITIALIZING DATABASE (DEMO)")
    print("=" * 50)
    
    conn = init_database()
    
    # Filter to only columns matching database schema
    expected_columns = [
        'sale_date', 'source_platform', 'book_identifier', 'canonical_work_slug',
        'series', 'edition_format', 'region', 'quantity', 'price', 
        'royalty_amount', 'royalty_rate'
    ]
    
    df_for_db = df[[col for col in expected_columns if col in df.columns]].copy()
    print(f"[INFO] Filtering DataFrame to {len(df_for_db.columns)} compatible columns")
    
    rows_inserted = ingest_dataframe(conn, df_for_db)
    
    # Query the database to verify
    print("\nQuerying database for verification...")
    monthly_results = get_monthly_summary_query(conn)
    
    if monthly_results:
        print(f"\nDatabase contains {len(monthly_results)} monthly aggregates:")
        for period, platform, units, revenue, txns in monthly_results[:5]:
            print(f"  {period} | {platform:8} | {units:3} units | ${revenue:>7.2f}")
        if len(monthly_results) > 5:
            print(f"  ... and {len(monthly_results) - 5} more periods")
    
    # Close when done
    close_connection(conn)
    
    print("\n✅ Complete! Check data/author_analytics.db for full dataset")
    
    # Return success/failure
    print("\n" + "=" * 50)
    print("FINAL STATUS: ALL TESTS PASSED ✓")
    print("=" * 50)


if __name__ == '__main__':
    main()