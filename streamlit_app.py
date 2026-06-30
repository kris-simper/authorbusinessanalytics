"""
Author Business Analytics Dashboard — Interactive Web Interface.

Streamlit-powered analytics dashboard connecting to the SQLite data warehouse
created by the ETL pipeline. Provides multi-platform revenue tracking, trend
analysis, forecasting visualizations, and series performance rankings.

Architecture:
- Uses @st.cache_data decorator on database queries for automatic caching
- Color palette centralized for consistent branding across all charts
- Date filtering applied via standardized where clause builder
- Lazy database connection initialization for improved startup speed
"""

import datetime
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


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
# CENTRALIZED CONSTANTS
# ===================================================================

DATABASE_PATH = Path("data/author_analytics.db")

COLOR_PALETTE = {
    'ACX Audiobooks': '#6A4C93',
    'Amazon KDP': '#2E86AB',
    'KU Reads': '#F18F01',
    'Patreon': '#A23B72',
    'WooCommerce': '#3C5B6F',
    'Audiobooks Unleashed': '#5F9EA0',
    'Books': '#3C5B6F',
    'Merchandise': '#F18F01',
}

PLATFORM_NAMES = [
    'ACX', 'Amazon KDP', 'Patreon',
    'WooCommerce', 'Audiobooks Unleashed',
]


# ===================================================================
# HELPER FUNCTIONS
# ===================================================================

def get_db_connection() -> sqlite3.Connection | None:
    """Connect to the SQLite database. Caches connection for reuse."""
    if not DATABASE_PATH.exists():
        st.error(f"Database not found at {DATABASE_PATH}. Run the ETL pipeline first.")
        return None
    conn = sqlite3.connect(DATABASE_PATH)
    return conn


@st.cache_data(ttl=300)
def query_database(sql_query: str, params=None) -> pd.DataFrame | None:
    """Execute SQL query with optional parameters and return DataFrame."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        df = pd.read_sql_query(sql_query, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Database error: {e}")
        return None


def format_currency(value) -> str:
    """Format numbers as currency. Handles None/NaN safely."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "$0.00"
    return f"${float(value):,.2f}"


def format_number(value) -> str:
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


def prettify_series(slug: str) -> str:
    """Convert slug format to Title Case (e.g., 'fallen_gods' → 'Fallen Gods')."""
    if not slug or slug == '(Unmatched)':
        return slug
    return slug.replace('_', ' ').title()
   
   
def date_where_clause(column_name: str = "sale_date", use_filter: bool = False, date_range=None) -> str:
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
        ["Home Overview", "Platform Breakdown", "Revenue Insights", "KENP Analysis", "Series Performance", "Forecasting"]
    )
    
    st.divider()
    
    # Date range filter (applies to all pages)
    # Date range filter (applies to all pages)
    st.header("Date Filter")
    date_range = st.date_input(
        "Date Range",
        value=(datetime.date(2018, 1, 1), datetime.date(2026, 12, 31)),
    )
    
    use_filter = st.checkbox("Apply date filter to queries", value=False)
    
    # Build SQL WHERE clause from selected dates
    if len(date_range) == 2:
        date_filter_sql = date_where_clause('sale_date', use_filter, date_range)
    else:
        date_filter_sql = ""
    
    st.divider()
    
    # Platform filter
    st.header("Platform Filter")
    hide_platforms = st.multiselect(
        "Hide these platforms:",
        PLATFORM_NAMES,
        default=[],
    )


# ===================================================================
# HEADER SECTION
# ===================================================================

