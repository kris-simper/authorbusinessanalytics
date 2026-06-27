"""Quick test script to verify ACX loader works with real data."""

import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from src.book_catalog import BookCatalog
from src.loaders import load_acx_report

# Paths
DATA_DIR = Path(__file__).parent / 'data'
ACX_FILE = DATA_DIR / 'raw' / 'acx-new' / 'Royalty_ACCT_S_D_Simper_86666_ACX_MONTHLY_Apr_2026.xlsx'

# Load catalog
print("=" * 50)
print("TESTING ACX LOADER")
print("=" * 50)

catalog = BookCatalog(DATA_DIR / 'catalog_products.csv')
catalog.load()

# Check if ACX file exists
if not ACX_FILE.exists():
    print(f"\n[ERROR] ACX file not found at: {ACX_FILE}")
    print("[INFO] Make sure you've copied your ACX .xlsx into data/raw/acx-new/")
    print("[INFO] Current data directory contents:")
    for item in DATA_DIR.rglob('*'):
        if item.is_file():
            print(f"  {item.relative_to(DATA_DIR)}")
else:
    # Run the loader
    print(f"\nLoading: {ACX_FILE.name}")
    df = load_acx_report(ACX_FILE, catalog=catalog)
    
    # Show results
    print(f"\n{'=' * 50}")
    print(f"RESULTS: {len(df)} rows loaded")
    print(f"{'=' * 50}")
    print(f"\nColumns: {list(df.columns)}")
    print(f"\nFirst 3 rows (key columns):")
    display_cols = ['book_identifier', 'book_title', 'region', 'quantity', 
                    'royalty_amount', 'sale_date', 'source_platform']
    available = [c for c in display_cols if c in df.columns]
    print(df[available].head(3).to_string())
    
    print(f"\nCatalog enrichment check:")
    if 'canonical_work_slug' in df.columns:
        matched = df['canonical_work_slug'].notna().sum()
        print(f"  Matched to catalog: {matched}/{len(df)}")
    
    print(f"\n✅ Test complete!")