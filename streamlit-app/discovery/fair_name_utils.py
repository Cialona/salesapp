"""
Fair Name Matching Utilities

Provides robust fair name matching that handles short names (e.g., "IRE", "ISE", "CES")
without false positives from substring matching.

Problem: "IRE" matches as a substring in "ge26ire", "tire", "require", etc.
Solution: For short names (< 5 chars), require word-boundary matching instead of
simple substring matching. A "word boundary" here means the match is delimited by
dots, hyphens, underscores, slashes, digits-to-letters transitions, or string edges.
"""

import re
from typing import List, Set
from urllib.parse import urlparse


# Minimum length for simple substring matching.
# Names shorter than this use word-boundary matching.
_MIN_SUBSTRING_LENGTH = 5


def fair_name_in_url(fair_name_word: str, url: str) -> bool:
    """Check if a fair name word appears meaningfully in a URL.

    For short words (< 5 chars), requires word-boundary matching:
    - "ire" matches "ire-expo.com", "ire.mapyourshow.com", "ire2026"
    - "ire" does NOT match "ge26ire.mapyourshow.com", "require", "tired"

    For longer words, simple substring matching is used (false positive risk is low).

    Args:
        fair_name_word: A single keyword from the fair name (lowercase).
        url: The URL to check (will be lowercased internally).

    Returns:
        True if the fair name word appears meaningfully in the URL.
    """
    if not fair_name_word or not url:
        return False

    word = fair_name_word.lower()
    url_lower = url.lower()

    if len(word) >= _MIN_SUBSTRING_LENGTH:
        # Long enough for safe substring matching
        return word in url_lower

    # Short word: use word-boundary matching
    # Word boundaries in URLs: start/end of string, dots, hyphens, underscores,
    # slashes, and transitions between digits and letters (e.g., "26ire" → no match,
    # but "ire2026" → match because letter-to-digit is OK for fair+year patterns)
    return _short_word_matches_url(word, url_lower)


def _short_word_matches_url(word: str, url_lower: str) -> bool:
    """Check if a short word appears as a distinct segment in a URL.

    Matches when the word is bounded by URL separators (., -, _, /, start/end)
    or appears at a letter-to-digit boundary (for patterns like "ire2026").

    Does NOT match when preceded by other letters (e.g., "ge26ire" — the "ire"
    is part of a larger code, not a standalone reference to the fair).
    """
    # Build regex pattern:
    # - Lookbehind: start of string OR a separator OR a digit (digit→letter transition)
    # - The word itself
    # - Lookahead: end of string OR a separator OR a digit (letter→digit transition)
    #
    # This allows: "ire-expo.com", "ire.mapyourshow.com", "ire2026", "/ire/"
    # But blocks: "ge26ire", "tire", "require", "fire", "icegaming" for "ire"
    pattern = (
        r'(?:^|[.\-_/])'   # preceded by start or separator
        + re.escape(word)
        + r'(?:$|[.\-_/\d])'  # followed by end, separator, or digit
    )
    return bool(re.search(pattern, url_lower))


def fair_name_in_text(fair_name_word: str, text: str) -> bool:
    """Check if a fair name word appears meaningfully in free text.

    For short words (< 5 chars), requires word-boundary matching using \\b.
    For longer words, simple substring matching is used.

    Args:
        fair_name_word: A single keyword from the fair name (lowercase).
        text: The text to search (will be lowercased internally).

    Returns:
        True if the fair name word appears meaningfully in the text.
    """
    if not fair_name_word or not text:
        return False

    word = fair_name_word.lower()
    text_lower = text.lower()

    if len(word) >= _MIN_SUBSTRING_LENGTH:
        return word in text_lower

    # Short word: require word boundaries
    pattern = r'\b' + re.escape(word) + r'\b'
    return bool(re.search(pattern, text_lower))


def any_fair_keyword_in_url(fair_keywords: Set[str], url: str, min_length: int = 3) -> bool:
    """Check if ANY fair keyword appears meaningfully in a URL.

    Filters keywords by minimum length and uses appropriate matching
    (word-boundary for short keywords, substring for long ones).

    Args:
        fair_keywords: Set of fair name keywords (lowercase).
        url: The URL to check.
        min_length: Minimum keyword length to consider.

    Returns:
        True if any qualifying keyword matches.
    """
    for kw in fair_keywords:
        if len(kw) >= min_length and fair_name_in_url(kw, url):
            return True
    return False


def extract_fair_keywords(fair_name: str) -> List[str]:
    """Extract meaningful keywords from a fair name for matching.

    Returns keywords that can be used with fair_name_in_url() / fair_name_in_text().
    Includes the full concatenated name and individual significant words.

    Args:
        fair_name: The trade fair name (e.g., "IRE 2026", "Fruit Logistica").

    Returns:
        List of lowercase keywords, deduplicated.
    """
    keywords = set()

    # Remove year
    clean_name = re.sub(r'\s*20\d{2}\s*', ' ', fair_name).strip()
    words = clean_name.lower().split()

    stop_words = {
        'the', 'of', 'and', 'for', 'in', 'at', 'de', 'der', 'die', 'das',
        'van', 'het', 'een', 'fair', 'trade', 'show', 'exhibition',
        'expo', 'messe', 'fiera', 'salon', 'salone',
    }

    # Add full cleaned name
    full_name = clean_name.lower()
    if len(full_name) >= 3:
        keywords.add(full_name)

    # Add concatenated form (e.g., "fruit logistica" → "fruitlogistica")
    concat = clean_name.lower().replace(' ', '').replace('-', '')
    if len(concat) >= 3:
        keywords.add(concat)

    # Add individual significant words
    for word in words:
        if word not in stop_words and not word.isdigit() and len(word) >= 3:
            keywords.add(word)

    return sorted(keywords)


def is_different_fair_pdf(pdf_url: str, fair_name: str) -> bool:
    """Check if a PDF URL likely belongs to a DIFFERENT fair.

    Looks for other fair identifiers in the URL/filename that don't match
    the target fair. E.g., "LTW26_Standbuild_Guidelines.pdf" when looking
    for "IRE 2026".

    Args:
        pdf_url: URL of the PDF.
        fair_name: Target fair name.

    Returns:
        True if the PDF likely belongs to a different fair.
    """
    url_lower = pdf_url.lower()
    filename = url_lower.split('/')[-1] if '/' in url_lower else url_lower

    # Extract the target fair's keywords
    fair_kws = extract_fair_keywords(fair_name)
    fair_concat = re.sub(r'\s*20\d{2}\s*', '', fair_name).strip().lower().replace(' ', '')

    # Look for "XXNN" or "XXXXNN" patterns in the filename that could be other fair codes
    # E.g., "LTW26", "ISE24", "CES25"
    # Use [^a-z] instead of \b because \b treats underscore as a word character
    other_fair_codes = re.findall(r'(?:^|[^a-z])([a-z]{2,6})(2[0-9])(?:[^0-9]|$)', filename)

    for code, year_suffix in other_fair_codes:
        code_lower = code.lower()
        # If this code doesn't match any of our fair keywords, it's suspicious
        if code_lower not in fair_kws and code_lower != fair_concat:
            # Double check it's not a common non-fair abbreviation
            common_abbrevs = {'rev', 'ver', 'vol', 'doc', 'pdf', 'img', 'src', 'tmp', 'eng', 'deu'}
            if code_lower not in common_abbrevs:
                return True

    return False