st.markdown("# 📈 Author Revenue Dashboard")
st.caption("Interactive analytics across 6 distribution platforms (11,686 records)")


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
            
            SELECT 'Audiobooks Unleashed' AS source_platform,
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
    
    # Create columns for Dynamic KPI cards
    # Top performing month across all platforms
    top_month_query = f"""
        WITH all_months AS (
            SELECT strftime('%Y-%m', sale_date) AS period,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM sales_fact
            WHERE source_platform LIKE '%acx%' {date_filter_sql}
            GROUP BY strftime('%Y-%m', sale_date)
            
            UNION ALL
            
            SELECT strftime('%Y-%m', sale_date) AS period,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM sales_fact
            WHERE source_platform NOT LIKE '%acx%' {date_filter_sql}
            GROUP BY strftime('%Y-%m', sale_date)
            
            UNION ALL
            
            SELECT strftime('%Y-%m', sale_date) AS period,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM kenp_reads
            WHERE royalty_amount_usd > 0 {date_filter_sql}
            GROUP BY strftime('%Y-%m', sale_date)
            
            UNION ALL
            
            SELECT strftime('%Y-%m', sale_date) AS period,
                   ROUND(SUM(net_earnings), 2) AS revenue
            FROM fact_patreon_earnings
            WHERE 1=1 {date_filter_sql}
            GROUP BY strftime('%Y-%m', sale_date)
            
            UNION ALL
            
            SELECT strftime('%Y-%m', sale_date) AS period,
                   ROUND(SUM(net_sales), 2) AS revenue
            FROM fact_woo_sales
            WHERE 1=1 {date_filter_sql}
            GROUP BY strftime('%Y-%m', sale_date)
            
            UNION ALL
            
            SELECT strftime('%Y-%m', sale_date) AS period,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM fact_aubooks_sales
            WHERE 1=1 {date_filter_sql}
            GROUP BY strftime('%Y-%m', sale_date)
        )
        SELECT period, SUM(revenue) AS total_revenue
        FROM all_months
        GROUP BY period
        ORDER BY total_revenue DESC
        LIMIT 1
    """
    df_top_month = query_database(top_month_query)
    
    # Active date range across all tables
    date_range_query = """
        SELECT MIN(d) AS earliest, MAX(d) AS latest FROM (
            SELECT MIN(sale_date) AS d FROM sales_fact
            UNION ALL SELECT MAX(sale_date) FROM sales_fact
            UNION ALL SELECT MIN(sale_date) FROM kenp_reads
            UNION ALL SELECT MAX(sale_date) FROM kenp_reads
            UNION ALL SELECT MIN(sale_date) FROM fact_patreon_earnings
            UNION ALL SELECT MAX(sale_date) FROM fact_patreon_earnings
            UNION ALL SELECT MIN(sale_date) FROM fact_woo_sales
            UNION ALL SELECT MAX(sale_date) FROM fact_woo_sales
            UNION ALL SELECT MIN(sale_date) FROM fact_aubooks_sales
            UNION ALL SELECT MAX(sale_date) FROM fact_aubooks_sales
        )
    """
    df_dates = query_database(date_range_query)
    
    # Compute all KPI values dynamically
    total_revenue = df_summary['total_revenue'].sum() if df_summary is not None and len(df_summary) > 0 else 0
    total_records = df_summary['record_count'].sum() if df_summary is not None and len(df_summary) > 0 else 0
    
    if df_top_month is not None and len(df_top_month) > 0:
        # Convert "2024-11" to "Nov 2024"
        year, month_num = df_top_month['period'].iloc[0].split('-')
        month_abbr = datetime.date(int(year), int(month_num), 1).strftime('%b')
        top_month_label = f"{month_abbr} {year}"
        top_month_rev = df_top_month['total_revenue'].iloc[0]
    else:
        top_month_label = "N/A"
        top_month_rev = 0
    
    if df_dates is not None and len(df_dates) > 0:
        earliest = pd.to_datetime(df_dates['earliest'].iloc[0]).year
        latest = pd.to_datetime(df_dates['latest'].iloc[0]).year
        active_period = f"{earliest}–{latest}"
    else:
        active_period = "N/A"
    
    # Create columns for KPI cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Revenue (All Platforms)", format_currency(total_revenue))
        st.caption("Across 6 platforms")
    
    with col2:
        st.metric("Records Analyzed", format_number(int(total_records)))
        st.caption("6 fact tables")
    
    with col3:
        st.metric("Active Period", active_period)
        st.caption(f"{latest - earliest + 1 if 'earliest' in dir() and 'latest' in dir() else ''}+ years of data")
    
    with col4:
        st.metric("Top Performing Month", top_month_label)
        st.caption(f"{format_currency(top_month_rev)} in royalties")
    
    st.divider()
    
    # Main chart area
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Monthly Trend", "Platform Distribution", "YoY Growth", "Cumulative Trajectory", "Details"])
    
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
                       'Audiobooks Unleashed' AS channel,
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
                color_discrete_map=COLOR_PALETTE,
                title='Monthly Revenue Across All 6 Distribution Channels',
                labels={'revenue': 'Revenue ($)', 'period': 'Month'},
                template='plotly_white'
            )
            st.plotly_chart(fig, width='stretch')
            # --- Channel share over time (100% stacked) ---
            st.subheader("Channel Share Over Time (%)")
            st.caption("Relative contribution of each platform to total monthly revenue")
            
            df_share = df_monthly.copy()
            monthly_totals = df_share.groupby('period')['revenue'].transform('sum')
            df_share['share_pct'] = (df_share['revenue'] / monthly_totals * 100).round(1)
            
            fig_share = px.bar(
                df_share,
                x='period',
                y='share_pct',
                color='channel',
                color_discrete_map=COLOR_PALETTE,
                labels={'share_pct': 'Share (%)', 'period': 'Month', 'channel': 'Channel'},
                title='',
            )
            fig_share.update_layout(
                height=400,
                barmode='stack',
                hovermode='x unified',
                legend_title_text='Channel',
            )
            fig_share.update_xaxes(tickangle=-45, nticks=20, tickfont=dict(size=9))
            fig_share.update_yaxes(ticksuffix='%', range=[0, 100])
            st.plotly_chart(fig_share, width='stretch')
    
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
                
                SELECT 'Audiobooks Unleashed' AS platform, ROUND(SUM(royalty_amount_usd), 2) AS rev
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
                color_discrete_sequence=[COLOR_PALETTE[k] for k in ['ACX Audiobooks', 'Amazon KDP', 'KU Reads', 'Patreon', 'WooCommerce', 'Audiobooks Unleashed']]
            )
            st.plotly_chart(fig, width='stretch')

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
                       'Audiobooks Unleashed' AS channel,
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
                color_discrete_map=COLOR_PALETTE,
            )
            st.plotly_chart(fig, width='stretch')
            
            # Data table
            with st.expander("View Yearly Breakdown Table"):
                # Pivot for easier reading
                pivot_df = df_yoy.pivot(index='year', columns='channel', values='revenue').fillna(0)
                pivot_df['Total'] = pivot_df.sum(axis=1)
                st.dataframe(
                    pivot_df.style.format('${:,.2f}'),
                    width='stretch'
                )
        else:
            st.info("No data available for the selected date range.")

    with tab4:
        st.subheader("📈 Cumulative Revenue Accumulation")
        st.caption("Total lifetime revenue progression by platform through present day")
        
        # Query: monthly totals with cumulative sum using window function
        cum_query = f"""
            WITH monthly_totals AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'ACX Audiobooks' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact
                WHERE source_platform LIKE '%acx%' {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'Amazon KDP' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact
                WHERE source_platform NOT LIKE '%acx%' {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'KU Reads' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM kenp_reads
                WHERE royalty_amount_usd > 0 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'Patreon' AS channel,
                       ROUND(SUM(net_earnings), 2) AS revenue
                FROM fact_patreon_earnings
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'WooCommerce' AS channel,
                       ROUND(SUM(net_sales), 2) AS revenue
                FROM fact_woo_sales
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'Audiobooks Unleashed' AS channel,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM fact_aubooks_sales
                WHERE 1=1 {date_filter_sql}
                GROUP BY strftime('%Y-%m', sale_date)
            )
            SELECT 
                period,
                channel,
                revenue,
                ROUND(SUM(revenue) OVER (PARTITION BY channel ORDER BY period ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2) AS cumulative_revenue,
                ROUND(SUM(revenue) OVER (ORDER BY period ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2) AS total_cumulative
            FROM monthly_totals
            ORDER BY period ASC, channel ASC
        """
        df_cum = query_database(cum_query)
        
        if df_cum is not None and len(df_cum) > 0:
            # --- Top-level cumulative summary ---
            grand_total = df_cum['total_cumulative'].iloc[-1]
            platform_totals = df_cum.groupby('channel')['cumulative_revenue'].tail(1).sort_values(ascending=False)
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Lifetime Revenue (All Platforms)", format_currency(grand_total))
            col2.metric("Platforms Tracked", df_cum['channel'].nunique())
            col3.metric("Data Points", format_number(len(df_cum)))
            
            st.divider()
            
            # --- Chart: Stacked cumulative lines ---
            fig = px.line(
                df_cum,
                x='period',
                y='cumulative_revenue',
                color='channel',
                color_discrete_map=COLOR_PALETTE,
                markers=True,
                title='Cumulative Revenue Accumulation by Platform',
                labels={'cumulative_revenue': 'Cumulative Revenue (USD)', 'period': 'Month'},
                template='plotly_white',
            )
            
            fig.update_layout(
                height=500,
                hovermode='x unified',
                legend_title_text='Platform',
                xaxis_tickangle=-45,
            )
            fig.update_xaxes(tickformat='%b %Y')
            fig.update_yaxes(tickprefix='$', tickformat=',.0f')
            
            st.plotly_chart(fig, width='stretch')
            
            # --- Data table toggle ---
            with st.expander("View Cumulative Data Table"):
                display_df = df_cum.copy()
                display_df['Cumulative Revenue'] = display_df['cumulative_revenue'].apply(format_currency)
                display_df['Monthly Revenue'] = display_df['revenue'].apply(format_currency)
                display_df = display_df[['period', 'channel', 'Monthly Revenue', 'Cumulative Revenue']]
                st.dataframe(display_df, hide_index=True, width='stretch')
        
        else:
            st.warning("No cumulative data available for the selected date range.")
            
    with tab5:
        if df_summary is not None:
            st.dataframe(df_summary, width='stretch', hide_index=True)

