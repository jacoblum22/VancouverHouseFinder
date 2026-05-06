from __future__ import annotations

import re

from .models import Listing

_RE_MULTI_SPACE = re.compile(r"\s+")
_RE_PUNCT = re.compile(r"[,\.]")
# Match postal code with a space in the middle so we can collapse it: "V5V 1H3" -> "v5v1h3"
_RE_POSTAL_SPACE = re.compile(r"([a-z]\d[a-z])\s+(\d[a-z]\d)", re.IGNORECASE)
_RE_HAS_DIGIT = re.compile(r"\d")


def deduplicate_by_address(listings: list[Listing]) -> tuple[list[Listing], int]:
    """Cluster listings that share the same canonical street address and keep the best one.

    Only addresses that contain at least one digit are used as cluster keys.
    Generic strings like "Vancouver" or "Commercial Drive" are too vague and are
    skipped, falling through to the URL-based dedupe pass instead.

    Returns (result_listings, n_dropped).
    """
    no_key: list[Listing] = []
    by_address: dict[str, list[Listing]] = {}

    for listing in listings:
        if not listing.address_text:
            no_key.append(listing)
            continue
        key = _canonical_address(listing.address_text)
        if not key or not _RE_HAS_DIGIT.search(key):
            # Too vague to use as a dedupe key
            no_key.append(listing)
            continue
        by_address.setdefault(key, []).append(listing)

    result: list[Listing] = list(no_key)
    dropped = 0

    for group in by_address.values():
        best = max(group, key=_completeness_score)
        result.append(best)
        dropped += len(group) - 1

    return result, dropped


def deduplicate(listings: list[Listing]) -> list[Listing]:
    """Remove duplicate listings using a two-tier key strategy.

    Tier 1: source + source_listing_id (exact match within a source).
    Tier 2: normalized URL with query-string stripped (catches same listing
            posted with different tracking parameters).

    The first occurrence wins; later duplicates are dropped.
    """
    seen_source_ids: set[str] = set()
    seen_urls: set[str] = set()
    result: list[Listing] = []

    for listing in listings:
        source_key = (
            f"{listing.source}::{listing.source_listing_id}"
            if listing.source_listing_id
            else None
        )
        url_key = str(listing.url).split("?")[0].rstrip("/")

        if source_key and source_key in seen_source_ids:
            continue
        if url_key in seen_urls:
            continue

        if source_key:
            seen_source_ids.add(source_key)
        seen_urls.add(url_key)
        result.append(listing)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _canonical_address(text: str) -> str:
    """Normalize an address string to a stable dedupe key.

    e.g. "1257 E 18TH AVE, Vancouver, BC V5V1H3"
      -> "1257 e 18th ave vancouver bc v5v1h3"
    """
    text = text.lower().strip()
    text = _RE_PUNCT.sub(" ", text)
    # Collapse any space inside a postal code: "v5v 1h3" -> "v5v1h3"
    text = _RE_POSTAL_SPACE.sub(lambda m: m.group(1).lower() + m.group(2).lower(), text)
    text = _RE_MULTI_SPACE.sub(" ", text).strip()
    return text


def _completeness_score(listing: Listing) -> int:
    """Score a listing by data completeness — higher is better.

    Used to pick the "winner" when two listings share the same address.
    """
    score = 0
    if listing.bedrooms is not None:
        score += 2
    if listing.price_cad is not None:
        score += 1
    if listing.address_text:
        # Prefer full street addresses (contain digits) over vague labels
        if _RE_HAS_DIGIT.search(listing.address_text):
            score += 2
        else:
            score += 1
    return score
