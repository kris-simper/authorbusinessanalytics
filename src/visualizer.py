"""
Visualization module for author business analytics.
Generates publication-quality charts from SQLite database.
"""

import sqlite3
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

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
            ROUND(SUM(royalty_amount), 2) AS total_royalties
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

    ax1.set_title('Monthly Royalty Revenue & Units Sold (ACX)', fontsize=14, fontweight='bold', pad=15)
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
            ROUND(SUM(royalty_amount), 2) AS total_royalties
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
            ROUND(SUM(royalty_amount), 2) AS total_royalties
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
            ROUND(SUM(royalty_amount), 2) AS total_royalties,
            SUM(quantity) AS total_units_sold
        FROM sales_fact
        GROUP BY canonical_work_slug
        ORDER BY SUM(royalty_amount) DESC
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

    conn.close()

    print(f"\n[DONE] All charts saved to {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    generate_all_charts()