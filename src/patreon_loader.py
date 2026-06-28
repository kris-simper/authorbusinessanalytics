"""
Patreon earnings loader for monthly membership income.

Parses the Patreon monthly earnings breakdown CSV and maps it to the
fact_patreon_earnings table. All amounts are in the currency reported
by Patreon (typically USD for US-based creators).
"""

import pandas as pd
from pathlib import Path


# Mapping Patreon CSV columns to database column names
COLUMN_MAP = {
    'Month - successful transactions': 'sale_date',
    'Currency': 'currency',
    'Membership gross earnings - Web and Android': 'gross_web_android',
    'Membership gross earnings - iOS app': 'gross_ios',
    'Total gross earnings': 'gross_total',
    'Patreon platform fees': 'platform_fees',
    'Payment processing fees': 'processing_fees',
    'Currency exchange fee': 'exchange_fee',
    'iOS app fee': 'ios_app_fee',
    'Merch costs (items + shipping)': 'merch_costs',
    'Total payment processing fees': 'total_processing_fees',
    'Refunds': 'refunds',
    'Patreon adjustments': 'adjustments',
    'Recovered payments': 'recovered_payments',
    'Total net earnings': 'net_earnings',
}


def load_patreon_data(filepath):
    """
    Load Patreon monthly earnings CSV.

    Args:
        filepath: Path to the Patreon earnings CSV

    Returns:
        DataFrame with renamed columns ready for database ingestion
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading Patreon data from {filepath.name}")

    # Patreon exports are typically clean UTF-8 CSVs
    try:
        df = pd.read_csv(filepath, encoding='utf-8')
    except UnicodeDecodeError:
        print("[WARN] UTF-8 failed, falling back to cp1252")
        df = pd.read_csv(filepath, encoding='cp1252')

    print(f"[INFO] Patreon CSV: {len(df)} monthly records")

    # Verify expected columns exist
    missing = [col for col in COLUMN_MAP if col not in df.columns]
    if missing:
        print(f"[WARN] Missing columns in Patreon CSV: {missing}")

    # Rename columns to match database schema
    df = df.rename(columns=COLUMN_MAP)

    # Parse month string (e.g., "2020-05") to first-of-month date
    df['sale_date'] = pd.to_datetime(df['sale_date'], format='%Y-%m')

    # Add source platform for consistency with other fact tables
    df['source_platform'] = 'patreon'

    # Fill any NaN numeric values with 0 (fees/adjustments often blank)
    numeric_cols = [
        'gross_web_android', 'gross_ios', 'gross_total',
        'platform_fees', 'processing_fees', 'exchange_fee',
        'ios_app_fee', 'merch_costs', 'total_processing_fees',
        'refunds', 'adjustments', 'recovered_payments', 'net_earnings',
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0.0).astype(float)

    # Reorder columns to match fact_patreon_earnings schema
    final_columns = [
        'sale_date', 'source_platform', 'currency',
        'gross_web_android', 'gross_ios', 'gross_total',
        'platform_fees', 'processing_fees', 'exchange_fee',
        'ios_app_fee', 'merch_costs', 'total_processing_fees',
        'refunds', 'adjustments', 'recovered_payments', 'net_earnings',
    ]

    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    print(f"[INFO] Patreon load complete: {len(df_result)} months of earnings")
    print(f"[INFO] Date range: {df_result['sale_date'].min().strftime('%Y-%m')} "
          f"to {df_result['sale_date'].max().strftime('%Y-%m')}")
    print(f"[INFO] Total net earnings (all months): ${df_result['net_earnings'].sum():.2f}")

    return df_result