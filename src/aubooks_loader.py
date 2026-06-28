"""
Audiobooks Unleashed royalty loader for wide-distribution audiobook sales.

Parses "Royalty Detail" PDF statements using pdfplumber for text extraction.
Each PDF contains multiple book sections (identified by title + ISBN headers),
with data rows containing: accrued date, distributor source, quantity, location,
and a money flow chain (Gross -> Received -> Less Fee -> Payable -> Percent -> Royalty).

ISBNs from section headers are matched against the book catalog for series/work
enrichment. Currency is parsed from the PDF header and converted to USD.
"""

import re
import pdfplumber
import pandas as pd
from pathlib import Path


# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def _parse_money(s):
    """
    Clean and parse a monetary string.
    Handles currency symbols, parentheses for negatives, European decimal
    format (1.234,56), and bare numbers.
    """
    if not s or pd.isna(s):
        return 0.0
    s = str(s).strip()

    # Handle parentheses notation for negatives: (10.37) -> -10.37
    is_negative = False
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1].strip()
        is_negative = True

    s = re.sub(r'[\u20ac\u00a3\u00a5$]', '', s)  # Strip currency symbols
    s = re.sub(r'[A-Za-z]', '', s)  # Strip letters (EUR, GBP, etc.)
    s = s.strip()

    if not s or s == '-':
        return 0.0

    # Handle European decimal format: 1.234,56 -> 1234.56
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')   # Decimal comma: 14,97 -> 14.97
        else:
            s = s.replace(',', '')     # Thousands separator: 1,200 -> 1200

    try:
        val = float(s)
        return -val if is_negative else val
    except ValueError:
        return 0.0


def _is_money_token(token):
    """Check if a token looks like a monetary value (including parens negatives)."""
    cleaned = re.sub(r'[\u20ac\u00a3\u00a5$]', '', token)
    # Allow digits, dots, commas, parentheses, minus sign
    return bool(re.match(r'^\(?-?[\d.,]+\)?$', cleaned))


def _parse_data_row(line):
    """
    Parse a single AU Books data row from extracted text.

    Expected format:
    M/D/YYYY  SOURCE  QTY  LOCATION  GROSS  RECEIVED  FEE  PAYABLE  PERCENT%  ROYALTY

    Strategy:
    1. Date anchored at start (M/D/YYYY format)
    2. Percent value (ends with %) anchors boundary between middle and end
    3. Royalty is everything after percent
    4. Work backwards from percent to extract 4 money values
    5. Remaining middle tokens = source, qty, location
    """
    # Must start with a date in M/D/YYYY format
    date_match = re.match(r'^(\d{1,2}/\d{1,2}/\d{4})\s+', line)
    if not date_match:
        return None

    date_str = date_match.group(1)
    remainder = line[date_match.end():].strip()

    # Find percent value (must contain %)
    pct_matches = list(re.finditer(r'(-?\d+(?:\.\d+)?)\s*%', remainder))
    if not pct_matches:
        return None

    pct_match = pct_matches[-1]
    percent = float(pct_match.group(1))

    # Royalty is everything after the percent
    royalty_str = remainder[pct_match.end():].strip()
    royalty = _parse_money(royalty_str)

    # Before percent: SOURCE QTY LOCATION GROSS RECEIVED FEE PAYABLE
    before_pct = remainder[:pct_match.start()].strip()
    tokens = before_pct.split()

    # Work backwards: extract 4 money values (payable, fee, received, gross)
    money_vals = []
    i = len(tokens) - 1
    while i >= 0 and len(money_vals) < 4:
        token = tokens[i]
        if _is_money_token(token):
            money_vals.insert(0, _parse_money(token))
            i -= 1
        else:
            break

    if len(money_vals) < 4:
        return None

    payable, fee, received, gross = money_vals

    # Remaining tokens: SOURCE QTY LOCATION
    remaining = tokens[:i + 1]

    # Find qty (first standalone integer, possibly negative)
    qty_idx = None
    for j, token in enumerate(remaining):
        if re.match(r'^-?\d+$', token):
            qty_idx = j
            break

    if qty_idx is None:
        return None

    qty = int(remaining[qty_idx])
    source = ' '.join(remaining[:qty_idx])
    location = ' '.join(remaining[qty_idx + 1:]) if qty_idx + 1 < len(remaining) else ''

    return {
        'sale_date': date_str,
        'distributor': source,
        'quantity': qty,
        'region_code': location,
        'gross_local': gross,
        'received_local': received,
        'fee_local': fee,
        'payable_local': payable,
        'royalty_rate_pct': percent,
        'royalty_amount_local': royalty,
    }


# Valid ISO currency codes for detection
_VALID_CURRENCIES = {'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'INR',
                      'BRL', 'MXN', 'PLN', 'SEK', 'NZD'}


# ===================================================================
# MAIN LOADER
# ===================================================================

