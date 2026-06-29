-- ============================================================
-- LEGACY QUERY DEMONSTRATIONS
-- ============================================================
-- DEPRECATED: These queries served as portfolio showcases during 
-- development but are now superseded by the Streamlit dashboard
-- (streamlit_app.py). They remain here for educational purposes
-- to demonstrate raw SQL proficiency in analytical query writing.
-- 
-- Modern consumption: Run `streamlit run streamlit_app.py` for
-- interactive exploration of these same queries.
--
-- Key techniques demonstrated below:
-- • UNION ALL patterns for multi-table aggregation
-- • strftime() date manipulation
-- • CTEs for complex calculations
-- • Window functions for rankings
-- ============================================================

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


-- ============================================================
-- ADVANCED SQL TECHNIQUES DEMONSTRATION
-- ============================================================
-- These queries showcase analytical SQL patterns beyond basic aggregation.
-- Used for portfolio demonstration.

--------------------------------------------------------------------------------
-- QUERY 1: WINDOW FUNCTIONS - Series Contribution Ranking
-- Technique: ROW_NUMBER(), SUM() OVER (PARTITION BY ...)
-- Purpose: Rank each book within its series by revenue share
--------------------------------------------------------------------------------

WITH series_revenue AS (
    SELECT 
        series,
        canonical_work_slug,
        SUM(royalty_amount_usd) AS total_book_revenue
    FROM sales_fact
    WHERE series IS NOT NULL
    GROUP BY series, canonical_work_slug
),
ranked_books AS (
    SELECT 
        series,
        canonical_work_slug,
        total_book_revenue,
        ROW_NUMBER() OVER (PARTITION BY series ORDER BY total_book_revenue DESC) AS rank_in_series,
        SUM(total_book_revenue) OVER (PARTITION BY series) AS series_total_revenue,
        ROUND(total_book_revenue * 100.0 / SUM(total_book_revenue) OVER (PARTITION BY series), 1) AS pct_of_series
    FROM series_revenue
)
SELECT 
    series,
    canonical_work_slug,
    rank_in_series,
    '$' || printf("%.2f", total_book_revenue) AS book_revenue,
    '$' || printf("%.2f", series_total_revenue) AS series_total,
    pct_of_series || '%' AS contribution_pct
FROM ranked_books
WHERE rank_in_series <= 5
ORDER BY series, rank_in_series;


--------------------------------------------------------------------------------
-- QUERY 2: RECURSIVE CTE - Month Gap Detection
-- Technique: RECURSIVE CTE to generate continuous time series
-- Purpose: Identify months with zero activity (publication gaps)
--------------------------------------------------------------------------------

WITH RECURSIVE 
all_months(period) AS (
    -- Anchor: Start from earliest recorded month
    SELECT MIN(strftime('%Y-%m', sale_date))
    FROM sales_fact
    
    UNION ALL
    
    -- Recursive: Increment month until latest
    SELECT strftime('%Y-%m', date(period || '-01', '+1 month'))
    FROM all_months
    WHERE period < (SELECT MAX(strftime('%Y-%m', sale_date)) FROM sales_fact)
),
monthly_activity AS (
    SELECT 
        strftime('%Y-%m', sale_date) AS active_month,
        COUNT(*) AS transaction_count,
        ROUND(SUM(royalty_amount_usd), 2) AS revenue
    FROM sales_fact
    GROUP BY strftime('%Y-%m', sale_date)
)
SELECT 
    m.period,
    COALESCE(a.transaction_count, 0) AS transactions,
    COALESCE(a.revenue, 0.00) AS revenue,
    CASE WHEN a.active_month IS NULL THEN 'GAP MONTH' ELSE 'ACTIVE' END AS status
FROM all_months m
LEFT JOIN monthly_activity a ON m.period = a.active_month
ORDER BY m.period;


--------------------------------------------------------------------------------
-- QUERY 3: SELF-JOIN / LAG - Month-over-Month Growth Rate
-- Technique: Window function LAG() to access prior row
-- Purpose: Calculate MoM delta and percentage change per platform
--------------------------------------------------------------------------------

WITH monthly_by_platform AS (
    SELECT 
        source_platform,
        strftime('%Y-%m', sale_date) AS period,
        ROUND(SUM(royalty_amount_usd), 2) AS revenue
    FROM sales_fact
    GROUP BY source_platform, strftime('%Y-%m', sale_date)
),
with_previous AS (
    SELECT 
        source_platform,
        period,
        revenue,
        LAG(revenue, 1) OVER (PARTITION BY source_platform ORDER BY period) AS prev_revenue
    FROM monthly_by_platform
)
SELECT 
    source_platform,
    period,
    '$' || printf("%.2f", revenue) AS current_revenue,
    '$' || printf("%.2f", COALESCE(prev_revenue, 0)) AS previous_revenue,
    '$' || printf("%.2f", revenue - COALESCE(prev_revenue, 0)) AS absolute_change,
    CASE 
        WHEN prev_revenue IS NULL OR prev_revenue = 0 THEN 'N/A'
        ELSE printf("%.1f", (revenue - prev_revenue) * 100.0 / prev_revenue) || '%'
    END AS pct_growth