# ===================================================================
# PLATFORM BREAKDOWN PAGE (WITH TABS)
# ===================================================================

elif selected_page == "Platform Breakdown":
    st.header("Revenue Comparison Across All Platforms")
    
    tab_platforms, tab_aubooks_dist, tab_woo = st.tabs(["Platform Comparison", "AU Books Distributors", "WooCommerce"])
    
    # ============================================================
    # TAB 1: PLATFORM COMPARISON (existing content, unchanged)
    # ============================================================
    with tab_platforms:
    
        # Query each platform separately for comparison
        acx_query = f"""
            SELECT 
                COUNT(*) AS sales_count,
                SUM(royalty_amount_usd) AS royalty_sum,
                AVG(royalty_amount_usd) AS avg_transaction
            FROM sales_fact 
            WHERE source_platform LIKE '%acx%' {date_filter_sql}
        """
        kdp_query = f"""
            SELECT 
                COUNT(*) AS sales_count,
                SUM(royalty_amount_usd) AS royalty_sum,
                AVG(royalty_amount_usd) AS avg_transaction
            FROM sales_fact 
            WHERE source_platform LIKE '%acx%' {date_filter_sql}
        """
        woo_query = f"""
            SELECT 
                SUM(items_sold) AS units_sold,
                SUM(net_sales) AS revenue_sum,
                AVG(net_sales) AS avg_order
            FROM fact_woo_sales
            WHERE 1=1 {date_filter_sql}
        """
        patreon_query = f"""
            SELECT 
                COUNT(*) AS months_recorded,
                SUM(net_earnings) AS total_net
            FROM fact_patreon_earnings
            WHERE 1=1 {date_filter_sql}
        """
        au_books_query = f"""
            SELECT 
                COUNT(*) AS record_count,
                SUM(royalty_amount_usd) AS royalty_sum,
                AVG(royalty_amount_usd) AS avg_transaction,
                COUNT(DISTINCT distributor) AS distributors
            FROM fact_aubooks_sales
            WHERE 1=1 {date_filter_sql}
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
            st.subheader("🎧 Audiobooks Unleashed")
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

    # ============================================================
    # TAB 2: AU BOOKS DISTRIBUTOR BREAKDOWN (NEW!)
    # ============================================================
    with tab_aubooks_dist:
        st.subheader("🎧 Distributor Performance")
        st.caption("Revenue breakdown across Audiobooks Unleashed distribution partners")
        
        # --- Query: aggregated by distributor ---
        dist_query = f"""
            SELECT 
                COALESCE(distributor, 'Unknown') AS distributor,
                ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
                SUM(quantity) AS total_units,
                COUNT(*) AS transaction_count,
                ROUND(AVG(royalty_amount_usd), 2) AS avg_transaction_value
            FROM fact_aubooks_sales
            WHERE 1=1 {date_filter_sql}
            GROUP BY COALESCE(distributor, 'Unknown')
            ORDER BY total_revenue DESC
        """
        df_dist = query_database(dist_query)
        
        if df_dist is not None and len(df_dist) > 0:
            # --- KPI strip ---
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Revenue", format_currency(df_dist['total_revenue'].sum()))
            col2.metric("Distributors", df_dist['distributor'].nunique())
            col3.metric("Units Sold", format_number(int(df_dist['total_units'].sum())))
            col4.metric("Transactions", format_number(int(df_dist['transaction_count'].sum())))
            
            st.divider()
            
            # --- Chart 1: Revenue by distributor (horizontal bar) ---
            st.subheader("Revenue by Distributor")
            fig_rev = px.bar(
                df_dist,
                x='total_revenue',
                y='distributor',
                orientation='h',
                color_discrete_sequence=[COLOR_PALETTE['Audiobooks Unleashed']],
                hover_data={
                    'total_revenue': ':$,.2f',
                    'total_units': True,
                    'transaction_count': True,
                    'avg_transaction_value': ':$,.2f',
                },
                labels={
                    'total_revenue': 'Revenue (USD)',
                    'distributor': 'Distributor',
                },
            )
            fig_rev.update_yaxes(categoryorder='total ascending')
            fig_rev.update_layout(
                height=max(400, len(df_dist) * 45 + 150),
                xaxis_tickformat='$,.0f',
                showlegend=False,
                margin=dict(l=20, r=20, t=20, b=40),
            )
            st.plotly_chart(fig_rev, width='stretch')
            
            # --- Chart 2 & 3: Side-by-side secondary metrics ---
            col_left, col_right = st.columns(2)
            
            with col_left:
                st.subheader("Units by Distributor")
                fig_units = px.bar(
                    df_dist,
                    x='total_units',
                    y='distributor',
                    orientation='h',
                    color_discrete_sequence=[COLOR_PALETTE['Audiobooks Unleashed']],
                    hover_data={'total_units': True, 'transaction_count': True},
                    labels={'total_units': 'Units Sold', 'distributor': 'Distributor'},
                )
                fig_units.update_yaxes(categoryorder='total ascending')
                fig_units.update_layout(
                    height=400,
                    showlegend=False,
                    margin=dict(l=20, r=20, t=20, b=40),
                )
                st.plotly_chart(fig_units, width='stretch')
            
            with col_right:
                st.subheader("Avg Transaction Value")
                fig_avg = px.bar(
                    df_dist,
                    x='avg_transaction_value',
                    y='distributor',
                    orientation='h',
                    color_discrete_sequence=[COLOR_PALETTE['Audiobooks Unleashed']],
                    hover_data={'avg_transaction_value': ':$,.2f', 'transaction_count': True},
                    labels={'avg_transaction_value': 'Avg Transaction (USD)', 'distributor': 'Distributor'},
                )
                fig_avg.update_yaxes(categoryorder='total ascending')
                fig_avg.update_layout(
                    height=400,
                    showlegend=False,
                    margin=dict(l=20, r=20, t=20, b=40),
                )
                st.plotly_chart(fig_avg, width='stretch')
            
            st.divider()
            
            # --- Data table ---
            st.subheader("Distributor Detail")
            display_df = df_dist.copy()
            display_df.columns = [
                "Distributor", "Revenue (USD)", "Units Sold",
                "Transactions", "Avg Transaction",
            ]
            display_df["Revenue (USD)"] = display_df["Revenue (USD)"].apply(format_currency)
            display_df["Avg Transaction"] = display_df["Avg Transaction"].apply(format_currency)
            display_df["Units Sold"] = display_df["Units Sold"].apply(format_number)
            display_df["Transactions"] = display_df["Transactions"].apply(format_number)
            st.dataframe(display_df, hide_index=True, width='stretch')
        
        else:
            st.warning("No AU Books data found for the selected period.")

    # ============================================================
    # TAB 3: WOOCOMMERCE BOOKS VS MERCH
    # ============================================================
    with tab_woo:
        st.subheader("🛍️ Books vs. Merchandise")
        st.caption("Revenue composition over time — how much is book sales vs. merch?")
        
        woo_breakdown_query = f"""
            SELECT 
                strftime('%Y-%m', sale_date) AS period,
                CASE 
                    WHEN series IS NOT NULL THEN 'Books'
                    ELSE 'Merchandise'
                END AS category,
                SUM(items_sold) AS units,
                ROUND(SUM(net_sales), 2) AS revenue
            FROM fact_woo_sales
            WHERE 1=1 {date_filter_sql}
            GROUP BY period, category
            ORDER BY period ASC
        """
        df_woo_break = query_database(woo_breakdown_query)
        
        if df_woo_break is not None and len(df_woo_break) > 0:
            # --- KPI strip ---
            pivot = df_woo_break.pivot_table(index='period', columns='category', values='revenue', aggfunc='sum').fillna(0)
            books_total = pivot['Books'].sum() if 'Books' in pivot.columns else 0
            merch_total = pivot['Merchandise'].sum() if 'Merchandise' in pivot.columns else 0
            grand_total = books_total + merch_total
            books_pct = (books_total / grand_total * 100) if grand_total > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Book Revenue", format_currency(books_total))
            col2.metric("Merch Revenue", format_currency(merch_total))
            col3.metric("Books % of Total", f"{books_pct:.1f}%")
            
            st.divider()
            
            # --- Chart 1: Stacked bar — Revenue composition ---
            st.subheader("Revenue Composition Over Time")
            
            fig_woo = px.bar(
                df_woo_break,
                x='period',
                y='revenue',
                color='category',
                color_discrete_map=COLOR_PALETTE,
                labels={'revenue': 'Revenue (USD)', 'period': 'Month', 'category': 'Category'},
                title='',
            )
            fig_woo.update_layout(
                height=450,
                barmode='stack',
                hovermode='x unified',
                legend_title_text='Category',
            )
            fig_woo.update_xaxes(tickangle=-45, nticks=20, tickfont=dict(size=9))
            fig_woo.update_yaxes(tickprefix='$', tickformat=',.0f')
            st.plotly_chart(fig_woo, width='stretch')
            
            # --- Chart 2: 100% stacked bar — Category share ---
            st.subheader("Category Share Over Time (%)")
            
            df_share = df_woo_break.copy()
            monthly_totals = df_share.groupby('period')['revenue'].transform('sum')
            df_share['share_pct'] = (df_share['revenue'] / monthly_totals * 100).round(1)
            
            fig_share = px.bar(
                df_share,
                x='period',
                y='share_pct',
                color='category',
                color_discrete_map={
                    'Books': '#3C5B6F',
                    'Merchandise': '#F18F01'
                },
                labels={'share_pct': 'Share (%)', 'period': 'Month', 'category': 'Category'},
                title='',
            )
            fig_share.update_layout(
                height=400,
                barmode='stack',
                hovermode='x unified',
                legend_title_text='Category',
            )
            fig_share.update_xaxes(tickangle=-45, nticks=20, tickfont=dict(size=9))
            fig_share.update_yaxes(ticksuffix='%', range=[0, 100])
            st.plotly_chart(fig_share, width='stretch')
            
            st.divider()
            
            # --- Data table ---
            with st.expander("View Monthly Breakdown"):
                display_df = df_woo_break.copy()
                display_df.columns = ["Month", "Category", "Units Sold", "Revenue (USD)"]
                display_df["Revenue (USD)"] = display_df["Revenue (USD)"].apply(format_currency)
                display_df["Units Sold"] = display_df["Units Sold"].apply(format_number)
                st.dataframe(display_df, hide_index=True, width='stretch')
        
        else:
            st.warning("No WooCommerce data found for the selected period.")


# ===================================================================
# REVENUE INSIGHTS PAGE (NEW!)
# ===================================================================

elif selected_page == "Revenue Insights":
    st.header("📊 Revenue Concentration Analysis")
    st.caption("Applying the Pareto principle — which titles drive the majority of revenue?")
    
    # --- Pareto query: cumulative revenue ranking by title ---
    pareto_query = f"""
        WITH title_revenue AS (
            SELECT 
                canonical_work_slug,
                COALESCE(series, '(Unmatched)') AS work_group,
                SUM(quantity) AS units_sold,
                ROUND(SUM(royalty_amount_usd), 2) AS total_revenue
            FROM sales_fact
            WHERE canonical_work_slug IS NOT NULL
            {date_filter_sql}
            GROUP BY canonical_work_slug, series
        ),
        ranked AS (
            SELECT 
                canonical_work_slug,
                work_group,
                units_sold,
                total_revenue,
                ROW_NUMBER() OVER (ORDER BY total_revenue DESC) AS rank,
                SUM(total_revenue) OVER () AS grand_total,
                ROUND(SUM(total_revenue) OVER (ORDER BY total_revenue DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2) AS cumulative_revenue,
                ROUND(SUM(total_revenue) OVER (ORDER BY total_revenue DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 100.0 / SUM(total_revenue) OVER (), 1) AS cumulative_pct
            FROM title_revenue
        )
        SELECT * FROM ranked ORDER BY rank ASC
    """
    df_pareto = query_database(pareto_query)
    
    if df_pareto is not None and len(df_pareto) > 0:
        # --- Summary metrics ---
        total_titles = len(df_pareto)
        titles_for_80 = len(df_pareto[df_pareto['cumulative_pct'] <= 80])
        pct_of_titles = (titles_for_80 / total_titles * 100) if total_titles > 0 else 0
        grand_total = df_pareto['grand_total'].iloc[0]
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Titles", format_number(total_titles))
        col2.metric("Titles Driving 80% Revenue", format_number(titles_for_80))
        col3.metric("% of Titles for 80%", f"{pct_of_titles:.0f}%")
        col4.metric("Total Revenue", format_currency(grand_total))
        
        st.divider()
        
        # --- Pareto combo chart (bars + cumulative line) ---
        st.subheader("Title Revenue Ranking with Cumulative Percentage")
        
        # Limit to top 20 for readability
        df_chart = df_pareto.head(20).copy()
        
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Bars: per-title revenue
        fig.add_trace(
            go.Bar(
                x=df_chart['canonical_work_slug'],
                y=df_chart['total_revenue'],
                name='Revenue (USD)',
                marker_color='#2E86AB',
                hovertemplate='<b>%{x}</b><br>Revenue: $%{y:,.2f}<extra></extra>',
            ),
            secondary_y=False,
        )
        
        # Line: cumulative percentage
        fig.add_trace(
            go.Scatter(
                x=df_chart['canonical_work_slug'],
                y=df_chart['cumulative_pct'],
                name='Cumulative %',
                mode='lines+markers',
                line=dict(color='#E63946', width=2),
                marker=dict(size=6),
                hovertemplate='<b>%{x}</b><br>Cumulative: %{y:.1f}%<extra></extra>',
            ),
            secondary_y=True,
        )
        
        # 80% reference line
        fig.add_hline(
            y=80,
            line_dash="dash",
            line_color="gray",
            annotation_text="80% threshold",
            secondary_y=True,
        )
        
        fig.update_xaxes(tickangle=-45, tickfont=dict(size=9))
        fig.update_yaxes(title_text="Revenue (USD)", secondary_y=False, tickprefix='$', tickformat=',.0f')
        fig.update_yaxes(title_text="Cumulative %", secondary_y=True, range=[0, 105], ticksuffix='%')
        fig.update_layout(
            height=550,
            hovermode='x unified',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=20, b=120),
        )
        
        st.plotly_chart(fig, width='stretch')
        
        st.divider()
        
        # --- Secondary analysis: Revenue by series ---
        st.subheader("Revenue Concentration by Series")
        
        series_pareto_query = f"""
            WITH series_rev AS (
                SELECT 
                    COALESCE(series, '(Unmatched)') AS series_name,
                    ROUND(SUM(royalty_amount_usd), 2) AS total_revenue
                FROM sales_fact
                WHERE series IS NOT NULL
                {date_filter_sql}
                GROUP BY series
            ),
            ranked AS (
                SELECT 
                    series_name,
                    total_revenue,
                    ROW_NUMBER() OVER (ORDER BY total_revenue DESC) AS rank,
                    ROUND(SUM(total_revenue) OVER (ORDER BY total_revenue DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 100.0 / SUM(total_revenue) OVER (), 1) AS cumulative_pct
                FROM series_rev
            )
            SELECT * FROM ranked ORDER BY rank ASC
        """
        df_series_par = query_database(series_pareto_query)
        
        if df_series_par is not None and len(df_series_par) > 0:
            df_series_par['series_name'] = df_series_par['series_name'].apply(prettify_series)
            
            fig_series = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig_series.add_trace(
                go.Bar(
                    x=df_series_par['series_name'],
                    y=df_series_par['total_revenue'],
                    name='Revenue (USD)',
                    marker_color='#6A4C93',
                    hovertemplate='<b>%{x}</b><br>Revenue: $%{y:,.2f}<extra></extra>',
                ),
                secondary_y=False,
            )
            fig_series.add_trace(
                go.Scatter(
                    x=df_series_par['series_name'],
                    y=df_series_par['cumulative_pct'],
                    name='Cumulative %',
                    mode='lines+markers',
                    line=dict(color='#E63946', width=2),
                    hovertemplate='<b>%{x}</b><br>Cumulative: %{y:.1f}%<extra></extra>',
                ),
                secondary_y=True,
            )
            fig_series.add_hline(y=80, line_dash="dash", line_color="gray", annotation_text="80%", secondary_y=True)
            
            fig_series.update_xaxes(tickangle=-45, tickfont=dict(size=10))
            fig_series.update_yaxes(title_text="Revenue (USD)", secondary_y=False, tickprefix='$', tickformat=',.0f')
            fig_series.update_yaxes(title_text="Cumulative %", secondary_y=True, range=[0, 105], ticksuffix='%')
            fig_series.update_layout(
                height=450,
                hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=20, r=20, t=20, b=80),
            )
            st.plotly_chart(fig_series, width='stretch')
        
        st.divider()
        
        # --- Full data table ---
        with st.expander("View Full Pareto Table (All Titles)"):
            display_df = df_pareto.copy()
            display_df.columns = [
                "Rank", "Title Slug", "Series", "Units Sold",
                "Revenue (USD)", "Grand Total", "Cumulative Revenue", "Cumulative %",
            ]
            display_df["Revenue (USD)"] = display_df["Revenue (USD)"].apply(format_currency)
            display_df["Cumulative Revenue"] = display_df["Cumulative Revenue"].apply(format_currency)
            display_df["Grand Total"] = display_df["Grand Total"].apply(format_currency)
            display_df["Cumulative %"] = display_df["Cumulative %"].astype(str) + "%"
            st.dataframe(display_df, hide_index=True, width='stretch')
    
    else:
        st.warning("No data available for Pareto analysis with the selected filters.")


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
            {date_filter_sql}
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
            st.plotly_chart(fig, width='stretch')
        
        with col_right:
            fig = px.scatter(
                df_kenp,
                x='pages_read', y='revenue',
                hover_data=['period'],   # Show period on hover only
                title='Page Volume vs Revenue Correlation',
                labels={'pages_read': 'Pages Read', 'revenue': 'Revenue ($)'}
            )
            st.plotly_chart(fig, width='stretch')
        
        # Show raw data table (collapsible)
        with st.expander("View Raw Data"):
            st.dataframe(df_kenp, width='stretch', hide_index=True)


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
            {date_filter_sql}
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
        st.plotly_chart(fig, width='stretch')
        
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
            width='stretch',
            hide_index=True
        )


# ===================================================================
# FORECASTING PAGE (NEW!)
# ===================================================================

elif selected_page == "Forecasting":
    st.header("🔮 Revenue Seasonality & Forecasting")
    st.caption("Identify seasonal patterns and revenue cyclicality across all platforms")
    
    # ============================================================
    # CHART 1: SEASONALITY HEATMAP
    # ============================================================
    st.subheader("Monthly Revenue Heatmap")
    st.caption("Color intensity = total revenue. Rows = years, Columns = months. Spot seasonal patterns at a glance.")
    
    heatmap_query = f"""
        WITH monthly AS (
            SELECT strftime('%Y', sale_date) AS year,
                   strftime('%m', sale_date) AS month,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM sales_fact
            WHERE 1=1 {date_filter_sql}
            GROUP BY 1, 2
            
            UNION ALL
            
            SELECT strftime('%Y', sale_date) AS year,
                   strftime('%m', sale_date) AS month,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM kenp_reads
            WHERE royalty_amount_usd > 0 {date_filter_sql}
            GROUP BY 1, 2
            
            UNION ALL
            
            SELECT strftime('%Y', sale_date) AS year,
                   strftime('%m', sale_date) AS month,
                   ROUND(SUM(net_earnings), 2) AS revenue
            FROM fact_patreon_earnings
            WHERE 1=1 {date_filter_sql}
            GROUP BY 1, 2
            
            UNION ALL
            
            SELECT strftime('%Y', sale_date) AS year,
                   strftime('%m', sale_date) AS month,
                   ROUND(SUM(net_sales), 2) AS revenue
            FROM fact_woo_sales
            WHERE 1=1 {date_filter_sql}
            GROUP BY 1, 2
            
            UNION ALL
            
            SELECT strftime('%Y', sale_date) AS year,
                   strftime('%m', sale_date) AS month,
                   ROUND(SUM(royalty_amount_usd), 2) AS revenue
            FROM fact_aubooks_sales
            WHERE 1=1 {date_filter_sql}
            GROUP BY 1, 2
        )
        SELECT year, month, ROUND(SUM(revenue), 2) AS revenue
        FROM monthly
        GROUP BY year, month
        ORDER BY year, month
    """
    df_heat = query_database(heatmap_query)
    
    if df_heat is not None and len(df_heat) > 0:
        # --- Pivot into year × month matrix ---
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        pivot = df_heat.pivot(index='year', columns='month', values='revenue')
        # Ensure all 12 months exist as columns
        for m in range(1, 13):
            m_str = f"{m:02d}"
            if m_str not in pivot.columns:
                pivot[m_str] = 0
        pivot = pivot[sorted(pivot.columns)]  # Sort by month
        pivot.columns = month_names  # Replace "01" with "Jan", etc.
        pivot = pivot.fillna(0)
        
        # --- KPI strip ---
        best_month = df_heat.loc[df_heat['revenue'].idxmax()]
        worst_month = df_heat.loc[df_heat['revenue'].idxmin()]
        monthly_std = df_heat.groupby('month')['revenue'].std()
        most_consistent = monthly_std.idxmin()
        least_consistent = monthly_std.idxmax()
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Best Month Ever", f"{month_names[int(best_month['month'])-1]} {best_month['year']}")
        col1.caption(format_currency(best_month['revenue']))
        col2.metric("Revenue in Best Month", format_currency(best_month['revenue']))
        col3.metric("Most Consistent Month", month_names[int(most_consistent)-1])
        col3.caption("Lowest variance year-over-year")
        col4.metric("Most Variable Month", month_names[int(least_consistent)-1])
        col4.caption("Highest variance year-over-year")
        
        st.divider()
        
        # --- Heatmap visualization ---
        fig_heat = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale='YlOrRd',
            hovertemplate='<b>%{y} %{x}</b><br>Revenue: $%{z:,.2f}<extra></extra>',
            colorbar=dict(title="Revenue ($)", tickprefix="$"),
        ))
        
        fig_heat.update_layout(
            title="Revenue Heatmap: Years × Months",
            xaxis_title="Month",
            yaxis_title="Year",
            height=max(350, len(pivot) * 50 + 100),
            yaxis=dict(autorange="reversed"),  # Most recent year at top
        )
        
        st.plotly_chart(fig_heat, width='stretch')
        st.divider()
        
        # ============================================================
        # CHART 4: ROLLING MOVING AVERAGES (3-month & 12-month)
        # ============================================================
        st.subheader("Revenue Trends with Moving Averages")
        st.caption("Raw monthly revenue with 3-month and 12-month smoothed trend lines")
        
        ma_query = f"""
            WITH monthly AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact WHERE source_platform LIKE '%acx%' {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(royalty_amount_usd), 2)
                FROM sales_fact WHERE source_platform NOT LIKE '%acx%' {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(royalty_amount_usd), 2)
                FROM kenp_reads WHERE royalty_amount_usd > 0 {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(net_earnings), 2)
                FROM fact_patreon_earnings WHERE 1=1 {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(net_sales), 2)
                FROM fact_woo_sales WHERE 1=1 {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(royalty_amount_usd), 2)
                FROM fact_aubooks_sales WHERE 1=1 {date_filter_sql} GROUP BY 1
            ),
            combined AS (SELECT period, SUM(revenue) AS revenue FROM monthly GROUP BY 1 ORDER BY 1),
            with_ma AS (
                SELECT 
                    period,
                    revenue,
                    ROUND(AVG(revenue) OVER (ORDER BY period ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS ma_3month,
                    ROUND(AVG(revenue) OVER (ORDER BY period ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 2) AS ma_12month
                FROM combined
            )
            SELECT * FROM with_ma
        """
        df_ma = query_database(ma_query)
        
        if df_ma is not None and len(df_ma) > 0:
            fig_ma = go.Figure()
            
            # Raw revenue bars
            fig_ma.add_trace(go.Bar(
                x=df_ma['period'],
                y=df_ma['revenue'],
                name='Monthly Revenue',
                marker_color='lightgray',
                hovertemplate='<b>%{x}</b><br>Revenue: $%{y:,.2f}<extra></extra>',
                opacity=0.5,
            ))
            
            # 3-month MA line
            fig_ma.add_trace(go.Scatter(
                x=df_ma['period'],
                y=df_ma['ma_3month'],
                name='3-Month MA',
                mode='lines',
                line=dict(color='#E63946', width=3),
                hovertemplate='<b>%{x}</b><br>MA-3: $%{y:,.2f}<extra></extra>',
            ))
            
            # 12-month MA line
            fig_ma.add_trace(go.Scatter(
                x=df_ma['period'],
                y=df_ma['ma_12month'],
                name='12-Month MA',
                mode='lines',
                line=dict(color='#2E86AB', width=4),
                hovertemplate='<b>%{x}</b><br>MA-12: $%{y:,.2f}<extra></extra>',
            ))
            
            fig_ma.update_layout(
                height=450,
                barmode='overlay',
                hovermode='x unified',
                legend_title_text='',
                margin=dict(l=20, r=20, t=20, b=40),
            )
            fig_ma.update_xaxes(tickangle=-45, nticks=20, tickfont=dict(size=9))
            fig_ma.update_yaxes(title_text="Revenue (USD)", tickprefix='$', tickformat=',.0f')
            st.plotly_chart(fig_ma, width='stretch')
        
        else:
            st.warning("No data available for moving average analysis.")        

        st.divider()
        
        # ============================================================
        # CHART 5: TRAILING 12-MONTH RUN RATE
        # ============================================================
        st.subheader("Trailing 12-Month Run Rate")
        st.caption("Annualized revenue removing seasonality completely — true growth trajectory")
        
        ttm_query = f"""
            WITH monthly AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact WHERE source_platform LIKE '%acx%' {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(royalty_amount_usd), 2)
                FROM sales_fact WHERE source_platform NOT LIKE '%acx%' {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(royalty_amount_usd), 2)
                FROM kenp_reads WHERE royalty_amount_usd > 0 {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(net_earnings), 2)
                FROM fact_patreon_earnings WHERE 1=1 {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(net_sales), 2)
                FROM fact_woo_sales WHERE 1=1 {date_filter_sql} GROUP BY 1
                UNION ALL SELECT strftime('%Y-%m', sale_date), ROUND(SUM(royalty_amount_usd), 2)
                FROM fact_aubooks_sales WHERE 1=1 {date_filter_sql} GROUP BY 1
            ),
            combined AS (SELECT period, SUM(revenue) AS revenue FROM monthly GROUP BY 1 ORDER BY 1),
            with_ttm AS (
                SELECT 
                    period,
                    revenue,
                    ROUND(SUM(revenue) OVER (ORDER BY period ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 2) AS ttm_revenue
                FROM combined
            )
            SELECT * FROM with_ttm
        """
        df_ttm = query_database(ttm_query)
        
        if df_ttm is not None and len(df_ttm) > 0:
            latest_ttm = df_ttm['ttm_revenue'].iloc[-1]
            start_ttm = df_ttm['ttm_revenue'].iloc[0]
            ttm_growth_pct = ((latest_ttm - start_ttm) / start_ttm * 100) if start_ttm > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Current TTM", format_currency(latest_ttm))
            col2.metric("TTM Growth Since Start", f"{ttm_growth_pct:+.1f}%")
            col3.metric("TTM Periods", format_number(len(df_ttm)))
            
            st.divider()
            
            fig_ttm = go.Figure()
            fig_ttm.add_trace(go.Scatter(
                x=df_ttm['period'],
                y=df_ttm['ttm_revenue'],
                name='Trailing 12-Month Revenue',
                mode='lines+markers',
                line=dict(color='#A23B72', width=4),
                marker=dict(size=6),
                fill='tozeroy',
                fillcolor='rgba(162, 59, 114, 0.15)',
                hovertemplate='<b>%{x}</b><br>TTM: $%{y:,.2f}<extra></extra>',
            ))
            fig_ttm.update_layout(
                height=400,
                hovermode='x unified',
                margin=dict(l=20, r=20, t=20, b=40),
            )
            fig_ttm.update_xaxes(tickangle=-45, nticks=20, tickfont=dict(size=9))
            fig_ttm.update_yaxes(title_text="TTM Revenue (USD)", tickprefix='$', tickformat=',.0f')
            st.plotly_chart(fig_ttm, width='stretch')
        
        else:
            st.warning("No data available for TTM run rate analysis.")    

        st.divider()
        
        # ============================================================
        # CHART 6: PLATFORM DIVERSIFICATION TREND
        # ============================================================
        st.subheader("Revenue Concentration by Top Platform")
        st.caption("Tracking platform dominance over time — higher concentration means more risk")
        
        div_query = f"""
            WITH monthly_by_platform AS (
                SELECT strftime('%Y-%m', sale_date) AS period,
                       'ACX' AS platform,
                       ROUND(SUM(royalty_amount_usd), 2) AS revenue
                FROM sales_fact WHERE source_platform LIKE '%acx%' {date_filter_sql} GROUP BY 1
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date), 'Amazon KDP',
                       ROUND(SUM(royalty_amount_usd), 2)
                FROM sales_fact WHERE source_platform NOT LIKE '%acx%' {date_filter_sql} GROUP BY 1
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date), 'KU Reads',
                       ROUND(SUM(royalty_amount_usd), 2)
                FROM kenp_reads WHERE royalty_amount_usd > 0 {date_filter_sql} GROUP BY 1
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date), 'Patreon',
                       ROUND(SUM(net_earnings), 2)
                FROM fact_patreon_earnings WHERE 1=1 {date_filter_sql} GROUP BY 1
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date), 'WooCommerce',
                       ROUND(SUM(net_sales), 2)
                FROM fact_woo_sales WHERE 1=1 {date_filter_sql} GROUP BY 1
                
                UNION ALL
                
                SELECT strftime('%Y-%m', sale_date), 'Audiobooks Unleashed',
                       ROUND(SUM(royalty_amount_usd), 2)
                FROM fact_aubooks_sales WHERE 1=1 {date_filter_sql} GROUP BY 1
            ),
            totals AS (
                SELECT period, SUM(revenue) AS total_revenue FROM monthly_by_platform GROUP BY 1
            ),
            with_share AS (
                SELECT 
                    m.period,
                    m.platform,
                    m.revenue,
                    ROUND((m.revenue * 100.0 / t.total_revenue), 1) AS platform_share_pct,
                    t.total_revenue
                FROM monthly_by_platform m
                JOIN totals t ON m.period = t.period
            ),
            top_platform_share AS (
                SELECT period, MAX(platform_share_pct) AS top_share_pct, total_revenue
                FROM with_share
                GROUP BY period, total_revenue
            )
            SELECT period, top_share_pct, total_revenue FROM top_platform_share ORDER BY period ASC
        """
        df_div = query_database(div_query)
        
        if df_div is not None and len(df_div) > 0:
            latest_concentration = df_div['top_share_pct'].iloc[-1]
            avg_concentration = df_div['top_share_pct'].mean()
            max_concentration = df_div['top_share_pct'].max()
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Top Platform Share (Latest)", f"{latest_concentration:.1f}%")
            col2.metric("Average Concentration", f"{avg_concentration:.1f}%")
            col3.metric("Max Concentration Ever", f"{max_concentration:.1f}%")
            
            st.divider()
            
            fig_div_line = go.Figure()
            fig_div_line.add_trace(go.Scatter(
                x=df_div['period'],
                y=df_div['top_share_pct'],
                name='Top Platform Share (%)',
                mode='lines+markers',
                line=dict(color='#F18F01', width=3),
                marker=dict(size=6),
                hovertemplate='<b>%{x}</b><br>Top Platform: %{y:.1f}%<extra></extra>',
            ))
            
            fig_div_line.add_hline(y=80, line_dash="dot", line_color="darkred", annotation_text="⚠️ High Risk")
            fig_div_line.add_hline(y=50, line_dash="dash", line_color="orange", annotation_text="Moderate")
            
            fig_div_line.update_layout(
                height=350,
                hovermode='x unified',
                margin=dict(l=20, r=20, t=50, b=40),
            )
            fig_div_line.update_xaxes(tickangle=-45, nticks=20, tickfont=dict(size=9))
            fig_div_line.update_yaxes(title_text="Top Platform Share (%)", ticksuffix='% ', range=[0, 100])
            st.plotly_chart(fig_div_line, width='stretch')
            
            st.info("**Diversification Score**: Lower concentration is healthier. Below 50% indicates good multi-platform balance. Above 70-80% signals dependency risk on a single channel.")
        
        else:
            st.warning("No data available for diversification analysis.")            
        
        st.divider()
        
        # ============================================================
        # CHART 2: AVERAGE MONTHLY PATTERN (ACROSS ALL YEARS)
        # ============================================================
        st.subheader("Average Revenue by Month (All Years)")
        st.caption("Aggregated across all years to reveal recurring seasonal patterns")
        
        df_avg = df_heat.groupby('month').agg(
            avg_revenue=('revenue', 'mean'),
            min_revenue=('revenue', 'min'),
            max_revenue=('revenue', 'max'),
            std_revenue=('revenue', 'std'),
        ).reset_index()
        df_avg['month_name'] = df_avg['month'].apply(lambda m: month_names[int(m)-1])
        
        fig_avg = go.Figure()
        
        # Min-max range as a shaded area
        fig_avg.add_trace(go.Scatter(
            x=df_avg['month_name'],
            y=df_avg['max_revenue'],
            name='Maximum',
            mode='lines',
            line=dict(width=0),
            hoverinfo='skip',
        ))
        fig_avg.add_trace(go.Scatter(
            x=df_avg['month_name'],
            y=df_avg['min_revenue'],
            name='Range',
            mode='lines',
            line=dict(width=0),
            fill='tonexty',
            fillcolor='rgba(46, 134, 171, 0.15)',
            hoverinfo='skip',
        ))
        
        # Average line
        fig_avg.add_trace(go.Scatter(
            x=df_avg['month_name'],
            y=df_avg['avg_revenue'],
            name='Average Revenue',
            mode='lines+markers',
            line=dict(color='#2E86AB', width=3),
            marker=dict(size=8),
            hovertemplate='<b>%{x}</b><br>Avg: $%{y:,.2f}<extra></extra>',
        ))
        
        fig_avg.update_layout(
            title="Seasonal Revenue Pattern (Min-Max Range + Average)",
            xaxis_title="Month",
            yaxis_title="Revenue (USD)",
            height=400,
            hovermode='x unified',
            yaxis=dict(tickprefix='$', tickformat=',.0f'),
        )
        
        st.plotly_chart(fig_avg, width='stretch')
        
        st.divider()
        
        # ============================================================
        # CHART 3: YEAR-OVER-YEAR MONTHLY COMPARISON
        # ============================================================
        st.subheader("Year-over-Year Monthly Comparison")
        st.caption("Same months lined up across years — are you growing?")
        
        # Pivot for YoY: months as x-axis, years as colored lines
        pivot_yoy = df_heat.copy()
        pivot_yoy['month_name'] = pivot_yoy['month'].apply(lambda m: month_names[int(m)-1])
        
        fig_yoy = px.line(
            pivot_yoy,
            x='month_name',
            y='revenue',
            color='year',
            markers=True,
            labels={'revenue': 'Revenue (USD)', 'month_name': 'Month', 'year': 'Year'},
            title='',
            category_orders={'month_name': month_names},
        )
        fig_yoy.update_layout(
            height=450,
            hovermode='x unified',
            yaxis=dict(tickprefix='$', tickformat=',.0f'),
            legend_title_text='Year',
        )
        
        st.plotly_chart(fig_yoy, width='stretch')
        
        st.divider()
        
        # --- Raw data table ---
        with st.expander("View Monthly Revenue Matrix"):
            display_matrix = pivot.copy()
            for col in display_matrix.columns:
                display_matrix[col] = display_matrix[col].apply(format_currency)
            display_matrix.index.name = 'Year'
            st.dataframe(display_matrix, width='stretch')
    
    else:
        st.warning("No data available for seasonality analysis with the selected filters.")


# ===================================================================
# FOOTER
# ===================================================================

st.divider()
refresh_ts = datetime.datetime.fromtimestamp(DATABASE_PATH.stat().st_mtime)
st.caption(
    "🔧 Powered by Author Business Analytics pipeline. "
    f"Database last refreshed on: {refresh_ts.strftime('%Y-%m-%d %H:%M')} | "
    "Built with Streamlit + Plotly."
)