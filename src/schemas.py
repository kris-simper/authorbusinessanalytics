"""
Column name mappings and platform constants for ETL pipeline schema normalization.

Provides standardized column name mappings that translate platform-specific export
headers into unified schema fields used across all fact tables. Each loader
imports the relevant mapping constant and applies it via DataFrame.rename().

Architecture Note:
Some newer loaders (D2D, B&N, Kobo, Ingram) define their column mappings locally
within the loader file itself, since those mappings include transformation logic
(e.g., renaming Publisher Share → royalty_amount with semantic meaning). The
constants here are used by the older loaders (ACX, KDP) where mappings are
pure renaming with no transformation logic.

Active Constants:
- ACX_NEW_FORMAT: Column rename map for ACX post-April 2024 .xlsx exports
- KDP_COMBINED_FORMAT: Column rename map for KDP Combined Sales sheet
- KDP_MARKETPLACE_MAP: Amazon marketplace domain → region code lookup
- DROP_COLUMNS_COMMON: PII columns to strip from all Amazon exports

Deprecated/Placeholder Constants:
- ACX_OLD_FORMAT: Empty placeholder — legacy ACX uses manual header parsing
- AMAZON_KDP_EBOOK: Unused — replaced by KDP_COMBINED_FORMAT
- AMAZON_KDP_PAPERBACK: Unused — replaced by KDP_COMBINED_FORMAT
- DRAFT2DIGITAL_CSV: Unused — D2D loader defines local COLUMN_MAP
- BARNES_AND_NOBLE_CSV: Unused — B&N loader defines local column mapping
"""

# ===================================================================
# ACX (AUDIOBOOK CREATION EXCHANGE) SCHEMAS
# ===================================================================

ACX_NEW_FORMAT = {
    'Product ID': 'book_identifier',
    'Title': 'book_title',
    'Digital ISBN': 'isbn',
    'Transaction Type': 'transaction_type',
    'Marketplace': 'region',
    'Currency': 'currency',
    'Net Units': 'quantity',
    'Net Sales': 'price',
    'Net Royalties Earned': 'royalty_amount',
    'Royalty Rate': 'royalty_rate',
}

# Legacy ACX format uses manual header parsing (header=4) and does not
# require a column mapping constant. See amazon_loader.load_acx_legacy_report().
ACX_OLD_FORMAT = {}


# ===================================================================
# AMAZON KDP SCHEMAS
# ===================================================================

# Combined Sales sheet merges all formats (eBook, Paperback, Hardcover)
# into a single flat tabular structure.
KDP_COMBINED_FORMAT = {
    'Royalty Date': 'sale_date',
    'Title': 'book_title',
    'ASIN/ISBN': 'book_identifier',
    'Marketplace': 'marketplace_raw',
    'Royalty Type': 'royalty_type_raw',
    'Transaction Type': 'transaction_type',
    'Net Units Sold': 'quantity',
    'Avg. List Price without tax': 'price',
    'Royalty': 'royalty_amount',
    'Currency': 'currency',
}

# Earlier approach used separate per-format mappings (now deprecated).
# Retained for reference in case format-specific parsing is needed later.
AMAZON_KDP_EBOOK = {
    'Royalty Date': 'sale_date',
    'Title': 'book_title',
    'ASIN': 'book_identifier',
    'Marketplace': 'region',
    'Units Sold': 'quantity',
    'Avg. List Price without tax': 'price',
    'Royalty': 'royalty_amount',
    'Currency': 'currency',
}

AMAZON_KDP_PAPERBACK = {
    'Royalty Date': 'sale_date',
    'Order Date': 'order_date',
    'Title': 'book_title',
    'ISBN': 'isbn',
    'Marketplace': 'region',
    'Units Sold': 'quantity',
    'Avg. List Price without tax': 'price',
    'Royalty': 'royalty_amount',
    'Currency': 'currency',
}

# Amazon marketplace domain → region code mapping
KDP_MARKETPLACE_MAP = {
    'Amazon.com': 'US',
    'Amazon.co.uk': 'UK',
    'Amazon.de': 'DE',
    'Amazon.fr': 'FR',
    'Amazon.it': 'IT',
    'Amazon.es': 'ES',
    'Amazon.com.au': 'AU',
    'Amazon.ca': 'CA',
    'Amazon.co.jp': 'JP',
    'Amazon.in': 'IN',
    'Amazon.nl': 'NL',
    'Amazon.com.mx': 'MX',
    'Amazon.com.br': 'BR',
    'Amazon.se': 'SE',
    'Amazon.pl': 'PL',
}


# ===================================================================
# OTHER PLATFORM SCHEMAS (DEFINED IN-LOADER, RETAINED FOR REFERENCE)
# ===================================================================

# Draft2Digital and Barnes & Noble loaders define their column mappings
# locally within the loader files. These constants are retained for
# reference and potential future centralization.

DRAFT2DIGITAL_CSV = {
    'Start Date': 'sale_date_start',
    'End Date': 'sale_date_end',
    'Title': 'book_title',
    'Publisher Share USD (estimated)': 'royalty_amount',
    'List Price Per Unit': 'price',
    'Country': 'region',
    'Units Sold': 'quantity',
    'Retailer': 'channel',
}

BARNES_AND_NOBLE_CSV = {
    'Sale Date': 'sale_date',
    'Title': 'book_title',
    'Format': 'product_format',
    'BN ID / ISBN': 'book_identifier',
    'Units Sold': 'quantity',
    'Total Royalty': 'royalty_amount',
    'Selling Currency': 'currency',
}


# ===================================================================
# PII COLUMNS TO STRIP FROM ALL SOURCES
# ===================================================================

# Author name fields are stripped during ingestion to protect PII.
# Royalty Earner is stripped from legacy ACX reports.
DROP_COLUMNS_COMMON = ['Author', 'Author Name', 'Primary Author', 'Royalty Earner']