"""
SQLite database layer for author business analytics.
Handles schema initialization, data ingestion, and analytical queries.
"""

import sqlite3
from pathlib import Path
import pandas as pd


DATABASE_PATH = "data/author_analytics.db"


def init_database(db_path=None):
    """
    Create fresh SQLite database with optimal table schema.
    
    Args:
        db_path: Custom path override (defaults to config DEFAULT_DB_PATH)
    
    Returns:
        SQLite connection object
    """
    if db_path is None:
        db_path = DATABASE_PATH
    
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Create main sales_fact table with indexes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_fact (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date DATE NOT NULL,
            source_platform TEXT NOT NULL,
            book_identifier TEXT,
            canonical_work_slug TEXT,
            series TEXT,
            edition_format TEXT,
            region TEXT,
            currency TEXT DEFAULT 'USD',
            quantity INTEGER DEFAULT 0,
            price REAL DEFAULT 0.0,
            price_usd REAL DEFAULT 0.0,
            royalty_amount REAL DEFAULT 0.0,
            royalty_amount_usd REAL DEFAULT 0.0,
            royalty_rate REAL,
            FOREIGN KEY (book_identifier) REFERENCES dim_books(book_identifier),
            FOREIGN KEY (canonical_work_slug) REFERENCES dim_books(canonical_work_slug)
        )
    """)
    
    # Create dimension table for books (denormalized catalog view)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dim_books (
            book_identifier TEXT PRIMARY KEY,
            canonical_work_slug TEXT,
            display_title TEXT,
            series TEXT,
            edition_format TEXT,
            other_ids TEXT
        )
    """)
    
    # Performance indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales_fact(sale_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_series ON sales_fact(series)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_platform ON sales_fact(source_platform)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_region ON sales_fact(region)")
    
    conn.commit()
    print(f"[INFO] Database initialized at {db_path}")
    return conn