def load_aubooks_data(filepath, catalog=None):
    """
    Load Audiobooks Unleashed royalty detail PDF.

    Parses line-by-line text extraction with regex pattern matching.
    Tracks book sections via ISBN headers to attribute each row to
    the correct title.

    Args:
        filepath: Path to the AU Books PDF
        catalog: BookCatalog instance for ISBN-based enrichment

    Returns:
        DataFrame with parsed royalty data ready for database ingestion
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading Audiobooks Unleashed data from {filepath.name}")

    # Skip summary statements (no line-item data)
    if 'detail' not in filepath.name.lower():
        print(f"[WARN] Skipping non-detail PDF: {filepath.name}")
        return pd.DataFrame()

    all_rows = []
    current_title = None
    current_isbn = None
    currency = 'USD'
    title_candidates = []  # Lines that could be book titles

    with pdfplumber.open(filepath) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                print(f"[WARN] Page {page_num + 1}: no extractable text")
                continue

            lines = text.split('\n')

            for line in lines:
                line_stripped = line.strip()

                # Skip empty lines
                if not line_stripped:
                    continue

                lower = line_stripped.lower()

                # Detect standalone currency code (e.g., "USD" on its own line)
                if line_stripped.upper() in _VALID_CURRENCIES:
                    currency = line_stripped.upper()
                    continue

                # Skip "Royalty :50%" lines
                if lower.startswith('royalty') and '%' in line_stripped:
                    continue

                # Skip "Type:Audiobooks" lines
                if lower.startswith('type:'):
                    continue

                # Skip column header rows
                if lower.startswith('accrued') and 'source' in lower:
                    continue

                # Skip page footers/headers and metadata
                if lower.startswith(('page ', 'royalty detail for',
                                     'dashbook', 'all amounts')):
                    continue

                # Skip account/address lines
                if any(lower.startswith(prefix) for prefix in
                       ['royalty account', 'shauntel', 'glen cove',
                        'united states', 'info@', 'sdsimper']):
                    continue

                # Skip period line (we parse dates from data rows instead)
                if lower.startswith('period from'):
                    continue

                # Detect ISBN OR ACX ASIN/product code line
                isbn_match = re.search(
                    r'ISBN[:\s]*(\d{10,13})',
                    line_stripped, re.IGNORECASE
                )
                asin_match = re.search(
                    r'(?:ASIN|Product Code)[:\s]*([A-Za-z0-9_]+)',
                    line_stripped, re.IGNORECASE
                )
                
                if isbn_match or asin_match:
                    # Prefer ISBN if available, else fall back to ASIN/product code
                    current_isbn = isbn_match.group(1) if isbn_match else asin_match.group(1)
                    
                    # Look backwards through title candidates for the book title
                    for candidate in reversed(title_candidates):
                        # Must not be a data row (doesn't start with a date)
                        if not re.match(r'^\d{1,2}/\d{1,2}/\d{4}', candidate):
                            current_title = candidate
                            break
                    title_candidates = []
                    continue

                # Try to parse as data row
                row = _parse_data_row(line_stripped)
                if row:
                    row['book_isbn'] = current_isbn
                    row['display_title'] = current_title
                    row['currency'] = currency
                    all_rows.append(row)
                else:
                    # Could be a book title on its own line
                    # Only track if it's not a data row and looks like a title
                    if (len(line_stripped) > 2 and
                        not re.match(r'^\d{1,2}/\d{1,2}/\d{4}', line_stripped) and
                        '@' not in line_stripped):
                        title_candidates.append(line_stripped)

    if not all_rows:
        print(f"[WARN] No data rows parsed from {filepath.name}")
        return pd.DataFrame()

    # Build DataFrame
    df = pd.DataFrame(all_rows)
    df['sale_date'] = pd.to_datetime(df['sale_date'], format='mixed')
    df['source_platform'] = 'audiobooks_unleashed'
    df['edition_format'] = 'audiobook'

    print(f"[INFO] Parsed {len(df)} royalty line items from {filepath.name}")
    print(f"[INFO] Date range: {df['sale_date'].min().strftime('%Y-%m-%d')} "
          f"to {df['sale_date'].max().strftime('%Y-%m-%d')}")
    print(f"[INFO] Currency: {currency}")
    print(f"[INFO] Books found: {df['display_title'].nunique()}")
    print(f"[INFO] Distributors: {', '.join(sorted(df['distributor'].unique()))}")

    # Currency conversion to USD
    if currency != 'USD':
        print(f"[INFO] Converting {currency} royalties to USD...")
        from src.currency import to_usd
        df['royalty_amount_usd'] = df.apply(
            lambda r: to_usd(
                r['royalty_amount_local'], currency, r['sale_date']
            ),
            axis=1
        )
    else:
        df['royalty_amount_usd'] = df['royalty_amount_local']

    # Catalog enrichment via ISBN matching
    if catalog is not None and 'book_isbn' in df.columns:
        print("[INFO] Enriching with catalog metadata via ISBN...")
        df = df.rename(columns={'book_isbn': 'book_identifier'})
        df = catalog.enrich(df, 'book_identifier')
        df = df.rename(columns={'book_identifier': 'book_isbn'})

        matched = df['series'].notna().sum()
        print(f"[INFO] Catalog enrichment: {matched}/{len(df)} rows matched")
    else:
        df['canonical_work_slug'] = None
        df['series'] = None

    # Final column selection to match fact_aubooks_sales schema
    final_columns = [
        'sale_date', 'source_platform', 'book_isbn', 'display_title',
        'distributor', 'region_code', 'quantity',
        'gross_local', 'received_local', 'fee_local', 'payable_local',
        'royalty_rate_pct', 'royalty_amount_local', 'currency',
        'royalty_amount_usd',
        'canonical_work_slug', 'series', 'edition_format',
    ]

    df_result = df[[c for c in final_columns if c in df.columns]].copy()

    print(f"[INFO] AU Books load complete: {len(df_result)} records")
    print(f"[INFO] Total royalty (local): "
          f"{df_result['royalty_amount_local'].sum():.2f} {currency}")
    print(f"[INFO] Total royalty (USD): "
          f"${df_result['royalty_amount_usd'].sum():.2f}")

    return df_result