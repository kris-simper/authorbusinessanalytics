"""
DEPRECATED: Query validation suite.

These tests verified database integrity during development. Now handled
automatically by cached dashboard queries (@st.cache_data(ttl=300)) which
fail gracefully on errors rather than crashing.

Kept for: Educational reference on SQL validation patterns, error handling,
and database integrity checking. Demonstrates defensive query testing across
multiple fact tables with different schemas and grains.

Usage:
    python validate_queries.py

Prerequisites:
    Database must exist at data/author_analytics.db
    Run `python run_pipeline.py` first if it doesn't.
"""

import warnings
warnings.warn(
    "validate_queries.py is deprecated. Dashboard handles validation automatically.",
    DeprecationWarning,
    stacklevel=2
)

import sqlite3
from pathlib import Path


def main():
    """Run all SQL query validation tests and display results."""
    print("SQL QUERY VALIDATION SUITE")
    print("=" * 60)

    db_path = Path("data/author_analytics.db")
    if not db_path.exists():
        print(f"[ERROR] Database not found at {db_path}")
        print("Run `python run_pipeline.py` first to generate the database.")
        return

    conn = sqlite3.connect(str(db_path))
    print(f"[INFO] Connected to database: {db_path}\n")

    # ============================================================
    # BASIC INTEGRITY QUERIES — verify each table is queryable
    # ============================================================
    basic_queries = [
        ("sales_fact — row count + revenue total",
         "SELECT COUNT(*), ROUND(SUM(royalty_amount_usd), 2) FROM sales_fact;"),

        ("kenp_reads — row count + revenue total",
         "SELECT COUNT(*), ROUND(SUM(royalty_amount_usd), 2) FROM kenp_reads;"),

        ("fact_patreon_earnings — row count + net earnings",
         "SELECT COUNT(*), ROUND(SUM(net_earnings), 2) FROM fact_patreon_earnings;"),

        ("fact_woo_sales — row count + net sales",
         "SELECT COUNT(*), ROUND(SUM(net_sales), 2) FROM fact_woo_sales;"),

        ("fact_aubooks_sales — row count + royalty total",
         "SELECT COUNT(*), ROUND(SUM(royalty_amount_usd), 2) FROM fact_aubooks_sales;"),

        ("dim_books — edition count",
         "SELECT COUNT(*) FROM dim_books;"),
    ]

    # ============================================================
    # ANALYTICAL QUERIES — verify schema supports real analysis
    # ============================================================
    analytical_queries = [
        ("Monthly Revenue Trend (sales_fact)",
         """SELECT strftime('%Y-%m', sale_date) AS period,
                   SUM(quantity) AS units,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM sales_fact
            GROUP BY period ORDER BY period;"""),

        ("Series Performance Ranking (sales_fact)",
         """SELECT COALESCE(series, '(Unmatched)') AS series_name,
                   SUM(quantity) AS units,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM sales_fact
            WHERE series IS NOT NULL
            GROUP BY series_name
            ORDER BY revenue DESC;"""),

        ("Regional Distribution (sales_fact)",
         """SELECT region,
                   SUM(quantity) AS units,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM sales_fact
            GROUP BY region
            ORDER BY revenue DESC;"""),

        ("Top Performing Titles (sales_fact)",
         """SELECT canonical_work_slug,
                   SUM(quantity) AS units,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM sales_fact
            GROUP BY canonical_work_slug
            ORDER BY revenue DESC LIMIT 10;"""),

        ("KENP Pages Read by Month (kenp_reads)",
         """SELECT strftime('%Y-%m', sale_date) AS period,
                   SUM(page_count) AS pages,
                   ROUND(SUM(equivalent_copies), 2) AS equiv_copies
            FROM kenp_reads
            GROUP BY period ORDER BY period;"""),

        ("AU Books Distributor Breakdown (fact_aubooks_sales)",
         """SELECT COALESCE(distributor, 'Unknown') AS distributor,
                   SUM(quantity) AS units,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM fact_aubooks_sales
            GROUP BY distributor
            ORDER BY revenue DESC;"""),

        ("WooCommerce Product Performance (fact_woo_sales)",
         """SELECT product_name,
                   SUM(items_sold) AS units,
                   ROUND(SUM(net_sales), 2) AS revenue
            FROM fact_woo_sales
            GROUP BY product_name
            ORDER BY revenue DESC LIMIT 10;"""),

        ("Patreon Monthly Net Earnings (fact_patreon_earnings)",
         """SELECT strftime('%Y-%m', sale_date) AS period,
                   ROUND(SUM(net_earnings), 2) AS net
            FROM fact_patreon_earnings
            GROUP BY period ORDER BY period;"""),
    ]

    # ============================================================
    # ADVANCED TECHNIQUE QUERIES — mirror sql_queries.sql patterns
    # ============================================================
    advanced_queries = [
        ("Window Function — Series Contribution Ranking",
         """WITH series_rev AS (
                SELECT series, canonical_work_slug,
                       SUM(royalty_amount_usd) AS book_revenue
                FROM sales_fact WHERE series IS NOT NULL
                GROUP BY series, canonical_work_slug
            )
            SELECT series, canonical_work_slug,
                   ROW_NUMBER() OVER (PARTITION BY series ORDER BY book_revenue DESC) AS rank,
                   ROUND(book_revenue * 100.0 / SUM(book_revenue) OVER (PARTITION BY series), 1) AS pct
            FROM series_rev
            ORDER BY series, rank LIMIT 20;"""),

        ("LAG — Month-over-Month Growth (sales_fact)",
         """WITH monthly AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       source_platform,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact
                GROUP BY period, source_platform
            )
            SELECT source_platform, period, revenue,
                   LAG(revenue) OVER (PARTITION BY source_platform ORDER BY period) AS prev_revenue
            FROM monthly ORDER BY source_platform, period;"""),

        ("Cumulative Sum — Lifetime Revenue Trajectory",
         """WITH monthly AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact
                GROUP BY period
            )
            SELECT period,
                   revenue,
                   ROUND(SUM(revenue) OVER (ORDER BY period ROWS UNBOUNDED PRECEDING), 2) AS cumulative
            FROM monthly ORDER BY period;"""),

        ("Pareto — Cumulative Title Revenue Share",
         """WITH title_rev AS (
                SELECT canonical_work_slug,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact
                GROUP BY canonical_work_slug
            ),
            ranked AS (
                SELECT canonical_work_slug, revenue,
                       ROUND(SUM(revenue) OVER (ORDER BY revenue DESC) * 100.0 /
                             SUM(revenue) OVER (), 1) AS cumulative_pct
                FROM title_rev
            )
            SELECT * FROM ranked WHERE cumulative_pct <= 80 ORDER BY revenue DESC;"""),
    ]

    # ============================================================
    # RUN ALL TESTS
    # ============================================================
    passed = 0
    failed = 0
    total_rows = 0

    print("-" * 60)
    print("BASIC INTEGRITY CHECKS (6 tables)")
    print("-" * 60)
    for title, sql in basic_queries:
        try:
            cursor = conn.execute(sql)
            row = cursor.fetchone()
            row_count = row[0] if row else 0
            print(f"  [PASS] {title}: {row_count:,} rows")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {title}: {e}")
            failed += 1

    print(f"\n{'-' * 60}")
    print("ANALYTICAL QUERIES (8 queries)")
    print("-" * 60)
    for title, sql in analytical_queries:
        try:
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            total_rows += len(rows)
            print(f"  [PASS] {title}: {len(rows)} rows returned")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {title}: {e}")
            failed += 1

    print(f"\n{'-' * 60}")
    print("ADVANCED TECHNIQUE QUERIES (4 queries)")
    print("-" * 60)
    for title, sql in advanced_queries:
        try:
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            print(f"  [PASS] {title}: {len(rows)} rows returned")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {title}: {e}")
            failed += 1

    conn.close()

    # ============================================================
    # SUMMARY
    # ============================================================
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print(f"Total rows across all analytical queries: {total_rows:,}")
    if failed == 0:
        print("ALL QUERIES VALIDATED ✓")
    else:
        print(f"{failed} QUERIES FAILED — Check errors above")
    print("=" * 60)


if __name__ == "__main__":
    main()