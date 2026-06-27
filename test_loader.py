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

# Import the batch processor
from src.loaders import load_all_acx_reports

# Set the folder path (not single file)
ACX_FOLDER = DATA_DIR / 'raw' / 'acx-new'

# Run batch processing
df = load_all_acx_reports(ACX_FOLDER, catalog=catalog)

# Show results
print(f"\n{'=' * 50}")
print(f"RESULTS: {len(df)} total rows loaded")
print(f"{'=' * 50}")

# Show monthly breakdown
print(f"\nMonthly breakdown:")
monthly = df.groupby(df['sale_date'].dt.to_period('M')).agg({
    'quantity': 'sum',
    'royalty_amount': 'sum'
}).round(2)
print(monthly.to_string())

# Show catalog match rate
matched = df['series'].notna().sum()
print(f"\nCatalog enrichment: {matched}/{len(df)} rows matched")
print(f"\n✅ Batch test complete!")