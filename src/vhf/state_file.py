"""Helpers for ``data/state/last_seen.json`` (listing keys, summaries, atomic write)."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import Listing


def listing_key(listing: Listing) -> str:
    """Stable identifier for a listing across runs."""
    if listing.source_listing_id:
        return f"{listing.source}:{listing.source_listing_id}"
    return str(listing.url).lower().rstrip("/")


def listing_summary_for_state(listing: Listing) -> dict[str, Any]:
    """Payload shape stored under *entries* in last_seen.json."""
    return {
        "url": str(listing.url),
        "title": listing.title,
        "source": listing.source,
        "price_cad": listing.price_cad,
        "bedrooms": listing.bedrooms,
        "neighborhood": listing.neighborhood,
        "address_text": listing.address_text,
        "transit_minutes_to_ubc": listing.transit_minutes_to_ubc,
    }


def listings_map_by_key(listings: Iterable[Listing]) -> dict[str, Listing]:
    """Last listing wins if duplicate keys appear in *listings*."""
    return {listing_key(l): l for l in listings}


def write_canonical_state_file(
    path: Path,
    entries: Mapping[str, Mapping[str, Any]],
    *,
    updated_at: datetime | None = None,
) -> None:
    """Write ``{updated_at, entries}`` to *path* via temp file + rename (no *keys* field).

    Creates *path.parent* if missing. On failure, removes the temp file when possible.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (updated_at or datetime.now(UTC)).isoformat()
    body: dict[str, Any] = {
        "updated_at": stamp,
        "entries": {str(k): dict(v) for k, v in entries.items()},
    }
    text = json.dumps(body, indent=2)
    fd, tmp = tempfile.mkstemp(
        prefix=".last_seen_",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
