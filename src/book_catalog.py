"""
Book catalog management for cross-platform identifier matching.
Transforms the human-friendly wide CSV into a machine-friendly long format
for merging against any incoming sales data identifier.
"""

import pandas as pd
from pathlib import Path


class BookCatalog:
    """Loads and prepares the product catalog for data enrichment."""
    
    def __init__(self, catalog_path=None):
        if catalog_path is None:
            catalog_path = Path(__file__).parent.parent / 'data' / 'catalog_products.csv'
        self.catalog_path = Path(catalog_path)
        self.raw_catalog = None      # Original wide format (human readable)
        self.match_table = None      # Unpivoted long format (machine readable)
        
    def load(self):
        """Load the catalog CSV and build the internal matching table."""
        if not self.catalog_path.exists():
            print(f"[WARN] Catalog file not found at {self.catalog_path}")
            print("[WARN] Skipping catalog enrichment. Data will use raw IDs.")
            return False
            
        # Try UTF-8 first, fall back to Windows encoding if needed
        try:
            self.raw_catalog = pd.read_csv(self.catalog_path, encoding='utf-8')
        except UnicodeDecodeError:
            print("[WARN] UTF-8 failed, falling back to cp1252 (Windows encoding)")
            self.raw_catalog = pd.read_csv(self.catalog_path, encoding='cp1252')
        
        # Build the long-format match table by unpivoting identifier columns
        id_columns = ['asin', 'isbn_10', 'isbn_13', 'other_id']
        match_frames = []
        
        for col in id_columns:
            if col in self.raw_catalog.columns:
                subset = self.raw_catalog[
                    ['series', 'canonical_work_slug', 'display_title', 'edition_format', col]
                ].dropna(subset=[col])
                
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
    
    def enrich(self, df, id_column, id_type_hint=None):
        """
        Merge catalog info (series, work slug, format) onto sales data.
        
        Args:
            df: Sales DataFrame with a column containing book identifiers
            id_column: Name of the column in df containing the identifiers
            id_type_hint: Optional hint about what type of ID it is ('asin', 'isbn_13', etc.)
                          If None, tries to match against all identifier types
        
        Returns:
            DataFrame with added columns: series, canonical_work_slug, edition_format
        """
        if self.match_table is None:
            # No catalog loaded — add empty columns as graceful fallback
            df['series'] = None
            df['canonical_work_slug'] = df[id_column]
            df['edition_format'] = None
            return df
        
        # Normalize the incoming IDs for matching (strip whitespace, uppercase ASINs)
        df = df.copy()
        df['_match_key'] = df[id_column].astype(str).str.strip()
        
        # ASINs are uppercase alphanumeric, normalize them
        if id_type_hint == 'asin' or (df['_match_key'].str.startswith('B0').any()):
            df['_match_key'] = df['_match_key'].str.upper()
            match_table = self.match_table.copy()
            match_table['match_identifier'] = match_table['match_identifier'].astype(str).str.strip().str.upper()
        else:
            match_table = self.match_table.copy()
            match_table['match_identifier'] = match_table['match_identifier'].astype(str).str.strip()
        
        # Perform left join — keeps all sales rows even if no catalog match
        enriched = df.merge(
            match_table[['match_identifier', 'series', 'canonical_work_slug', 'edition_format']],
            left_on='_match_key',
            right_on='match_identifier',
            how='left'
        )
        
        # Clean up temporary columns
        enriched = enriched.drop(columns=['_match_key', 'match_identifier'])
        
        # Fallback: unmatched rows get the raw ID as their work slug
        enriched['canonical_work_slug'] = enriched['canonical_work_slug'].fillna(df[id_column])
        
        # Count matches for logging
        matched = enriched['series'].notna().sum()
        total = len(enriched)
        print(f"[INFO] Catalog enrichment: {matched}/{total} rows matched to catalog")
        
        return enriched