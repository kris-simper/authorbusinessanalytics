"""
KENP (Kindle Edition Normalized Pages) loader for Amazon KDP.

Derives per-page royalty rates via backward calculation from KDP summary data:
    1. KENP royalty (native currency) = Summary.Royalty - CombinedSales.Royalty
    2. Effective rate = KENP royalty / total pages read
    3. Per-book royalty = page_count × rate_per_page

Each row represents one book-marketplace-date page-read aggregation (daily granularity).
Uses ASIN as primary identifier for catalog enrichment. Converts native-currency
royalties to USD using historical ECB reference rates (to_usd()).

Quirks handled:
- Three-tab Excel workbook (KENP, Summary, Combined Sales)
- Mixed date formats (ISO dates, "Month YYYY", "YYYY-MM")
- Marketplace-to-currency mapping across 13 regions
- Fallback title-matching for unmatched ASINs

Grain: One row per book-marketplace-date page-read record.
Kimball compliance: Separate fact table due to different measurement grain
(page reads vs sales transactions) and distinct analytical metrics.
"""

from pathlib import Path

import pandas as pd

from src.schemas import KDP_MARKETPLACE_MAP
from src.currency import to_usd


# ===================================================================
# CURRENCY AND MARKETPLACE MAPPING CONSTANTS
# ===================================================================

MARKETPLACE_CURRENCY_MAP = {
    "Amazon.com": "USD",
    "Amazon.co.uk": "GBP",
    "Amazon.de": "EUR",
    "Amazon.fr": "EUR",
    "Amazon.es": "EUR",
    "Amazon.it": "EUR",
    "Amazon.co.jp": "JPY",
    "Amazon.ca": "CAD",
    "Amazon.com.au": "AUD",
    "Amazon.in": "INR",
    "Amazon.com.br": "BRL",
    "Amazon.com.mx": "MXN",
    "Amazon.nl": "EUR",
    "Amazon.pl": "PLN",
    "Amazon.se": "SEK",
}

SUMMARY_CURRENCY_COLS = {
    "Royalty (USD)": "USD",
    "Royalty (GBP)": "GBP",
    "Royalty (EUR)": "EUR",
    "Royalty (JPY)": "JPY",
    "Royalty (CAD)": "CAD",
    "Royalty (INR)": "INR",
    "Royalty (PLN)": "PLN",
    "Royalty (SEK)": "SEK",
    "Royalty (BRL)": "BRL",
    "Royalty (MXN)": "MXN",
    "Royalty (AUD)": "AUD",
}


# ===================================================================
# MAIN LOADER FUNCTION
# ===================================================================

