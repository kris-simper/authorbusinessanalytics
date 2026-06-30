"""
Shared catalog matching utilities for ETL pipeline enrichment.

Provides fuzzy title matching as a fallback when identifier-based
catalog enrichment (ISBN, ASIN, SKU) fails to resolve entries.
"""

import re

import pandas as pd
from difflib import SequenceMatcher


def _match_titles_to_catalog(
    df: pd.DataFrame,
    catalog=None,
    threshold: float = 0.75,
) -> pd.DataFrame:
    """
    Match catalog entries based on book title similarity.

    Fallback enrichment layer used when primary identifiers (ISBN, ASIN, SKU)
    fail to resolve. Uses Levenshtein-distance ratio comparison to find
    closest title matches across the catalog.

    Args:
        df: Sales DataFrame with 'book_title' column
        catalog: BookCatalog instance providing raw_catalog DataFrame
        threshold: Minimum similarity ratio (0-1) for accepting a match.
                   Lower thresholds increase false positives; higher thresholds
                   miss legitimate matches with formatting variations.

    Returns:
        Enriched DataFrame with series, canonical_work_slug, and edition_format
        columns filled where matches exceeded the similarity threshold.
        Unmatched rows receive NULL values for these columns.
    """
    if catalog is None or catalog.raw_catalog is None:
        df['series'] = None
        df['canonical_work_slug'] = None
        df['edition_format'] = None
        return df.copy()

    catalog_titles = catalog.raw_catalog['display_title'].tolist()
    catalog_info = catalog.raw_catalog[['series', 'canonical_work_slug', 'edition_format']]

    def find_best_match(title: str, candidates: list) -> tuple:
        """Find closest match from candidate titles using sequence ratio."""
        if pd.isna(title) or not isinstance(title, str):
            return None, 0.0

        title_lower = title.lower().strip()
        title_clean = re.sub(r'\s*:\s*.*$', '', title_lower)
        title_clean = re.sub(r'\s*\([^)]*\)', '', title_clean)
        title_clean = title_clean.replace('&', 'and').strip()

        best_score = 0.0
        best_match_idx = None

        for idx, candidate in enumerate(candidates):
            if pd.isna(candidate) or not isinstance(candidate, str):
                continue

            cand_lower = candidate.lower().strip()
            cand_clean = re.sub(r'\s*:\s*.*$', '', cand_lower)
            cand_clean = re.sub(r'\s*\([^)]*\)', '', cand_clean)
            cand_clean = cand_clean.replace('&', 'and').strip()

            score = SequenceMatcher(None, title_clean, cand_clean).ratio()

            if score > best_score:
                best_score = score
                best_match_idx = idx

        if best_score >= threshold:
            return best_match_idx, best_score
        return None, best_score

    df_copy = df.copy()
    df_copy['_match_result'] = df_copy['book_title'].apply(
        lambda t: find_best_match(t, catalog_titles)
    )

    def apply_single_match(row: pd.Series) -> pd.Series:
        idx, score = row['_match_result']
        if idx is not None:
            return pd.Series([
                catalog_info.loc[idx, 'series'],
                catalog_info.loc[idx, 'canonical_work_slug'],
                catalog_info.loc[idx, 'edition_format'],
            ])
        return pd.Series([None, None, None])

    matched_cols = df_copy.apply(apply_single_match, axis=1)
    df_copy[['series', 'canonical_work_slug', 'edition_format']] = matched_cols
    df_copy = df_copy.drop(columns=['_match_result'])

    return df_copy