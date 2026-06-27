"""
Column name mappings for each data source platform.
Used to normalize different export formats into unified schema.
"""

ACX_NEW_FORMAT = {
    'Product ID': 'book_identifier',
    'Title': 'book_title',
    'Digital ISBN': 'isbn',
    'Transaction Type': 'transaction_type',
    'Region': 'region',  # Renamed from 'Marketplace'
    'Currency': 'currency',
    'Net Units': 'quantity',
    'Net Sales': 'price',
    'Net Royalties Earned': 'royalty_amount',
    'Royalty Rate': 'royalty_rate',
}

ACX_OLD_FORMAT = {
    # Old format needs special wide-to-long reshaping later
    # Placeholder — implement after ACX new format works
}

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

DRAFT2DIGITAL_CSV = {
    'Start Date': 'sale_date_start',
    'End Date': 'sale_date_end',
    'Title': 'book_title',
    'Publisher Share USD (estimated)': 'royalty_amount',
    'List Price Per Unit': 'price',
    'Country': 'region',
    'Units Sold': 'quantity',
    'Retailer': 'channel',  # Additional context field
}

BARNES_AND_NOBLE_CSV = {
    'Sale Date': 'sale_date',
    'Title': 'book_title',
    'Format': 'product_format',  # eBook, Hardcover, etc.
    'BN ID / ISBN': 'book_identifier',
    'Units Sold': 'quantity',
    'Total Royalty': 'royalty_amount',
    'Selling Currency': 'currency',
}

# Columns to DROP from all sources (PII/irrelevant)
DROP_COLUMNS_COMMON = ['Author', 'Author Name', 'Primary Author', 'Royalty Earner']