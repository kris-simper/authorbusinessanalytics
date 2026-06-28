"""Diagnose the structure of legacy ACX format (.xls) files."""
from pathlib import Path
import pandas as pd

ACX_OLD_FOLDER = Path("data/raw/acx-old")

files = list(ACX_OLD_FOLDER.glob("*.xls")) + list(ACX_OLD_FOLDER.glob("*.xlsx"))

if not files:
    print("[ERROR] No .xls or .xlsx files found in data/raw/acx-old/")
    print("Place at least one pre-April 2024 ACX report there and re-run.")
    exit()

filepath = files[0]
print(f"[INFO] Inspecting: {filepath.name}")
print("=" * 60)

# Determine engine based on extension
if filepath.suffix == '.xls':
    engine = 'xlrd'
else:
    engine = 'openpyxl'

# Get sheet names
xl = pd.ExcelFile(filepath, engine=engine)
print(f"\nSheet names: {xl.sheet_names}")

# Inspect each sheet
for sheet_name in xl.sheet_names:
    print(f"\n--- Sheet: '{sheet_name}' ---")

    df = pd.read_excel(filepath, engine=engine, sheet_name=sheet_name, header=None)

    if df.empty:
        print("  [EMPTY SHEET]")
        continue

    print(f"  Shape: {df.shape[0]} rows x {df.shape[1]} columns")

    # Print first 3 rows raw (no headers) to see structure
    for i in range(min(3, len(df))):
        row_vals = [str(v)[:30] if pd.notna(v) else 'None' for v in df.iloc[i]]
        print(f"  Row {i}: {row_vals}")

    # Count non-empty rows
    non_empty = df.dropna(how='all')
    print(f"  Non-empty rows: {len(non_empty)}")

print("\n" + "=" * 60)
print("[DONE] Paste this output back so we can design the legacy loader.")