"""
KENP (Kindle Edition Normalized Pages) loader for Amazon KDP.

Derives per-page royalty rates via backward calculation:
    1. KENP royalty (currency, month) = Summary total - Combined Sales total
    2. Effective rate = KENP royalty / total pages read
    3. Per-book royalty = page_count × effective rate
    
Converts native-currency royalties to USD using historical ECB reference rates.
Calculates equivalent copies sold via KU for apples-to-apples comparison vs direct sales.
"""

import pandas as pd
from pathlib import Path
from src.schemas import KDP_MARKETPLACE_MAP
from src.currency import to_usd


# Map marketplaces to the currency used in the Summary tab
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

# Summary tab column → ISO currency code mapping
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


def load_kenp_data(filepath, catalog=None):
    """
    Load KENP page reads and derive royalties via backward calculation.

    Args:
        filepath: Path to the KDP .xlsx file
        catalog: BookCatalog instance for enrichment

    Returns:
        DataFrame with KENP reads, derived royalties, and equivalent copies
    """
    filepath = Path(filepath)
    print(f"[INFO] Loading KENP data from {filepath.name}")

    # =======================================================================
    # STEP 1: Load all three tabs from the KDP workbook
    # =======================================================================

    df_kenp = pd.read_excel(filepath, sheet_name="KENP", engine="openpyxl")
    print(f"[INFO] KENP tab: {len(df_kenp)} page-read records")

    df_summary = pd.read_excel(filepath, sheet_name="Summary", engine="openpyxl")
    print(f"[INFO] Summary tab: {len(df_summary)} monthly rows")

    df_cs = pd.read_excel(filepath, sheet_name="Combined Sales", engine="openpyxl")
    print(f"[INFO] Combined Sales tab: {len(df_cs)} transaction rows")

    # =======================================================================
    # STEP 2: Normalize dates and currencies
    # =======================================================================

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

    # =======================================================================
    # STEP 3: Calculate KENP royalty residual per month + currency
    # =======================================================================
    # Formula: residual = Summary.Royalty(currency, month) - CombinedSales.sum(currency, month)

    cs_by_month_currency = df_cs.groupby(["sale_date", "Currency"])["Royalty"].sum()

    # Build a residual lookup: (sale_date, currency) → residual_royalty
    residuals = []

    for _, summary_row in df_summary.iterrows():
        month = summary_row["sale_date"]

        for col, currency in SUMMARY_CURRENCY_COLS.items():
            summary_total = summary_row[col]
            if pd.isna(summary_total) or summary_total == 0:
                # Check CS side — if CS has sales but Summary shows zero, this indicates data issue
                cs_val = cs_by_month_currency.get((month, currency), 0)
                if cs_val > 0:
                    residuals.append({
                        "sale_date": month,
                        "currency": currency,
                        "residual_royalty": -cs_val,  # negative = data inconsistency
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

    # =======================================================================
    # STEP 4: Calculate effective per-page rate per month + currency
    # =======================================================================
    # Formula: effective_rate = residual_royalty / total_pages_read

    # Sum KENP pages by month + currency
    pages_by_month_currency = df_kenp.groupby(["sale_date", "currency"])["KENP"].sum()

    # Merge residuals with page counts
    df_rates = df_residuals.merge(
        pages_by_month_currency.reset_index(),
        on=["sale_date", "currency"],
        how="left",
    )
    df_rates = df_rates.rename(columns={"KENP": "total_pages"})

    # Calculate effective rate (handle division by zero gracefully)
    df_rates["effective_rate"] = df_rates.apply(
        lambda r: r["residual_royalty"] / r["total_pages"]
        if r["total_pages"] and r["total_pages"] > 0
        else None,
        axis=1,
    )

    # Drop rows with no pages (nothing to allocate)
    df_rates = df_rates.dropna(subset=["effective_rate"])

    print(f"[INFO] Derived {len(df_rates)} effective rates "
          f"({df_rates['currency'].nunique()} currencies)")

    # Log sample rates for transparency
    print("[INFO] Sample effective rates (USD):")
    usd_rates = df_rates[df_rates["currency"] == "USD"].tail(5)
    for _, r in usd_rates.iterrows():
        print(f"  {r['sale_date'].strftime('%Y-%m')}: "
              f"${r['effective_rate']:.6f}/page "
              f"({r['total_pages']:,.0f} pages → ${r['residual_royalty']:.2f})")

    # =======================================================================
    # STEP 5: Allocate royalty to individual KENP rows
    # =======================================================================

    # Merge effective rates onto the per-book KENP data
    df_kenp = df_kenp.merge(
        df_rates[["sale_date", "currency", "effective_rate"]],
        on=["sale_date", "currency"],
        how="left",
    )

    # Calculate royalty in native currency
    df_kenp["royalty_amount"] = (
        df_kenp["KENP"] * df_kenp["effective_rate"]
    ).round(2)

    # Rename KENP column to page_count for clarity
    df_kenp = df_kenp.rename(columns={"KENP": "page_count"})

    # =======================================================================
    # STEP 6: Convert to USD using existing currency infrastructure
    # =======================================================================

    print("[INFO] Converting KENP royalties to USD...")
    df_kenp["royalty_amount_usd"] = df_kenp.apply(
        lambda r: to_usd(r["royalty_amount"], r["currency"], r["sale_date"]),
        axis=1,
    )

    converted = df_kenp["royalty_amount_usd"].notna().sum()
    print(f"[INFO] {converted}/{len(df_kenp)} KENP records converted to USD")

    # =======================================================================
    # STEP 7: Catalog enrichment (series, work slug, format, KENP page count)
    # =======================================================================

    if catalog is not None:
        print("[INFO] Enriching KENP reads with catalog metadata...")
        df_kenp = df_kenp.rename(columns={"eBook ASIN": "book_identifier"})

        # Run the same hybrid enrichment as the sales loaders
        df_enriched = catalog.enrich(df_kenp, "book_identifier")

        # Stage 2 fallback for any unmatched (rare edge cases)
        unmatched_mask = df_enriched["series"].isna()
        if unmatched_mask.any():
            from src.loaders import _match_titles_to_catalog
            unmatched_rows = df_enriched[unmatched_mask].copy()
            for col in ["series", "canonical_work_slug", "edition_format"]:
                if col in unmatched_rows.columns:
                    unmatched_rows = unmatched_rows.drop(columns=[col])
            title_matched = _match_titles_to_catalog(unmatched_rows, catalog)
            matched_rows = df_enriched[~unmatched_mask]
            df_enriched = pd.concat([matched_rows, title_matched], ignore_index=True)

        df_kenp = df_enriched
        matched = df_kenp["series"].notna().sum()
        print(f"[INFO] Catalog enrichment: {matched}/{len(df_kenp)} rows matched")
    else:
        df_kenp["series"] = None
        df_kenp["canonical_work_slug"] = None
        df_kenp["edition_format"] = None

    # =======================================================================
    # STEP 8: Calculate equivalent copies and finalize output
    # =======================================================================

    df_kenp["source_platform"] = "amazon_kdp_ku"
    df_kenp["edition_format"] = df_kenp["edition_format"].fillna("ebook")

    # Handle KENP page count: default to 1 to avoid division by zero
    df_kenp["kenp_page_count"] = df_kenp["kenp_page_count"].fillna(1).astype(int)
    
    # Calculate approximate copies read (pages / book's KENP page count)
    df_kenp["equivalent_copies"] = (
        df_kenp["page_count"] / df_kenp["kenp_page_count"]
    ).round(2)

    # Select and rename columns to match kenp_reads schema
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
    return df_result