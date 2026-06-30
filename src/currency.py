"""
Currency conversion utilities using historical ECB exchange rates.

Provides singleton CurrencyConverter instance backed by the bundled ECB
historical reference rate dataset. All ETL loaders use to_usd() to normalize
multi-currency royalty amounts to USD for consistent cross-platform reporting.

Fallback Logic:
ECB does not publish reference rates on weekends or European holidays.
When an exact-date rate is unavailable, to_usd() walks backward up to 30 days
to find the most recent available rate before the transaction date.

Kimball Compliance:
Currency conversion occurs in the ETL pipeline (Step 3) before ingestion,
producing a royalty_amount_usd conformed measure column across all fact tables.
"""

from datetime import date, timedelta

import pandas as pd
from currency_converter import CurrencyConverter, RateNotFoundError


# ===================================================================
# SINGLETON CONVERTER INITIALIZATION
# ===================================================================

_converter = None


def get_converter() -> CurrencyConverter:
    """
    Initialize and cache the CurrencyConverter instance with bundled ECB rates.

    Uses a module-level singleton pattern so the ECB dataset (which is large)
    is loaded only once per pipeline run, not once per transaction row.

    Returns:
        CurrencyConverter instance ready for historical conversions
    """
    global _converter
    if _converter is None:
        _converter = CurrencyConverter()
    return _converter


# ===================================================================
# CONVERSION FUNCTIONS
# ===================================================================

def to_usd(
    amount: float | None,
    currency_code: str | None,
    txn_date: date | pd.Timestamp | str,
) -> float | None:
    """
    Convert an amount to USD using the ECB reference rate nearest to txn_date.

    Handles weekend/holiday gaps by walking backward up to 30 days to find
    the most recent published rate. Returns None if no rate is found within
    the 30-day window or if inputs are invalid.

    Args:
        amount: Numeric amount in the original currency (may be None/NaN)
        currency_code: ISO 4217 currency code (e.g., 'EUR', 'GBP', 'JPY')
                       (may be None/NaN)
        txn_date: Date of the transaction. Accepts datetime.date,
                  pandas.Timestamp, or ISO date string. All are normalized
                  to datetime.date internally.

    Returns:
        Amount converted to USD rounded to 2 decimal places, or None if:
        - Input amount or currency_code is NaN/None
        - No ECB rate is available within 30 days before txn_date
        - The currency code is not recognized by the ECB dataset
    """
    # Guard against NaN/None inputs from upstream data quality issues
    if pd.isna(amount) or pd.isna(currency_code):
        return None

    currency_code = str(currency_code).strip().upper()
    if currency_code == 'USD':
        return round(float(amount), 2)

    cc = get_converter()

    # Normalize txn_date to datetime.date regardless of input type
    if isinstance(txn_date, pd.Timestamp):
        txn_date = txn_date.date()
    elif isinstance(txn_date, str):
        txn_date = pd.to_datetime(txn_date).date()

    # Attempt exact-date conversion first
    try:
        return round(cc.convert(float(amount), currency_code, 'USD', date=txn_date), 2)

    # Walk backward up to 30 days for weekend/holiday fallback
    except (RateNotFoundError, ValueError):
        for i in range(1, 30):
            try:
                fallback_date = txn_date - timedelta(days=i)
                return round(
                    cc.convert(float(amount), currency_code, 'USD', date=fallback_date),
                    2,
                )
            except (RateNotFoundError, ValueError):
                continue

        print(f"[WARN] Could not convert {amount} {currency_code} on {txn_date}")
        return None