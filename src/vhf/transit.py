from __future__ import annotations

import datetime
import json
import os
import re
import zoneinfo
from typing import Any

import httpx
from rich.console import Console

from .models import Listing
from .paths import PROCESSED_DIR

console = Console()

_ROUTES_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
_UBC_NEST = "6133 University Blvd, Vancouver, BC V6T 1Z1"
_CACHE_PATH = PROCESSED_DIR / "transit_cache.json"
_BATCH_SIZE = 100  # Google's transit element cap per request
_RE_APPROX = re.compile(r"Approx map:\s*([-\d.]+),\s*([-\d.]+)")


def _get_api_key() -> str | None:
    """Read key from env, then fall back to Windows user registry (set via setx)."""
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        try:
            import winreg  # type: ignore[import]
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg_key:
                key = winreg.QueryValueEx(reg_key, "GOOGLE_MAPS_API_KEY")[0]
        except Exception:
            pass
    return key or None


def _load_cache() -> dict[str, int]:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(cache: dict[str, int]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _cache_key(listing: Listing) -> str:
    if listing.source_listing_id:
        return f"{listing.source}:{listing.source_listing_id}"
    return f"addr:{listing.address_text or ''}"


def _build_waypoint(addr: str) -> dict[str, Any]:
    """Convert an address_text into a Routes API waypoint object.

    Handles both regular addresses and 'Approx map: lat, lng' strings.
    """
    m = _RE_APPROX.match(addr.strip())
    if m:
        return {
            "waypoint": {
                "location": {
                    "latLng": {
                        "latitude": float(m.group(1)),
                        "longitude": float(m.group(2)),
                    }
                }
            }
        }
    return {"waypoint": {"address": addr}}


def _next_weekday_830am_utc() -> str:
    """Return ISO 8601 UTC string for the next weekday 8:30 AM Vancouver time."""
    tz = zoneinfo.ZoneInfo("America/Vancouver")
    now = datetime.datetime.now(tz)
    for days_ahead in range(1, 8):
        candidate = (now + datetime.timedelta(days=days_ahead)).replace(
            hour=8, minute=30, second=0, microsecond=0
        )
        if candidate.weekday() < 5:  # Monday=0 ... Friday=4
            return candidate.astimezone(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
    # Fallback (should never reach here)
    return (datetime.datetime.utcnow() + datetime.timedelta(days=1)).strftime(
        "%Y-%m-%dT08:30:00Z"
    )


async def enrich_transit(listings: list[Listing]) -> tuple[list[Listing], int]:
    """Add transit_minutes_to_ubc to listings that don't have it yet.

    Checks on-disk cache first; only calls the API for genuinely new listings.
    Returns (updated_listings, n_newly_enriched).
    """
    api_key = _get_api_key()
    if not api_key:
        console.print(
            "  [yellow]SKIP[/yellow] Transit: GOOGLE_MAPS_API_KEY not set"
        )
        return listings, 0

    cache = _load_cache()

    # Apply already-cached values immediately
    def _apply_cache(l: Listing) -> Listing:
        ck = _cache_key(l)
        if l.transit_minutes_to_ubc is None and ck in cache:
            return l.model_copy(update={"transit_minutes_to_ubc": cache[ck]})
        return l

    listings = [_apply_cache(l) for l in listings]

    # Find listings still needing API enrichment
    to_enrich = [
        l for l in listings
        if l.transit_minutes_to_ubc is None and l.address_text is not None
    ]

    if not to_enrich:
        n_have = sum(1 for l in listings if l.transit_minutes_to_ubc is not None)
        console.print(f"  Transit: all {n_have} listings already cached")
        return listings, 0

    departure = _next_weekday_830am_utc()
    destination = [{"waypoint": {"address": _UBC_NEST}}]
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "originIndex,destinationIndex,status,condition,distanceMeters,duration"
        ),
    }

    # Map cache_key -> resolved minutes (None = no route)
    new_results: dict[str, int | None] = {}

    async with httpx.AsyncClient(timeout=60) as client:
        for batch_start in range(0, len(to_enrich), _BATCH_SIZE):
            batch = to_enrich[batch_start: batch_start + _BATCH_SIZE]
            origins = [_build_waypoint(l.address_text) for l in batch]  # type: ignore[arg-type]
            body = {
                "origins": origins,
                "destinations": destination,
                "travelMode": "TRANSIT",
                "departureTime": departure,
                "languageCode": "en-US",
                "units": "METRIC",
            }
            batch_num = batch_start // _BATCH_SIZE + 1
            console.print(
                f"  Transit API batch {batch_num} ({len(batch)} listings, "
                f"depart {departure})...",
                end=" ",
            )
            try:
                r = await client.post(_ROUTES_URL, json=body, headers=headers)
                r.raise_for_status()
                console.print("[green]OK[/green]")
                for elem in r.json():
                    idx = elem.get("originIndex", -1)
                    if not (0 <= idx < len(batch)):
                        continue
                    ck = _cache_key(batch[idx])
                    if elem.get("condition") == "ROUTE_EXISTS":
                        dur_str = str(elem.get("duration", ""))
                        try:
                            secs = int(dur_str.rstrip("s"))
                            new_results[ck] = round(secs / 60)
                        except (ValueError, TypeError):
                            new_results[ck] = None
                    else:
                        new_results[ck] = None
            except httpx.HTTPError as exc:
                console.print(f"[red]FAILED[/red] ({exc})")

    # Persist successful results to cache
    for ck, mins in new_results.items():
        if mins is not None:
            cache[ck] = mins
    _save_cache(cache)

    # Apply new results to listings
    enriched_count = 0
    result: list[Listing] = []
    for l in listings:
        ck = _cache_key(l)
        if l.transit_minutes_to_ubc is None and ck in new_results:
            mins = new_results[ck]
            if mins is not None:
                result.append(l.model_copy(update={"transit_minutes_to_ubc": mins}))
                enriched_count += 1
            else:
                result.append(l)
        else:
            result.append(l)

    return result, enriched_count