def init_kenp_table(conn):
    """Create the KENP reads fact table (separate grain from sales)."""
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kenp_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date DATE NOT NULL,
            source_platform TEXT NOT NULL DEFAULT 'amazon_kdp_ku',
            book_identifier TEXT,
            canonical_work_slug TEXT,
            series TEXT,
            edition_format TEXT,
            marketplace TEXT,
            region TEXT,
            currency TEXT,
            page_count INTEGER,
            rate_per_page REAL,
            royalty_amount REAL,
            royalty_amount_usd REAL,
            kenp_page_count INTEGER,
            equivalent_copies REAL,
            FOREIGN KEY (book_identifier) REFERENCES dim_books(book_identifier)
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kenp_date ON kenp_reads(sale_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kenp_series ON kenp_reads(series)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kenp_region ON kenp_reads(region)")
    
    conn.commit()
    print("[INFO] KENP reads table initialized")


def init_patreon_table(conn):
    """Create the Patreon earnings fact table (monthly aggregate grain)."""
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fact_patreon_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date DATE NOT NULL,
            source_platform TEXT NOT NULL DEFAULT 'patreon',
            currency TEXT NOT NULL DEFAULT 'USD',
            gross_web_android REAL DEFAULT 0.0,
            gross_ios REAL DEFAULT 0.0,
            gross_total REAL DEFAULT 0.0,
            platform_fees REAL DEFAULT 0.0,
            processing_fees REAL DEFAULT 0.0,
            exchange_fee REAL DEFAULT 0.0,
            ios_app_fee REAL DEFAULT 0.0,
            merch_costs REAL DEFAULT 0.0,
            total_processing_fees REAL DEFAULT 0.0,
            refunds REAL DEFAULT 0.0,
            adjustments REAL DEFAULT 0.0,
            recovered_payments REAL DEFAULT 0.0,
            net_earnings REAL DEFAULT 0.0
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patreon_date ON fact_patreon_earnings(sale_date)")
    
    conn.commit()
    print("[INFO] Patreon earnings table initialized")    
    

def init_woo_table(conn):
    """Create the WooCommerce sales fact table (product-level grain per date range)."""
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fact_woo_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date DATE NOT NULL,
            period_start DATE,
            period_end DATE,
            source_platform TEXT NOT NULL DEFAULT 'woocommerce',
            product_name TEXT,
            sku TEXT,
            category TEXT,
            items_sold INTEGER DEFAULT 0,
            net_sales REAL DEFAULT 0.0,
            orders_count INTEGER DEFAULT 0,
            canonical_work_slug TEXT,
            series TEXT,
            edition_format TEXT
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_woo_date ON fact_woo_sales(sale_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_woo_category ON fact_woo_sales(category)")
    
    conn.commit()
    print("[INFO] WooCommerce sales table initialized")


def init_aubooks_table(conn):
    """Create the Audiobooks Unleashed sales fact table (line-item grain)."""
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fact_aubooks_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date DATE NOT NULL,
            source_platform TEXT NOT NULL DEFAULT 'audiobooks_unleashed',
            book_isbn TEXT,
            display_title TEXT,
            distributor TEXT,
            region_code TEXT,
            quantity INTEGER,
            gross_local REAL,
            received_local REAL,
            fee_local REAL,
            payable_local REAL,
            royalty_rate_pct REAL,
            royalty_amount_local REAL,
            currency TEXT DEFAULT 'USD',
            royalty_amount_usd REAL,
            canonical_work_slug TEXT,
            series TEXT,
            edition_format TEXT DEFAULT 'audiobook'
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_aubooks_date ON fact_aubooks_sales(sale_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_aubooks_isbn ON fact_aubooks_sales(book_isbn)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_aubooks_series ON fact_aubooks_sales(series)")
    
    conn.commit()
    print("[INFO] Audiobooks Unleashed sales table initialized")

    
def ingest_dataframe(conn, df, table_name='sales_fact'):
    """
    Efficiently bulk-load pandas DataFrame into SQLite.
    
    Args:
        conn: Active SQLite connection
        df: Pandas DataFrame containing transaction data
        table_name: Target table (default: sales_fact)
    """
    if df.empty:
        print("[WARN] Cannot ingest empty DataFrame")
        return 0
    
    df.to_sql(table_name, conn, if_exists='append', index=False)
    print(f"[INFO] Ingested {len(df)} rows into {table_name}")
    return len(df)


def get_monthly_summary_query(conn):
    """
    Example analytical query: Monthly revenue aggregation by platform.
    
    Args:
        conn: SQLite connection
    
    Returns:
        List of tuples with aggregated results
    """
    cursor = conn.cursor()
    
    query = """
        SELECT 
            strftime('%Y-%m', sale_date) AS period,
            source_platform,
            SUM(quantity) AS total_units,
            ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
            COUNT(*) AS transaction_count
        FROM sales_fact
        GROUP BY strftime('%Y-%m', sale_date), source_platform
        ORDER BY period DESC, source_platform ASC
    """
    
    cursor.execute(query)
    return cursor.fetchall()


def get_series_performance_query(conn):
    """
    Example analytical query: Revenue breakdown by book series.
    
    Args:
        conn: SQLite connection
    
    Returns:
        Dict mapping series names to performance metrics
    """
    cursor = conn.cursor()
    
    query = """
        SELECT 
            series,
            COUNT(DISTINCT canonical_work_slug) AS unique_works,
            SUM(quantity) AS total_units_sold,
            ROUND(SUM(royalty_amount_usd), 2) AS total_royalties,
            ROUND(AVG(royalty_rate * 100), 1) AS avg_royalty_percent
        FROM sales_fact
        WHERE series IS NOT NULL AND series != ''
        GROUP BY series
        ORDER BY total_royalties DESC
    """
    
    cursor.execute(query)
    columns = ['series', 'unique_works', 'total_units_sold', 'total_royalties', 'avg_royalty_percent']
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def close_connection(conn):
    """Safe database disconnection."""
    if conn:
        conn.close()
        print("[INFO] Database connection closed")