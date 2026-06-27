"""Quick debug script to see all titles from ACX report."""

import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.book_catalog import BookCatalog
from src.loaders import load_acx_report

# Load catalog
catalog = BookCatalog()
catalog.load()

# Load ACX data
df = load_acx_report(
    Path('data/raw/acx-new/Royalty_ACCT_S_D_Simper_86666_ACX_MONTHLY_Apr_2026.xlsx'),
    catalog=catalog
)

print('\n' + '=' * 70)
print('ALL TITLES AND MATCH STATUS')
print('=' * 70)

for idx, row in df.iterrows():
    status = 'MATCHED ✓' if pd.notna(row.get('series')) else 'NO MATCH ✗'
    series_info = row.get('series', '') or 'N/A'
    
    # Truncate long titles for readability
    title_display = str(row['book_title'])[:50] + '...' if len(str(row['book_title'])) > 50 else str(row['book_title'])
    
    print(f"{status} | {title_display}")
    print(f"       Series: {series_info}")
    print()

print('=' * 70)
matched_count = df['series'].notna().sum()
total_count = len(df)
print(f"SUMMARY: {matched_count}/{total_count} titles matched to catalog")
print('=' * 70)