"""Deep diagnostic of legacy ACX Summary sheet."""
from pathlib import Path
import pandas as pd

ACX_OLD_FOLDER = Path("data/raw/acx-old")
files = list(ACX_OLD_FOLDER.glob("*.xls"))

if not files:
    print("[ERROR] No .xls files found in data/raw/acx-old/")
    exit()

filepath = files[0]
print(f"[INFO] Inspecting Summary sheet: {filepath.name}")
print("=" * 60)

df = pd.read_excel(filepath, engine='xlrd', sheet_name='Summary', header=None)

print(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns\n")

# Dump every single row
for i in range(len(df)):
    row_vals = []
    for j in range(df.shape[1]):
        val = df.iloc[i, j]
        if pd.notna(val):
            row_vals.append(f"[{j}]={val}")
    if row_vals:
        print(f"Row {i}: {' | '.join(row_vals)}")

print("\n" + "=" * 60)