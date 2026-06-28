# src/currency.py
from currency_converter import CurrencyConverter
from datetime import date, timedelta
import pandas as pd

_converter = None

def get_converter():
    global _converter
    if _converter is None:
        _converter = CurrencyConverter()
    return _converter

def to_usd(amount, currency_code, txn_date):
    """Convert amount to USD using ECB reference rate nearest to txn_date."""
    if pd.isna(amount) or pd.isna(currency_code):
        return None
    currency_code = str(currency_code).strip().upper()
    if currency_code == 'USD':
        return round(float(amount), 2)
    cc = get_converter()
    if isinstance(txn_date, pd.Timestamp):
        txn_date = txn_date.date()
    elif isinstance(txn_date, str):
        txn_date = pd.to_datetime(txn_date).date()
    try:
        return round(cc.convert(float(amount), currency_code, 'USD', date=txn_date), 2)
    except Exception:
        # RateNotFoundError or ValueError — walk backward to find nearest available date
        for i in range(1, 30):
            try:
                fallback_date = txn_date - timedelta(days=i)
                return round(cc.convert(float(amount), currency_code, 'USD', date=fallback_date), 2)
            except Exception:
                continue
        print(f"WARNING: Could not convert {amount} {currency_code} on {txn_date}")
        return None