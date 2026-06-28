"""
Book catalog management for cross-platform identifier matching.
Transforms the human-friendly wide CSV into a machine-friendly long format
for merging against any incoming sales data identifier.
"""

import pandas as pd
from pathlib import Path


class BookCatalog:
    """Loads and prepares the book catalog for data enrichment."""
    
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
            
        try:
            self.raw_catalog = pd.read_csv(self.catalog_path, encoding='utf-8', dtype=str)
        except UnicodeDecodeError:
            print("[WARN] UTF-8 failed, falling back to cp1252 (Windows encoding)")
            self.raw_catalog = pd.read_csv(self.catalog_path, encoding='cp1252', dtype=str)
        
        id_columns = ['asin', 'isbn_10', 'isbn_13', 'other_id']
        match_frames = []
        
        for col in id_columns:
            if col in self.raw_catalog.columns:
                # Include kenp_page_count if it exists in the catalog
                extra_cols = []
                if 'kenp_page_count' in self.raw_catalog.columns:
                    extra_cols.append('kenp_page_count')
                
                cols_to_select = [c for c in 
                                  ['series', 'canonical_work_slug', 'display_title', 
                                   'edition_format', 'kenp_page_count', col] 
                                  if c in self.raw_catalog.columns]
                
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
    
    def enrich(self, df, id_column, id_type_hint=None):
        """Merge catalog info onto sales data using hybrid ID/title matching."""
        if self.match_table is None:
            df['series'] = None
            df['canonical_work_slug'] = df[id_column]
            df['edition_format'] = None
            return df
        
        def _normalize_id(val):
            """Normalize identifiers: strip whitespace, hyphens, .0 artifacts, apostrophes."""
            if pd.isna(val):
                return None
            s = str(val).strip()
            if s.startswith("'"):
                s = s[1:]
            s = s.replace('-', '')  # CRITICAL: Strip hyphens from ISBNs
            if s.endswith('.0') and len(s) > 1 and s[:-2].isdigit():
                s = s[:-2]
            return s.upper()
        
        df = df.copy()
        df['_match_key'] = df[id_column].apply(_normalize_id)
        
        match_table = self.match_table.copy()
        match_table['match_identifier'] = match_table['match_identifier'].apply(_normalize_id)
        
        # Determine which columns to carry through based on what exists
        base_cols = ['match_identifier', 'series', 'canonical_work_slug', 'edition_format']
        if 'kenp_page_count' in match_table.columns:
            base_cols.append('kenp_page_count')
        
        enriched = df.merge(
            match_table[base_cols],
            left_on='_match_key',
            right_on='match_identifier',
            how='left'
        )
        
        enriched = enriched.drop(columns=['_match_key', 'match_identifier'])
        enriched['canonical_work_slug'] = enriched['canonical_work_slug'].fillna(df[id_column])
        
        matched = enriched['series'].notna().sum()
        total = len(enriched)
        print(f"[INFO] Catalog enrichment: {matched}/{total} rows matched to catalog")
        
        return enriched