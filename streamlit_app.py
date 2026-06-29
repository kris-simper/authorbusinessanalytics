"""Author Business Analytics Dashboard - Interactive Web Interface."""

import streamlit as st
import sqlite3
from pathlib import Path
import pandas as pd
import plotly.express as px
import datetime


# ===================================================================
# PAGE CONFIGURATION
# ===================================================================

st.set_page_config(
    page_title="Author Revenue Dashboard",
    page_icon="📊",
    layout="wide",              # Full-width, not centered narrow column
    initial_sidebar_state="expanded"  # Sidebar visible by default
)


# ===================================================================
# HELPER FUNCTIONS
# ===================================================================

def get_db_connection():
    """Connect to the SQLite database. Caches connection for reuse."""
    db_path = Path("data/author_analytics.db")
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    return conn


@st.cache_data(ttl=300)
def query_database(sql_query, params=None):
    """Execute SQL query with optional parameters and return DataFrame."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        import pandas as pd
        df = pd.read_sql_query(sql_query, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Database error: {e}")
        return None


def format_currency(value):
    """Format numbers as currency. Handles None/NaN safely."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "$0.00"
    return f"${float(value):,.2f}"


def format_number(value):
    """Format large numbers with K/M suffixes. Handles None/NaN safely."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "0"
    value = float(value)
    if value >= 1_000_000:
        return f"{value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"{value/1_000:.1f}K"
    else:
        return str(int(value))


def prettify_series(slug):
    """Convert slug format to Title Case (e.g., 'fallen_gods' → 'Fallen Gods')."""
    if not slug or slug == '(Unmatched)':
        return slug
    return slug.replace('_', ' ').title()
   
   
def date_where_clause(column_name="sale_date", use_filter=False, date_range=None):
    """Build a SQL WHERE clause fragment for date filtering."""
    if not use_filter or date_range is None or len(date_range) < 2:
        return ""
    start = date_range[0].strftime('%Y-%m-%d')
    end = date_range[1].strftime('%Y-%m-%d')
    return f"AND {column_name} >= '{start}' AND {column_name} <= '{end}'"
    
    
# ===================================================================
# SIDEBAR NAVIGATION
# ===================================================================

with st.sidebar:
    st.title("🗺️ Navigation")
    
    selected_page = st.radio(
        "Go to:",
        ["Home Overview", "Platform Breakdown", "KENP Analysis", "Series Performance"]
    )
    
    st.divider()
    
    # Date range filter (applies to all pages)
    # Date range filter (applies to all pages)
    st.header("Date Filter")
    from datetime import date
    date_range = st.date_input(
        "Date Range",
        value=(date(2018, 1, 1), date(2026, 12, 31)),
    )
    
    use_filter = st.checkbox("Apply date filter to queries", value=False)
    
    # Build SQL WHERE clause from selected dates
    if len(date_range) == 2:
        start_date = date_range[0].strftime('%Y-%m-%d')
        end_date = date_range[1].strftime('%Y-%m-%d')
        date_filter_sql = f"AND sale_date BETWEEN '{start_date}' AND '{end_date}'"
    else:
        date_filter_sql = ""  # Single date clicked, don't filter
    
    st.divider()
    
    # Platform filter
    st.header("Platform Filter")
    platforms = st.multiselect(
        "Hide these platforms:",
        ["ACX", "Amazon KDP", "Patreon", "WooCommerce", "Audiobooks Unleashed"],
        default=[]
    )


# ===================================================================
# HEADER SECTION
# ===================================================================

st.markdown("# 📈 Author Revenue Dashboard")
st.caption("Interactive analytics across 5 distribution platforms (11,686 records)")


# ===================================================================
# HOME OVERVIEW PAGE
# ===================================================================

if selected_page == "Home Overview":
    # Fetch total revenue summary
    summary_query = f"""
        WITH all_platforms AS (
            SELECT 'ACX Audiobooks' AS source_platform,
                   ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
                   COUNT(*) AS record_count
            FROM sales_fact
            WHERE source_platform LIKE '%acx%' AND 1=1 {date_filter_sql}
            
            UNION ALL
            
            SELECT 'Amazon KDP' AS source_platform,
                   ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
                   COUNT(*) AS record_count
            FROM sales_fact
            WHERE source_platform NOT LIKE '%acx%' AND 1=1 {date_filter_sql}
            
            UNION ALL
            
            SELECT 'KU Reads' AS source_platform,
                   ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
                   COUNT(*) AS record_count
            FROM kenp_reads
            WHERE royalty_amount_usd > 0 AND 1=1 {date_filter_sql}
            
            UNION ALL
            
            SELECT 'Patreon' AS source_platform,
                   ROUND(SUM(net_earnings), 2) AS total_revenue,
                   COUNT(*) AS record_count
            FROM fact_patreon_earnings
            WHERE 1=1 {date_filter_sql}
            
            UNION ALL
            
            SELECT 'WooCommerce' AS source_platform,
                   ROUND(SUM(net_sales), 2) AS total_revenue,
                   COUNT(*) AS record_count
            FROM fact_woo_sales
            WHERE 1=1 {date_filter_sql}
            
            UNION ALL
            
            SELECT 'AU Books Wide' AS source_platform,
                   ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
                   COUNT(*) AS record_count
            FROM fact_aubooks_sales
            WHERE 1=1 {date_filter_sql}
        )
        SELECT source_platform, total_revenue, record_count
        FROM all_platforms
        WHERE total_revenue > 0
        ORDER BY total_revenue DESC
    """
    df_summary = query_database(summary_query)
    
    # Create columns for KPI cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Revenue (All Platforms)", "$74,777")
        st.caption("Across 5 platforms")
    
    with col2:
        st.metric("Records Analyzed", "11,686")
        st.caption("5 fact tables")
    
    with col3:
        st.metric("Active Period", "2018–2026")
        st.caption("8+ years of data")
    
    with col4:
        st.metric("Top Performing Month", "Jun 2025")
        st.caption("~$1,200 in royalties")
    
    st.divider()
    
    # Main chart area
    tab1, tab2, tab3, tab4 = st.tabs(["Monthly Trend", "Platform Distribution", "YoY Growth", "Details"])
    
    with tab1:
        monthly_all_query = f"""
            WITH acx_sales AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'ACX Audiobooks' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue,
                       SUM(quantity) AS units
                FROM sales_fact
                WHERE source_platform LIKE '%acx%' {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
            ),
            kdp_sales AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'Amazon KDP' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue,
                       SUM(quantity) AS units
                FROM sales_fact
                WHERE source_platform NOT LIKE '%acx%' {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
            ),
            ku_reads AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'KU Reads' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue,
                       ROUND(SUM(equivalent_copies), 0) AS units
                FROM kenp_reads
                WHERE royalty_amount_usd > 0 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
            ),
            patreon_income AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'Patreon' AS channel,
                       ROUND(SUM(net_earnings), 2) AS revenue,
                       0 AS units
                FROM fact_patreon_earnings
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
            ),
            woo_orders AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'WooCommerce' AS channel,
                       ROUND(SUM(net_sales), 2) AS revenue,
                       SUM(items_sold) AS units
                FROM fact_woo_sales
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
            ),
            au_wide AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'AU Books Wide' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue,
                       SUM(quantity) AS units
                FROM fact_aubooks_sales
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
            )
            SELECT * FROM acx_sales
            UNION ALL SELECT * FROM kdp_sales
            UNION ALL SELECT * FROM ku_reads
            UNION ALL SELECT * FROM patreon_income
            UNION ALL SELECT * FROM woo_orders
            UNION ALL SELECT * FROM au_wide
            ORDER BY period ASC
        """
        df_monthly = query_database(monthly_all_query)
        
        if df_monthly is not None and len(df_monthly) > 0:
            fig = px.bar(
                df_monthly,
                x='period', y='revenue', color='channel',
                color_discrete_map={
                    'ACX Audiobooks': '#6A4C93',
                    'Amazon KDP': '#2E86AB',
                    'KU Reads': '#F18F01',
                    'Patreon': '#A23B72',
                    'WooCommerce': '#3C5B6F',
                    'AU Books Wide': '#5F9EA0'
                },
                title='Monthly Revenue Across All 5 Distribution Channels',
                labels={'revenue': 'Revenue ($)', 'period': 'Month'},
                template='plotly_white'
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        pie_all_query = """
            WITH platform_revenues AS (
                SELECT 'ACX Audiobooks' AS platform, ROUND(SUM(royalty_amount_usd), 2) AS rev
                FROM sales_fact
                WHERE source_platform LIKE '%acx%'
                
                UNION ALL
                
                SELECT 'Amazon KDP' AS platform, ROUND(SUM(royalty_amount_usd), 2) AS rev
                FROM sales_fact
                WHERE source_platform NOT LIKE '%acx%'
                
                UNION ALL
                
                SELECT 'KU Reads' AS platform, ROUND(SUM(royalty_amount_usd), 2) AS rev
                FROM kenp_reads
                WHERE royalty_amount_usd > 0
                
                UNION ALL
                
                SELECT 'Patreon' AS platform, ROUND(SUM(net_earnings), 2) AS rev
                FROM fact_patreon_earnings
                
                UNION ALL
                
                SELECT 'WooCommerce' AS platform, ROUND(SUM(net_sales), 2) AS rev
                FROM fact_woo_sales
                
                UNION ALL
                
                SELECT 'AU Books Wide' AS platform, ROUND(SUM(royalty_amount_usd), 2) AS rev
                FROM fact_aubooks_sales
            )
            SELECT platform, rev FROM platform_revenues WHERE rev > 0
            ORDER BY rev DESC
        """
        df_pie = query_database(pie_all_query)
        
        if df_pie is not None and len(df_pie) > 0:
            fig = px.pie(
                df_pie,
                values='rev', names='platform',
                title='Revenue Share Across 6 Distribution Channels (%)',
                color_discrete_sequence=['#6A4C93', '#2E86AB', '#F18F01', '#A23B72', '#3C5B6F', '#5F9EA0']
            )
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        yoy_query = f"""
            WITH acx_yearly AS (
                SELECT strftime('%Y', sale_date) AS year,
                       'ACX Audiobooks' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact
                WHERE source_platform LIKE '%acx%' {date_filter_sql}
                GROUP BY strftime('%Y', sale_date)
            ),
            kdp_yearly AS (
                SELECT strftime('%Y', sale_date) AS year,
                       'Amazon KDP' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact
                WHERE source_platform NOT LIKE '%acx%' {date_filter_sql}
                GROUP BY strftime('%Y', sale_date)
            ),
            ku_yearly AS (
                SELECT strftime('%Y', sale_date) AS year,
                       'KU Reads' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM kenp_reads
                WHERE royalty_amount_usd > 0 {date_filter_sql}
                GROUP BY strftime('%Y', sale_date)
            ),
            patreon_yearly AS (
                SELECT strftime('%Y', sale_date) AS year,
                       'Patreon' AS channel,
                       ROUND(SUM(net_earnings), 2) AS revenue
                FROM fact_patreon_earnings
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y', sale_date)
            ),
            woo_yearly AS (
                SELECT strftime('%Y', sale_date) AS year,
                       'WooCommerce' AS channel,
                       ROUND(SUM(net_sales), 2) AS revenue
                FROM fact_woo_sales
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y', sale_date)
            ),
            au_yearly AS (
                SELECT strftime('%Y', sale_date) AS year,
                       'AU Books Wide' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM fact_aubooks_sales
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y', sale_date)
            )
            SELECT * FROM acx_yearly
            UNION ALL SELECT * FROM kdp_yearly
            UNION ALL SELECT * FROM ku_yearly
            UNION ALL SELECT * FROM patreon_yearly
            UNION ALL SELECT * FROM woo_yearly
            UNION ALL SELECT * FROM au_yearly
            ORDER BY year ASC
        """
        df_yoy = query_database(yoy_query)
        
        if df_yoy is not None and len(df_yoy) > 0:
            # Summary metrics
            total_by_year = df_yoy.groupby('year')['revenue'].sum().reset_index()
            latest_year = total_by_year['year'].iloc[-1]
            prev_year = total_by_year['year'].iloc[-2] if len(total_by_year) > 1 else None
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Latest Year", latest_year)
                st.caption(f"${total_by_year['revenue'].iloc[-1]:,.2f} total")
            
            with col2:
                if prev_year:
                    growth = ((total_by_year['revenue'].iloc[-1] - total_by_year['revenue'].iloc[-2]) 
                              / total_by_year['revenue'].iloc[-2] * 100)
                    st.metric("YoY Change", f"{growth:+.1f}%")
                    st.caption(f"vs ${total_by_year['revenue'].iloc[-2]:,.2f} in {prev_year}")
                else:
                    st.metric("YoY Change", "N/A")
            
            with col3:
                st.metric("Best Year", total_by_year.loc[total_by_year['revenue'].idxmax(), 'year'])
                st.caption(f"${total_by_year['revenue'].max():,.2f}")
            
            st.divider()
            
            # Line chart
            fig = px.line(
                df_yoy,
                x='year', y='revenue', color='channel',
                markers=True,
                title='Year-over-Year Revenue by Platform',
                labels={'revenue': 'Revenue ($)', 'year': 'Year', 'channel': 'Platform'},
                template='plotly_white',
                color_discrete_map={
                    'ACX Audiobooks': '#6A4C93',
                    'Amazon KDP': '#2E86AB',
                    'KU Reads': '#F18F01',
                    'Patreon': '#A23B72',
                    'WooCommerce': '#3C5B6F',
                    'AU Books Wide': '#5F9EA0'
                }
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Data table
            with st.expander("View Yearly Breakdown Table"):
                # Pivot for easier reading
                pivot_df = df_yoy.pivot(index='year', columns='channel', values='revenue').fillna(0)
                pivot_df['Total'] = pivot_df.sum(axis=1)
                st.dataframe(
                    pivot_df.style.format('${:,.2f}'),
                    use_container_width=True
                )
        else:
            st.info("No data available for the selected date range.")
    
    with tab4:
        if df_summary is not None:
            st.dataframe(df_summary, use_container_width=True, hide_index=True)

# ===================================================================
# PLATFORM BREAKDOWN PAGE
# ===================================================================

elif selected_page == "Platform Breakdown":
    st.header("Revenue Comparison Across All Platforms")
    
    # Query each platform separately for comparison
    acx_query = f"""
        SELECT 
            COUNT(*) AS sales_count,
            SUM(royalty_amount_usd) AS royalty_sum,
            AVG(royalty_amount_usd) AS avg_transaction
        FROM sales_fact 
        WHERE source_platform LIKE '%acx%' {date_where_clause('sale_date', use_filter, date_range)}
    """
    kdp_query = f"""
        SELECT 
            COUNT(*) AS sales_count,
            SUM(royalty_amount_usd) AS royalty_sum,
            AVG(royalty_amount_usd) AS avg_transaction
        FROM sales_fact 
        WHERE source_platform NOT LIKE '%acx%' {date_where_clause('sale_date', use_filter, date_range)}
    """
    woo_query = f"""
        SELECT 
            SUM(items_sold) AS units_sold,
            SUM(net_sales) AS revenue_sum,
            AVG(net_sales) AS avg_order
        FROM fact_woo_sales
        WHERE 1=1 {date_where_clause('sale_date', use_filter, date_range)}
    """
    patreon_query = f"""
        SELECT 
            COUNT(*) AS months_recorded,
            SUM(net_earnings) AS total_net
        FROM fact_patreon_earnings
        WHERE 1=1 {date_where_clause('sale_date', use_filter, date_range)}
    """
    au_books_query = f"""
        SELECT 
            COUNT(*) AS record_count,
            SUM(royalty_amount_usd) AS royalty_sum,
            AVG(royalty_amount_usd) AS avg_transaction,
            COUNT(DISTINCT distributor) AS distributors
        FROM fact_aubooks_sales
        WHERE 1=1 {date_where_clause('sale_date', use_filter, date_range)}
    """
    
    df_acx = query_database(acx_query)
    df_kdp = query_database(kdp_query)
    df_woo = query_database(woo_query)
    df_patreon = query_database(patreon_query)
    df_aubooks = query_database(au_books_query)
    
    col1, col2, col3 = st.columns(3)
    col4, col5 = st.columns(2)
    
    with col1:
        st.subheader("🎙️ ACX Audiobooks")
        if df_acx is not None:
            st.metric("Transactions", format_number(df_acx['sales_count'].iloc[0]))
            st.metric("Total Royalty", format_currency(df_acx['royalty_sum'].iloc[0]))
            st.metric("Avg per Transaction", format_currency(df_acx['avg_transaction'].iloc[0]))

    with col2:
        st.subheader("📚 Amazon KDP")
        if df_kdp is not None:
            st.metric("Transactions", format_number(df_kdp['sales_count'].iloc[0]))
            st.metric("Total Royalty", format_currency(df_kdp['royalty_sum'].iloc[0]))
            st.metric("Avg per Transaction", format_currency(df_kdp['avg_transaction'].iloc[0]))

    with col3:
        st.subheader("🎧 AU Books Wide")
        if df_aubooks is not None:
            st.metric("Line Items", format_number(df_aubooks['record_count'].iloc[0]))
            st.metric("Total Royalty", format_currency(df_aubooks['royalty_sum'].iloc[0]))
            st.metric("Distributors", format_number(df_aubooks['distributors'].iloc[0]))

    with col4:
        st.subheader("🛍️ WooCommerce")
        if df_woo is not None:
            st.metric("Units Sold", format_number(df_woo['units_sold'].iloc[0]))
            st.metric("Total Sales", format_currency(df_woo['revenue_sum'].iloc[0]))
            st.metric("Avg Order Value", format_currency(df_woo['avg_order'].iloc[0]))

    with col5:
        st.subheader("💝 Patreon")
        if df_patreon is not None:
            st.metric("Months Recorded", format_number(df_patreon['months_recorded'].iloc[0]))
            st.metric("Net Earnings", format_currency(df_patreon['total_net'].iloc[0]))


# ===================================================================
# KENP ANALYSIS PAGE
# ===================================================================

elif selected_page == "KENP Analysis":
    st.header("Kindle Unlimited Engagement Metrics")
    
    kenp_query = f"""
        SELECT 
            strftime('%Y-%m', sale_date) AS period,
            SUM(page_count) AS pages_read,
            ROUND(SUM(royalty_amount_usd), 2) AS revenue,
            ROUND(SUM(equivalent_copies), 2) AS equiv_copies
        FROM kenp_reads
        WHERE royalty_amount_usd IS NOT NULL AND royalty_amount_usd > 0
            {date_where_clause('sale_date', use_filter, date_range)}
        GROUP BY strftime('%Y-%m', sale_date)
        ORDER BY period DESC
    """
    df_kenp = query_database(kenp_query)
    
    if df_kenp is not None and len(df_kenp) > 0:
        # Summary metrics
        total_pages = df_kenp['pages_read'].sum()
        total_equiv = df_kenp['equiv_copies'].sum()
        total_revenue = df_kenp['revenue'].sum()
        avg_per_copy = total_revenue / total_equiv if total_equiv > 0 else 0
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Pages Read (KU)", format_number(total_pages))
        col2.metric("Equivalent Copies", format_number(total_equiv))
        col3.metric("KU Royalties", format_currency(total_revenue))
        col4.metric("Revenue per Copy", format_currency(avg_per_copy))
        
        st.divider()
        
        # Charts
        col_left, col_right = st.columns(2)
        
        with col_left:
            fig = px.line(
                df_kenp.sort_values('period'),
                x='period', y='pages_read',
                markers=True,
                title='Pages Read Over Time'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col_right:
            fig = px.scatter(
                df_kenp,
                x='pages_read', y='revenue',
                hover_data=['period'],   # Show period on hover only
                title='Page Volume vs Revenue Correlation',
                labels={'pages_read': 'Pages Read', 'revenue': 'Revenue ($)'}
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Show raw data table (collapsible)
        with st.expander("View Raw Data"):
            st.dataframe(df_kenp, use_container_width=True, hide_index=True)


# ===================================================================
# SERIES PERFORMANCE PAGE
# ===================================================================

elif selected_page == "Series Performance":
    st.header("Book Series Revenue Rankings")
    
    series_query = f"""
        SELECT 
            COALESCE(series, '(Unmatched)') AS series_name,
            COUNT(DISTINCT canonical_work_slug) AS unique_titles,
            SUM(quantity) AS units_sold,
            ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
            ROUND(AVG(royalty_rate * 100), 1) AS avg_royalty_pct
        FROM sales_fact
        WHERE (series IS NOT NULL OR source_platform = 'woocommerce')
            {date_where_clause('sale_date', use_filter, date_range)}
        GROUP BY COALESCE(series, '(Unmatched)')
        HAVING total_revenue > 0
        ORDER BY total_revenue DESC
    """
    df_series = query_database(series_query)
    
    if df_series is not None and len(df_series) > 0:
        # Ranking bar chart
        df_chart = df_series.head(10).copy()
        df_chart['series_name'] = df_chart['series_name'].apply(prettify_series)

        fig = px.bar(
            df_chart,
            y='series_name',
            x='total_revenue',
            orientation='h',
            title='Top 10 Series by Revenue',
            labels={'series_name': 'Series', 'total_revenue': 'Revenue ($)'},
            template='plotly_white'
        )
        fig.update_layout(yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
        
        st.divider()
        
        st.subheader("Full Series Breakdown")

        df_series_display = df_series.copy()
        df_series_display['series_name'] = df_series_display['series_name'].apply(prettify_series)

        st.dataframe(
            df_series_display.style.format({
                'total_revenue': '${:,.2f}',
                'units_sold': '{:,}',
                'avg_royalty_pct': '{:.1f}'
            }),
            use_container_width=True,
            hide_index=True
        )


# ===================================================================
# FOOTER
# ===================================================================

st.divider()
import datetime
refresh_ts = datetime.datetime.fromtimestamp(Path('data/author_analytics.db').stat().st_mtime)
st.caption(
    "🔧 Powered by Author Business Analytics pipeline. "
    f"Database last refreshed on: {refresh_ts.strftime('%Y-%m-%d %H:%M')} | "
    "Built with Streamlit + Plotly."
)