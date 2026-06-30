"""
Book catalog management for cross-platform identifier matching.

Provides a centralized BookCatalog class that manages the master list of
published editions and their canonical identifiers (ASIN, ISBN-13, ISBN-10,
other_id), enabling hybrid enrichment strategies across all sales platforms.

Transformation Process:
1. Load human-friendly wide-format CSV (one row per edition, multiple ID columns)
2. Unpivot into machine-friendly long-format match_table (one row per ID)
3. Perform left merge during enrichment, matching on normalized identifiers
4. Fall back to title-based fuzzy matching when IDs fail

Kimball Compliance:
Dim_books serves as a conformed dimension table shared across all 10 fact
tables. All enrichment pipelines normalize foreign keys through this single
catalog source to ensure consistent series/work slugs regardless of platform.

Grain: One row per unique book edition in the catalog (distinct from transaction
fact tables which may contain thousands of records per edition over time).
"""

from pathlib import Path

import pandas as pd


# ===================================================================
# HELPER FUNCTIONS
# ===================================================================

def _normalize_identifier(val) -> str | None:
    """
    Normalize an identifier string for robust matching.

    Applies sequential transformations to eliminate common data quality issues:
        1. Return None for NaN/null inputs
        2. Convert to string and strip whitespace
        3. Remove leading apostrophe characters (Excel artifact)
        4. Remove hyphens from ISBN formats (ISBN-10 vs ISBN-13 presentation)
        5. Remove trailing ".0" suffix from numeric coercion artifacts
        6. Upper-case letters for case-insensitive comparison

    Args:
        val: Raw identifier value (may be string, float, int, or NaN)

    Returns:
        Normalized uppercase identifier string without dashes/artifacts, or None
    """
    if pd.isna(val):
        return None

    s = str(val).strip()
    if s.startswith("'"):
        s = s[1:]
    s = s.replace('-', '')  # CRITICAL: Strip hyphens from ISBNs
    if s.endswith('.0') and len(s) > 1 and s[:-2].isdigit():
        s = s[:-2]
    return s.upper()


# ===================================================================
# CATALOG CLASS
# ===================================================================

class BookCatalog:
    """Loads and prepares the book catalog for data enrichment."""

    def __init__(self, catalog_path: str | Path = None) -> None:
        """
        Initialize BookCatalog with path to catalog CSV file.

        Sets default path to project-relative location unless overridden.
        Does NOT load data until explicit .load() call.

        Args:
            catalog_path: Optional override for catalog file location. Defaults
                         to '../data/catalog_products.csv' relative to this file
        """
        if catalog_path is None:
            catalog_path = Path(__file__).parent.parent / 'data' / 'catalog_products.csv'
        self.catalog_path = Path(catalog_path)
        self.raw_catalog = None     # Original wide format (human readable)
        self.match_table = None     # Unpivoted long format (machine readable)

    def load(self) -> bool:
        """
        Load the catalog CSV and build the internal matching table.

        Transforms wide-format catalog (multiple ID columns per edition) into
        long-format match_table where each identifier gets its own row. Enables
        flexible merging regardless of which identifier type arrives in sales data.

        Returns:
            True if catalog loaded successfully, False if file missing or invalid
        """
        if not self.catalog_path.exists():
            print(f"[WARN] Catalog file not found at {self.catalog_path}")
            print("[WARN] Skipping catalog enrichment. Data will use raw IDs.")
            return False

        try:
            self.raw_catalog = pd.read_csv(
                self.catalog_path, encoding='utf-8', dtype=str
            )
        except UnicodeDecodeError:
            print("[WARN] UTF-8 failed, falling back to cp1252 (Windows encoding)")
            self.raw_catalog = pd.read_csv(
                self.catalog_path, encoding='cp1252', dtype=str
            )

        id_columns = ['asin', 'isbn_10', 'isbn_13', 'other_id']
        match_frames = []

        for col in id_columns:
            if col in self.raw_catalog.columns:
                cols_to_select = [
                    c for c in 
                    ['series', 'canonical_work_slug', 'display_title',
                     'edition_format', 'kenp_page_count', col] 
                    if c in self.raw_catalog.columns
                ]

                subset = self.raw_catalog[cols_to_select].dropna(subset=[col])
                subset = subset.rename(columns={col: 'match_identifier'})
                subset['id_type'] = col
                match_frames.append(subset)

        if match_frames:
            self.match_table = pd.concat(match_frames, ignore_index=True)
            print(f"[INFO] Catalog loaded: {len(self.raw_catalog)} editions, "
                  f"{len(self.match_table)} total identifiers indexed")
            return True
        else:
            print("[WARN] No valid identifier columns found in catalog")
            return False

    def enrich(self, df: pd.DataFrame, id_column: str, id_type_hint=None) -> pd.DataFrame:
        """
        Merge catalog info onto sales data using identifier matching.

        Performs left join between sales DataFrame and unpivoted match_table
        to attach series name, work slug, and edition format to each transaction.
        Uses pre-normalized identifier matching to handle formatting inconsistencies.

        Args:
            df: Sales DataFrame to enrich (modified copy returned)
            id_column: Name of identifier column in df (e.g., 'book_identifier')
            id_type_hint: Optional hint about expected ID type (currently unused)

        Returns:
            Copy of input df with additional catalog columns appended:
            series, canonical_work_slug, edition_format, kenp_page_count (if available)
            Unmatched rows receive NULL values for catalog fields
        """
        if self.match_table is None:
            print("[WARN] Catalog not loaded — returning dataframe without enrichment")
            df_copy = df.copy()
            df_copy['series'] = None
            df_copy['canonical_work_slug'] = df_copy[id_column]
            df_copy['edition_format'] = None
            return df_copy

        df_copy = df.copy()
        df_copy['_match_key'] = df_copy[id_column].apply(_normalize_identifier)

        match_table = self.match_table.copy()
        match_table['match_identifier'] = match_table['match_identifier'].apply(_normalize_identifier)

        # Determine which columns to carry through based on what exists
        base_cols = ['match_identifier', 'series', 'canonical_work_slug', 'edition_format']
        if 'kenp_page_count' in match_table.columns:
            base_cols.append('kenp_page_count')

        enriched = df_copy.merge(
            match_table[base_cols],
            left_on='_match_key',
            right_on='match_identifier',
            how='left'
        )

        enriched = enriched.drop(columns=['_match_key', 'match_identifier'])
        enriched['canonical_work_slug'] = enriched['canonical_work_slug'].fillna(df_copy[id_column])

        matched = enriched['series'].notna().sum()
        total = len(enriched)
        print(f"[INFO] Catalog enrichment: {matched}/{total} rows matched to catalog")

        return enriched