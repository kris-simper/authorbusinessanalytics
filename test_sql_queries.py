"""Simple SQL validation test - Pass/Fail only."""
import sqlite3
from pathlib import Path


def main():
    print("SQL QUERY VALIDATION TEST")
    print("=" * 50)

    db_path = Path("data/author_analytics.db")
    if not db_path.exists():
        print("[ERROR] Database not found at", db_path)
        print("Run test_loader.py first to generate the database")
        return

    conn = sqlite3.connect(str(db_path))
    print("[INFO] Connected to database\n")

    queries = [
        ("Monthly Revenue Trend",
         "SELECT strftime('%Y-%m', sale_date), SUM(quantity), ROUND(SUM(royalty_amount), 2) FROM sales_fact GROUP BY strftime('%Y-%m', sale_date);"),

        ("Series Performance Ranking",
         "SELECT series, SUM(quantity), ROUND(SUM(royalty_amount), 2) FROM sales_fact WHERE series IS NOT NULL GROUP BY series ORDER BY SUM(royalty_amount) DESC;"),

        ("Regional Distribution",
         "SELECT region, SUM(quantity), ROUND(SUM(royalty_amount), 2) FROM sales_fact GROUP BY region ORDER BY SUM(royalty_amount) DESC;"),

        ("Top Performing Titles",
         "SELECT canonical_work_slug, SUM(quantity), ROUND(SUM(royalty_amount), 2) FROM sales_fact GROUP BY canonical_work_slug ORDER BY SUM(royalty_amount) DESC LIMIT 10;"),

        ("Best Performing Months",
         "SELECT strftime('%Y-%m', sale_date), SUM(quantity), ROUND(SUM(royalty_amount), 2) FROM sales_fact GROUP BY strftime('%Y-%m', sale_date) ORDER BY SUM(royalty_amount) DESC LIMIT 5;"),
    ]

    passed = 0
    failed = 0

    for title, sql in queries:
        try:
            conn.execute(sql)
            print(f"[PASS] {title}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {title}: {e}")
            failed += 1

    conn.close()

    print()
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("ALL QUERIES VALIDATED \u2713")
    else:
        print("SOME QUERIES FAILED - Check syntax above")
    print("=" * 50)


if __name__ == "__main__":
    main()