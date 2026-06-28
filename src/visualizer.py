"""
Visualization module for author business analytics.
Generates publication-quality charts from SQLite database.
"""

import sqlite3
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# Global plot settings for consistent, professional appearance
plt.rcParams.update({
    'figure.figsize': (12, 6),
    'figure.dpi': 150,
    'font.size': 11,
    'axes.grid': True,
    'grid.alpha': 0.3,
    'axes.spines.top': False,
    'axes.spines.right': False,
})

OUTPUT_DIR = Path("results/figures")
DB_PATH = Path("data/author_analytics.db")


def get_connection():
    """Connect to the SQLite database."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")
    return sqlite3.connect(str(DB_PATH))


def chart_monthly_revenue(conn):
    """Line chart: Monthly royalty revenue over time."""
    df = pd.read_sql_query("""
        SELECT
            strftime('%Y-%m', sale_date) AS period,
            SUM(quantity) AS total_units,
            -- CHANGED: royalty_amount → royalty_amount_usd
            ROUND(SUM(royalty_amount_usd), 2) AS total_royalties
        FROM sales_fact
        GROUP BY strftime('%Y-%m', sale_date)
        ORDER BY period ASC
    """, conn)

    df['period_dt'] = pd.to_datetime(df['period'])

    fig, ax1 = plt.subplots(figsize=(14, 6))

    color_revenue = '#2E86AB'
    color_units = '#E63946'

    ax1.bar(df['period_dt'], df['total_royalties'], width=20, alpha=0.7, color=color_revenue, label='Royalties ($)')
    ax1.set_ylabel('Royalty Revenue ($)', color=color_revenue, fontsize=12)
    ax1.tick_params(axis='y', labelcolor=color_revenue)
    ax1.yaxis.set_major_formatter(ticker.FormatStrFormatter('$%d'))

    ax2 = ax1.twinx()
    ax2.plot(df['period_dt'], df['total_units'], color=color_units, marker='o', linewidth=2, label='Units Sold')
    ax2.set_ylabel('Units Sold', color=color_units, fontsize=12)
    ax2.tick_params(axis='y', labelcolor=color_units)

    ax1.set_title('Monthly Royalty Revenue & Units Sold', fontsize=14, fontweight='bold', pad=15)
    ax1.set_xlabel('Reporting Period', fontsize=11)
    ax1.xaxis.set_major_locator(plt.MaxNLocator(12))

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    plt.tight_layout()
    output = OUTPUT_DIR / "monthly_revenue.png"
    plt.savefig(output, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output}")


def chart_series_performance(conn):
    """Horizontal bar chart: Total royalties by book series."""
    df = pd.read_sql_query("""
        SELECT
            series,
            -- CHANGED: royalty_amount → royalty_amount_usd
            ROUND(SUM(royalty_amount_usd), 2) AS total_royalties
        FROM sales_fact
        WHERE series IS NOT NULL
        GROUP BY series
        ORDER BY total_royalties DESC
    """, conn)

    fig, ax = plt.subplots(figsize=(10, 5))

    colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#3B1F2B', '#8AC926']
    bars = ax.barh(df['series'], df['total_royalties'], color=colors[:len(df)])

    for bar in bars:
        width = bar.get_width()
        ax.text(width + 2, bar.get_y() + bar.get_height() / 2,
                f'${width:,.2f}', ha='left', va='center', fontsize=10)

    ax.set_xlabel('Total Royalties ($)', fontsize=12)
    ax.set_title('Royalty Revenue by Book Series', fontsize=14, fontweight='bold', pad=15)
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter('$%d'))

    plt.tight_layout()
    output = OUTPUT_DIR / "series_performance.png"
    plt.savefig(output, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output}")


def chart_regional_distribution(conn):
    """Pie chart: Revenue distribution by region."""
    df = pd.read_sql_query("""
        SELECT
            region,
            -- CHANGED: royalty_amount → royalty_amount_usd
            ROUND(SUM(royalty_amount_usd), 2) AS total_royalties
        FROM sales_fact
        GROUP BY region
        ORDER BY total_royalties DESC
    """, conn)

    total = df['total_royalties'].sum()

    fig, ax = plt.subplots(figsize=(10, 7))

    colors = ['#2E86AB', '#E63946', '#F18F01', '#8AC926', '#6A4C93', '#1982C4']

    wedges, _ = ax.pie(
        df['total_royalties'],
        labels=None,
        colors=colors[:len(df)],
        startangle=90,
        wedgeprops={'edgecolor': 'white', 'linewidth': 1.5}
    )

    legend_labels = [
        f'{row.region} — ${row.total_royalties:,.2f} ({row.total_royalties/total*100:.1f}%)'
        for row in df.itertuples()
    ]
    ax.legend(
        wedges,
        legend_labels,
        title='Regions',
        loc='center left',
        bbox_to_anchor=(1, 0.5),
        fontsize=10
    )

    ax.set_title('Revenue Distribution by Region', fontsize=14, fontweight='bold', pad=20)

    plt.tight_layout()
    output = OUTPUT_DIR / "regional_distribution.png"
    plt.savefig(output, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output}")


def chart_top_titles(conn):
    """Horizontal bar chart: Top performing titles by revenue."""
    df = pd.read_sql_query("""
        SELECT
            canonical_work_slug,
            -- CHANGED: royalty_amount → royalty_amount_usd
            ROUND(SUM(royalty_amount_usd), 2) AS total_royalties,
            SUM(quantity) AS total_units_sold
        FROM sales_fact
        GROUP BY canonical_work_slug
        -- CHANGED: ORDER BY royalty_amount → royalty_amount_usd
        ORDER BY SUM(royalty_amount_usd) DESC
        LIMIT 10
    """, conn)

    # Shorten slugs for display
    df['short_name'] = df['canonical_work_slug'].str.replace('_', ' ').str.title().str[:25]

    fig, ax = plt.subplots(figsize=(12, 6))

    bars = ax.barh(df['short_name'][::-1], df['total_royalties'][::-1], color='#2E86AB')

    for i, (bar, units) in enumerate(zip(bars, df['total_units_sold'][::-1])):
        width = bar.get_width()
        ax.text(width + 1, bar.get_y() + bar.get_height() / 2,
                f'${width:,.2f} ({units} units)', ha='left', va='center', fontsize=9)

    ax.set_xlabel('Total Royalties ($)', fontsize=12)
    ax.set_title('Top 10 Titles by Royalty Revenue', fontsize=14, fontweight='bold', pad=15)
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter('$%d'))

    plt.tight_layout()
    output = OUTPUT_DIR / "top_titles.png"
    plt.savefig(output, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output}")


def chart_platform_comparison(conn):
    """Stacked bar chart: Monthly revenue by source platform."""
    df = pd.read_sql_query("""
        SELECT
            strftime('%Y-%m', sale_date) AS period,
            source_platform,
            -- CHANGED: royalty_amount → royalty_amount_usd
            ROUND(SUM(royalty_amount_usd), 2) AS total_revenue
        FROM sales_fact
        -- CHANGED: WHERE clause uses royalty_amount_usd
        WHERE royalty_amount_usd IS NOT NULL AND royalty_amount_usd > 0
        GROUP BY strftime('%Y-%m', sale_date), source_platform
        ORDER BY period ASC, source_platform ASC
    """, conn)

    pivot_df = df.pivot(index='period', columns='source_platform', values='total_revenue').fillna(0)

    fig, ax = plt.subplots(figsize=(16, 7))
    pivot_df.plot(kind='bar', stacked=True, colormap='Set2', ax=ax, width=0.8)

    ax.set_title('Monthly Revenue by Source Platform', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Reporting Period', fontsize=11)
    ax.set_ylabel('Revenue ($)', fontsize=12)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('$%d'))
    
    # FIX: Better x-axis handling for overcrowded labels
    # Limit to ~10 major ticks and use cleaner angle/formatting
    num_periods = len(pivot_df.index)
    ax.xaxis.set_major_locator(plt.MaxNLocator(nbins=min(10, max(num_periods // 3, 6))))
    plt.xticks(rotation=45, ha='right')
    
    # Optional: Tighten legend positioning
    box = ax.get_position()
    ax.set_position([box.x0, box.y0, box.width * 0.9, box.height])
    ax.legend(title='Platform', bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=10)

    plt.tight_layout(rect=[0, 0, 1 - (num_periods / 300), 1])  # Add right padding for rotated labels
    output = OUTPUT_DIR / "platform_comparison.png"
    plt.savefig(output, bbox_inches='tight', dpi=150)
    plt.close()
    print(f"  Saved: {output}")


def chart_format_breakdown(conn):
    """Two-panel chart: revenue share (pie) and units sold (bar) by format."""
    df = pd.read_sql_query("""
        SELECT
            edition_format AS format_category,
            -- CHANGED: royalty_amount → royalty_amount_usd
            ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
            SUM(quantity) AS units_sold
        FROM sales_fact
        -- CHANGED: WHERE clause uses royalty_amount_usd
        WHERE royalty_amount_usd IS NOT NULL AND royalty_amount_usd > 0
          AND edition_format IS NOT NULL AND edition_format != ''
        GROUP BY edition_format
        ORDER BY total_revenue DESC
    """, conn)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    colors = plt.cm.Set2(np.linspace(0, 1, len(df)))

    # Left: Pie chart of revenue share
    wedges, texts, autotexts = ax1.pie(
        df['total_revenue'],
        labels=df['format_category'],
        autopct='%1.1f%%',
        colors=colors,
        startangle=90,
        wedgeprops={'edgecolor': 'white', 'linewidth': 1.5}
    )
    for autotext in autotexts:
        autotext.set_fontsize(10)
    ax1.set_title('Revenue Share by Format', fontsize=12, fontweight='bold', pad=15)

    # Right: Bar chart of units sold
    ax2.barh(df['format_category'][::-1], df['units_sold'][::-1], color=colors[::-1])
    ax2.set_xlabel('Units Sold', fontsize=11)
    ax2.set_title('Units Sold by Format', fontsize=12, fontweight='bold', pad=15)

    plt.suptitle('Book Format Performance Overview', fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    output = OUTPUT_DIR / "format_breakdown.png"
    plt.savefig(output, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output}")


def chart_marketplace_ranking(conn):
    """Three-panel chart: top markets by revenue, volume, and avg transaction value."""
    df = pd.read_sql_query("""
        SELECT
            region,
            COUNT(*) AS transaction_count,
            -- CHANGED: royalty_amount → royalty_amount_usd
            ROUND(SUM(royalty_amount_usd), 2) AS total_revenue,
            SUM(quantity) AS units_sold
        FROM sales_fact
        -- CHANGED: WHERE clause uses royalty_amount_usd
        WHERE royalty_amount_usd IS NOT NULL AND royalty_amount_usd > 0
          AND region IS NOT NULL AND region != ''
        GROUP BY region
        HAVING COUNT(*) >= 5
        ORDER BY total_revenue DESC
        LIMIT 10
    """, conn)

    fig, axes = plt.subplots(1, 3, figsize=(16, 6))

    # Panel 1: Revenue by region
    ax = axes[0]
    ax.barh(df['region'][::-1], df['total_revenue'][::-1], color='#2E86AB')
    ax.set_xlabel('Revenue ($)', fontsize=10)
    ax.set_title('Top Markets by Revenue', fontsize=12, fontweight='bold')
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter('$%d'))
    ax.tick_params(axis='x', labelsize=9)
    ax.tick_params(axis='y', labelsize=9)

    # Panel 2: Transaction volume
    ax = axes[1]
    ax.barh(df['region'][::-1], df['transaction_count'][::-1], color='#A23B72')
    ax.set_xlabel('Transactions', fontsize=10)
    ax.set_title('Volume by Region', fontsize=12, fontweight='bold')
    ax.tick_params(axis='x', labelsize=9)
    ax.tick_params(axis='y', labelsize=9)

    # Panel 3: Average transaction value
    avg_value = df['total_revenue'] / df['transaction_count']
    ax = axes[2]
    ax.barh(df['region'][::-1], avg_value[::-1], color='#F18F01')
    ax.set_xlabel('Avg Transaction Value ($)', fontsize=10)
    ax.set_title('Per-Transaction Value', fontsize=12, fontweight='bold')
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter('$%d'))
    ax.tick_params(axis='x', labelsize=9)
    ax.tick_params(axis='y', labelsize=9)

    plt.suptitle('Global Market Performance Breakdown', fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    output = OUTPUT_DIR / "marketplace_ranking.png"
    plt.savefig(output, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output}")


def generate_all_charts():
    """Generate all visualization charts from the database."""
    print("=" * 60)
    print("GENERATING VISUALIZATIONS")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    print(f"[INFO] Connected to database: {DB_PATH}")

    print("\nGenerating charts:")

    chart_monthly_revenue(conn)
    chart_series_performance(conn)
    chart_regional_distribution(conn)
    chart_top_titles(conn)
    chart_platform_comparison(conn)
    chart_format_breakdown(conn)
    chart_marketplace_ranking(conn)

    conn.close()

    print(f"\n[DONE] All 7 charts saved to {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    generate_all_charts()