def load_kenp_data(filepath: str | Path, catalog=None) -> pd.DataFrame:
    """
    Load KENP page reads and derive royalties via backward calculation.

    Parses KDP's three-tab Excel workbook structure to calculate implied
    per-page royalty rates, then allocates those rates to individual book-
    day page read records. Falls back to title-matching for ASIN lookups
    that fail initial catalog resolution.

    Args:
        filepath: Path to the KDP .xlsx file containing KENP tab, Summary tab,
                  and Combined Sales tab
        catalog: BookCatalog instance for ASIN-based hybrid enrichment

    Returns:
        DataFrame with KENP reads, derived royalties, equivalent copies,
        and catalog metadata. Column mapping aligns with kenp_reads schema.
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading KENP data from {filepath.name}")

    # ==========================================================================
    # STEP 1: Load all three tabs from the KDP workbook
    # ==========================================================================

    df_kenp = pd.read_excel(filepath, sheet_name="KENP", engine="openpyxl")
    print(f"[INFO] KENP tab: {len(df_kenp)} page-read records")

    df_summary = pd.read_excel(filepath, sheet_name="Summary", engine="openpyxl")
    print(f"[INFO] Summary tab: {len(df_summary)} monthly rows")

    df_cs = pd.read_excel(filepath, sheet_name="Combined Sales", engine="openpyxl")
    print(f"[INFO] Combined Sales tab: {len(df_cs)} transaction rows")

    # ==========================================================================
    # STEP 2: Normalize dates and currencies
    # ==========================================================================

    # KENP tab uses ISO dates (YYYY-MM-DD)
    df_kenp["sale_date"] = pd.to_datetime(df_kenp["Date"])

    # Summary tab uses "Month YYYY" format
    df_summary["sale_date"] = pd.to_datetime(df_summary["Date"], format="%B %Y")

    # Combined Sales uses "YYYY-MM" format
    df_cs["sale_date"] = pd.to_datetime(df_cs["Royalty Date"], format="%Y-%m")

    # Map marketplace → currency on the KENP tab
    df_kenp["currency"] = df_kenp["Marketplace"].map(MARKETPLACE_CURRENCY_MAP)
    unmapped = df_kenp[df_kenp["currency"].isna()]["Marketplace"].unique()
    if len(unmapped) > 0:
        print(f"[WARN] Unmapped marketplaces in KENP tab: {unmapped}")

    # Map marketplace → region code (reuse existing schema)
    df_kenp["region"] = df_kenp["Marketplace"].map(KDP_MARKETPLACE_MAP)

    # ==========================================================================
    # STEP 3: Calculate KENP royalty residual per month + currency
    # ==========================================================================
    # Formula: residual = Summary.Royalty(currency, month) - CombinedSales.sum(currency, month)

    cs_by_month_currency = df_cs.groupby(["sale_date", "Currency"])["Royalty"].sum()

    residuals = []

    for _, summary_row in df_summary.iterrows():
        month = summary_row["sale_date"]

        for col, currency in SUMMARY_CURRENCY_COLS.items():
            summary_total = summary_row[col]
            if pd.isna(summary_total) or summary_total == 0:
                cs_val = cs_by_month_currency.get((month, currency), 0)
                if cs_val > 0:
                    residuals.append({
                        "sale_date": month,
                        "currency": currency,
                        "residual_royalty": -cs_val,
                    })
                continue

            cs_val = cs_by_month_currency.get((month, currency), 0)
            residual = summary_total - cs_val
            residuals.append({
                "sale_date": month,
                "currency": currency,
                "residual_royalty": round(residual, 2),
            })

    df_residuals = pd.DataFrame(residuals)
    print(f"[INFO] Calculated {len(df_residuals)} month/currency residuals")

    # ==========================================================================
    # STEP 4: Calculate effective per-page rate per month + currency
    # ==========================================================================
    # Formula: rate_per_page = residual_royalty / total_pages_read

    pages_by_month_currency = df_kenp.groupby(["sale_date", "currency"])["KENP"].sum()

    df_rates = df_residuals.merge(
        pages_by_month_currency.reset_index(),
        on=["sale_date", "currency"],
        how="left",
    )
    df_rates = df_rates.rename(columns={"KENP": "total_pages"})

    # Handle division by zero gracefully
    df_rates["rate_per_page"] = df_rates.apply(
        lambda r: r["residual_royalty"] / r["total_pages"]
        if r["total_pages"] and r["total_pages"] > 0
        else None,
        axis=1,
    )

    df_rates = df_rates.dropna(subset=["rate_per_page"])

    print(f"[INFO] Derived {len(df_rates)} effective rates "
          f"({df_rates['currency'].nunique()} currencies)")

    # Log sample rates for transparency
    print("[INFO] Sample effective rates (USD):")
    usd_rates = df_rates[df_rates["currency"] == "USD"].tail(5)
    if not usd_rates.empty:
        for _, r in usd_rates.iterrows():
            print(f"  {r['sale_date'].strftime('%Y-%m')}: "
                  f"${r['rate_per_page']:.6f}/page "
                  f"({r['total_pages']:,.0f} pages → ${r['residual_royalty']:.2f})")

    # ==========================================================================
    # STEP 5: Allocate royalty to individual KENP rows
    # ==========================================================================

    # Merge rate_per_page onto per-book KENP data
    df_kenp = df_kenp.merge(
        df_rates[["sale_date", "currency", "rate_per_page"]],
        on=["sale_date", "currency"],
        how="left",
    )

    # Calculate royalty in native currency using the per-page rate
    df_kenp["royalty_amount"] = (
        df_kenp["KENP"] * df_kenp["rate_per_page"]
    ).round(2)

    # Rename KENP column to page_count for clarity
    df_kenp = df_kenp.rename(columns={"KENP": "page_count"})

    # ==========================================================================
    # STEP 6: Convert to USD using existing currency infrastructure
    # ==========================================================================

    print("[INFO] Converting KENP royalties to USD...")
    df_kenp["royalty_amount_usd"] = df_kenp.apply(
        lambda r: to_usd(r["royalty_amount"], r["currency"], r["sale_date"]),
        axis=1,
    )

    converted = df_kenp["royalty_amount_usd"].notna().sum()
    print(f"[INFO] {converted}/{len(df_kenp)} KENP records converted to USD")

    # ==========================================================================
    # STEP 7: Catalog enrichment (series, work slug, format, KENP page count)
    # ==========================================================================

    if catalog is not None:
        print("[INFO] Enriching KENP reads with catalog metadata...")
        df_kenp = df_kenp.rename(columns={"eBook ASIN": "book_identifier"})

        # Run standard enrichment via ASIN
        df_kenp = catalog.enrich(df_kenp, "book_identifier")

        # Stage 2 fallback for any unmatched (rare edge cases)
        unmatched_mask = df_kenp["series"].isna()
        if unmatched_mask.any():
            from src.matching import _match_titles_to_catalog

            unmatched_rows = df_kenp[unmatched_mask].copy()

            # Drop enrichment columns so title matching can recreate them fresh
            for col in ["series", "canonical_work_slug", "edition_format"]:
                if col in unmatched_rows.columns:
                    unmatched_rows = unmatched_rows.drop(columns=[col])

            title_matched = _match_titles_to_catalog(unmatched_rows, catalog)
            matched_rows = df_kenp[~unmatched_mask]
            df_kenp = pd.concat([matched_rows, title_matched], ignore_index=True)

        matched = df_kenp["series"].notna().sum()
        print(f"[INFO] Catalog enrichment: {matched}/{len(df_kenp)} rows matched")
    else:
        df_kenp["series"] = None
        df_kenp["canonical_work_slug"] = None
        # Do NOT set edition_format to None here — defaults to 'ebook' in Step 8

    # ==========================================================================
    # STEP 8: Finalize output columns and handle defaults
    # ==========================================================================

    df_kenp["source_platform"] = "amazon_kdp_ku"
    df_kenp["edition_format"] = df_kenp.get("edition_format", pd.Series(dtype=str)).fillna("ebook")

    # Ensure KENP page count exists (may come from catalog or original data)
    # Default to 1 to avoid division by zero when calculating equivalent_copies
    df_kenp["kenp_page_count"] = df_kenp.get("kenp_page_count", pd.Series(dtype=float)).fillna(1).astype(int)

    # Calculate approximate copies read (pages / book's KENP page count)
    df_kenp["equivalent_copies"] = (
        df_kenp["page_count"] / df_kenp["kenp_page_count"]
    ).round(2)

    # Select final columns matching kenp_reads schema
    final_columns = [
        "sale_date",
        "source_platform",
        "book_identifier",
        "canonical_work_slug",
        "series",
        "edition_format",
        "marketplace",
        "region",
        "currency",
        "page_count",
        "rate_per_page",
        "royalty_amount",
        "royalty_amount_usd",
        "kenp_page_count",
        "equivalent_copies",
    ]

    df_result = df_kenp[[c for c in final_columns if c in df_kenp.columns]].copy()

    print(f"[INFO] KENP load complete: {len(df_result)} normalized records")

    if not df_result.empty:
        print(f"[INFO] Date range: {df_result['sale_date'].min()} to {df_result['sale_date'].max()}")
        print(f"[INFO] Unique currencies: {df_result['currency'].nunique()}")
        total_royalty = df_result['royalty_amount_usd'].sum()
        print(f"[INFO] Total royalty (USD): ${total_royalty:.2f}")

    return df_result