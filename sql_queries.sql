-- ============================================================
-- Author Business Analytics — Showcase SQL Queries
-- Database: SQLite (data/author_analytics.db)
-- ============================================================

-- 1. MONTHLY REVENUE TREND (Time Series Analysis)
SELECT 
    strftime('%Y-%m', sale_date) AS period,
    SUM(quantity) AS total_units,
    ROUND(SUM(royalty_amount), 2) AS total_royalties,
    ROUND(AVG(royalty_amount), 2) AS avg_per_transaction,
    COUNT(*) AS transaction_count
FROM sales_fact
GROUP BY strftime('%Y-%m', sale_date)
ORDER BY period ASC;


-- 2. SERIES PERFORMANCE RANKING (Revenue by Book Series)
SELECT 
    series,
    COUNT(DISTINCT canonical_work_slug) AS unique_works,
    SUM(quantity) AS total_units_sold,
    ROUND(SUM(royalty_amount), 2) AS total_royalties,
    ROUND(SUM(royalty_amount) / NULLIF(SUM(quantity), 0), 2) AS revenue_per_unit,
    ROUND(AVG(royalty_rate * 100), 1) AS avg_royalty_percent
FROM sales_fact
WHERE series IS NOT NULL
GROUP BY series
ORDER BY SUM(royalty_amount) DESC;


-- 3. REGIONAL DISTRIBUTION (Geographic Analysis)
SELECT 
    region,
    SUM(quantity) AS total_units,
    ROUND(SUM(royalty_amount), 2) AS total_royalties,
    ROUND(100.0 * SUM(royalty_amount) / (SELECT SUM(royalty_amount) FROM sales_fact), 1) AS pct_of_revenue
FROM sales_fact
GROUP BY region
ORDER BY SUM(royalty_amount) DESC;


-- 4. YEAR-OVER-YEAR GROWTH (Comparative Analysis)
SELECT 
    strftime('%m', sale_date) AS month,
    ROUND(SUM(CASE WHEN strftime('%Y', sale_date) = '2024' THEN royalty_amount ELSE 0 END), 2) AS revenue_2024,
    ROUND(SUM(CASE WHEN strftime('%Y', sale_date) = '2025' THEN royalty_amount ELSE 0 END), 2) AS revenue_2025,
    ROUND(SUM(CASE WHEN strftime('%Y', sale_date) = '2026' THEN royalty_amount ELSE 0 END), 2) AS revenue_2026,
    CASE 
        WHEN SUM(CASE WHEN strftime('%Y', sale_date) = '2024' THEN royalty_amount ELSE 0 END) > 0 
        THEN ROUND(
            100.0 * (SUM(CASE WHEN strftime('%Y', sale_date) = '2025' THEN royalty_amount ELSE 0 END) - 
                     SUM(CASE WHEN strftime('%Y', sale_date) = '2024' THEN royalty_amount ELSE 0 END)) /
            SUM(CASE WHEN strftime('%Y', sale_date) = '2024' THEN royalty_amount ELSE 0 END), 1)
        ELSE NULL 
    END AS yoy_growth_pct_2025_vs_2024,
    CASE 
        WHEN SUM(CASE WHEN strftime('%Y', sale_date) = '2025' THEN royalty_amount ELSE 0 END) > 0 
        THEN ROUND(
            100.0 * (SUM(CASE WHEN strftime('%Y', sale_date) = '2026' THEN royalty_amount ELSE 0 END) - 
                     SUM(CASE WHEN strftime('%Y', sale_date) = '2025' THEN royalty_amount ELSE 0 END)) /
            SUM(CASE WHEN strftime('%Y', sale_date) = '2025' THEN royalty_amount ELSE 0 END), 1)
        ELSE NULL 
    END AS yoy_growth_pct_2026_vs_2025
FROM sales_fact
GROUP BY strftime('%m', sale_date)
ORDER BY CAST(month AS INTEGER) ASC;


-- 5. TOP PERFORMING TITLES (Individual Book Rankings)
SELECT 
    canonical_work_slug,
    series,
    SUM(quantity) AS total_units_sold,
    ROUND(SUM(royalty_amount), 2) AS total_royalties,
    MIN(sale_date) AS first_sale,
    MAX(sale_date) AS last_sale
FROM sales_fact
GROUP BY canonical_work_slug
ORDER BY SUM(royalty_amount) DESC
LIMIT 10;


-- 6. BEST PERFORMING MONTHS (Top 5 Revenue Periods)
SELECT 
    strftime('%Y-%m', sale_date) AS period,
    SUM(quantity) AS total_units,
    ROUND(SUM(royalty_amount), 2) AS total_royalties,
    ROUND(AVG(royalty_amount), 2) AS avg_transaction_value
FROM sales_fact
GROUP BY strftime('%Y-%m', sale_date)
ORDER BY SUM(royalty_amount) DESC
LIMIT 5;