FROM with_previous
ORDER BY source_platform, period DESC;


--------------------------------------------------------------------------------
-- QUERY 4: CORRELATED SUBQUERY - Dominant Platform Per Month
-- Technique: EXISTS clause with correlated subquery
-- Purpose: Identify which platform earned the most revenue each month
--------------------------------------------------------------------------------

WITH monthly_aggregate AS (
    SELECT 
        strftime('%Y-%m', sale_date) AS period,
        source_platform,
        ROUND(SUM(royalty_amount_usd), 2) AS revenue
    FROM sales_fact
    GROUP BY strftime('%Y-%m', sale_date), source_platform
)
SELECT 
    m.period,
    m.source_platform AS dominant_platform,
    '$' || printf("%.2f", m.revenue) AS top_revenue,
    (SELECT ROUND(MAX(sub.revenue), 2) 
     FROM monthly_aggregate sub 
     WHERE sub.period = m.period) AS confirmation
FROM monthly_aggregate m
WHERE m.revenue = (
    SELECT MAX(sub.revenue) 
    FROM monthly_aggregate sub 
    WHERE sub.period = m.period
)
ORDER BY m.period DESC;


--------------------------------------------------------------------------------
-- QUERY 5: COMPLEX AGGREGATION - Pareto Analysis (80/20 Rule)
-- Technique: HAVING with cumulative percentages, CASE filtering
-- Purpose: Identify which titles drive 80% of total revenue
--------------------------------------------------------------------------------

WITH title_revenue AS (
    SELECT 
        COALESCE(series, '(Unmatched)') AS work_group,
        canonical_work_slug,
        SUM(quantity) AS units_sold,
        ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
        COUNT(*) AS transaction_count
    FROM sales_fact
    GROUP BY COALESCE(series, '(Unmatched)'), canonical_work_slug
),
ranked_with_running AS (
    SELECT 
        work_group,
        canonical_work_slug,
        total_revenue,
        units_sold,
        transaction_count,
        ROUND(SUM(total_revenue) OVER (ORDER BY total_revenue DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2) AS cumulative_revenue,
        ROUND(SUM(total_revenue) OVER (), 2) AS grand_total,
        ROUND((SUM(total_revenue) OVER (ORDER BY total_revenue DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) / SUM(total_revenue) OVER ()) * 100, 1) AS cumulative_pct
    FROM title_revenue
)
SELECT 
    work_group,
    canonical_work_slug,
    '$' || printf("%.2f", total_revenue) AS revenue,
    units_sold,
    transaction_count,
    cumulative_revenue,
    cumulative_pct || '%' AS running_share
FROM ranked_with_running
WHERE cumulative_pct <= 80
ORDER BY cumulative_revenue DESC;


-- ============================================================
-- FORECASTING & TREND ANALYSIS QUERIES
-- ============================================================
-- Advanced patterns for time-series smoothing, run-rate calculation,
-- and diversification risk tracking. These support the dashboard's
-- forecasting page visualizations.

--------------------------------------------------------------------------------
-- QUERY 6: ROLLING MOVING AVERAGES (3-month & 12-month)
-- Technique: ROWS BETWEEN x PRECEDING AND CURRENT ROW frame specification
-- Purpose: Smooth volatile monthly data to reveal underlying trends
--------------------------------------------------------------------------------

WITH all_revenue AS (
    SELECT strftime('%Y-%m', sale_date) AS period, SUM(royalty_amount_usd) AS revenue
    FROM sales_fact WHERE source_platform LIKE '%acx%' GROUP BY 1
    
    UNION ALL
    
    SELECT strftime('%Y-%m', sale_date), SUM(royalty_amount_usd)
    FROM sales_fact WHERE source_platform NOT LIKE '%acx%' GROUP BY 1
    
    UNION ALL
    
    SELECT strftime('%Y-%m', sale_date), SUM(royalty_amount_usd)
    FROM kenp_reads WHERE royalty_amount_usd > 0 GROUP BY 1
    
    UNION ALL
    
    SELECT strftime('%Y-%m', sale_date), SUM(net_earnings)
    FROM fact_patreon_earnings GROUP BY 1
    
    UNION ALL
    
    SELECT strftime('%Y-%m', sale_date), SUM(net_sales)
    FROM fact_woo_sales GROUP BY 1
    
    UNION ALL
    
    SELECT strftime('%Y-%m', sale_date), SUM(royalty_amount_usd)
    FROM fact_aubooks_sales GROUP BY 1
),
combined AS (SELECT period, SUM(revenue) AS revenue FROM all_revenue GROUP BY 1 ORDER BY 1),
with_ma AS (
    SELECT 
        period,
        revenue,
        ROUND(AVG(revenue) OVER (ORDER BY period ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS ma_3month,
        ROUND(AVG(revenue) OVER (ORDER BY period ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 2) AS ma_12month
    FROM combined
)
SELECT 
    period,
    '$' || printf("%.2f", revenue) AS monthly_revenue,
    '$' || printf("%.2f", ma_3month) AS "3-Month MA",
    '$' || printf("%.2f", ma_12month) AS "12-Month MA"
FROM with_ma
ORDER BY period ASC;


--------------------------------------------------------------------------------
-- QUERY 7: TRAILING 12-MONTH (TTM) RUN RATE
-- Technique: Cumulative sum over rolling window for annualized revenue
-- Purpose: Annualize current performance while eliminating seasonality
--------------------------------------------------------------------------------

WITH all_revenue AS (
    SELECT strftime('%Y-%m', sale_date) AS period, SUM(royalty_amount_usd) AS revenue
    FROM sales_fact WHERE source_platform LIKE '%acx%' GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), SUM(royalty_amount_usd)
    FROM sales_fact WHERE source_platform NOT LIKE '%acx%' GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), SUM(royalty_amount_usd)
    FROM kenp_reads WHERE royalty_amount_usd > 0 GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), SUM(net_earnings)
    FROM fact_patreon_earnings GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), SUM(net_sales)
    FROM fact_woo_sales GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), SUM(royalty_amount_usd)
    FROM fact_aubooks_sales GROUP BY 1
),
combined AS (SELECT period, SUM(revenue) AS revenue FROM all_revenue GROUP BY 1 ORDER BY 1),
with_ttm AS (
    SELECT 
        period,
        revenue,
        ROUND(SUM(revenue) OVER (ORDER BY period ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 2) AS ttm_revenue
    FROM combined
)
SELECT 
    period,
    '$' || printf("%.2f", revenue) AS "Monthly Revenue",
    '$' || printf("%.2f", ttm_revenue) AS "TTM Run Rate"
FROM with_ttm
ORDER BY period DESC
LIMIT 24;


--------------------------------------------------------------------------------
-- QUERY 8: PLATFORM DIVERSIFICATION / CONCENTRATION METRICS
-- Technique: Self-join + partition window to find max share per period
-- Purpose: Track whether revenue becomes more or less concentrated over time
--------------------------------------------------------------------------------

WITH monthly_by_platform AS (
    SELECT strftime('%Y-%m', sale_date) AS period, 'ACX' AS platform, ROUND(SUM(royalty_amount_usd), 2) AS revenue
    FROM sales_fact WHERE source_platform LIKE '%acx%' GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), 'Amazon KDP', ROUND(SUM(royalty_amount_usd), 2)
    FROM sales_fact WHERE source_platform NOT LIKE '%acx%' GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), 'KU Reads', ROUND(SUM(royalty_amount_usd), 2)
    FROM kenp_reads WHERE royalty_amount_usd > 0 GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), 'Patreon', ROUND(SUM(net_earnings), 2)
    FROM fact_patreon_earnings GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), 'WooCommerce', ROUND(SUM(net_sales), 2)
    FROM fact_woo_sales GROUP BY 1
    UNION ALL SELECT strftime('%Y-%m', sale_date), 'AU Books', ROUND(SUM(royalty_amount_usd), 2)
    FROM fact_aubooks_sales GROUP BY 1
),
totals AS (
    SELECT period, SUM(revenue) AS total_revenue FROM monthly_by_platform GROUP BY 1
),
shares AS (
    SELECT 
        m.period,
        m.platform,
        m.revenue,
        ROUND((m.revenue * 100.0 / t.total_revenue), 1) AS platform_share_pct,
        t.total_revenue
    FROM monthly_by_platform m
    JOIN totals t ON m.period = t.period
),
concentration AS (
    SELECT 
        period,
        MAX(platform_share_pct) AS top_platform_share_pct,
        COUNT(DISTINCT platform) AS active_platforms,
        SUM(total_revenue) AS total_revenue
    FROM shares
    GROUP BY period, total_revenue
),
ranked AS (
    SELECT 
        period,
        top_platform_share_pct,
        active_platforms,
        '$' || printf("%.2f", total_revenue) AS total_revenue,
        ROUND(((active_platforms - 1) * 100.0 / 5), 1) AS diversification_score,
        CASE 
            WHEN top_platform_share_pct >= 80 THEN '⚠️ HIGH RISK'
            WHEN top_platform_share_pct >= 70 THEN '⚡ MODERATE-RISK'
            ELSE '✓ HEALTHY'
        END AS risk_level
    FROM concentration
)
SELECT 
    period,
    top_platform_share_pct || '%' AS "Top Platform Share",
    active_platforms AS "Active Platforms",
    diversity_risk.level,
    total_revenue,
    risk_level
FROM ranked
ORDER BY period DESC;