"""Rentals.ca listing display title (no HTTP deps — used by ``sites.rentals_ca`` and tests)."""

from __future__ import annotations

from typing import Any


def is_rentals_ca_room_listing(node: dict[str, Any]) -> bool:
    """True when Rentals.ca classifies this under the ``room`` category (not whole unit).

    ``listingType`` looks like ``residential:room:private-room`` or ``residential:room:room`` —
    we key off the second colon segment, not the word ``room`` in titles (avoids ``bedroom``).
    """
    s = str(node.get("listingType") or "").strip().lower()
    parts = [p for p in s.split(":") if p]
    return len(parts) >= 2 and parts[1] == "room"


def rentals_ca_listing_type_word(listing_type: object) -> str:
    """Short noun for titles: ``house``, ``room``, ``apartment``, ``multi unit``, …"""
    s = str(listing_type or "").strip().lower()
    if not s:
        return ""
    parts = [p for p in s.split(":") if p]
    if len(parts) >= 2 and parts[1] == "room":
        return "room"
    if parts:
        return parts[-1].replace("-", " ")
    return ""


def format_rentals_listing_title(
    node: dict[str, Any],
    *,
    street_line: str,
    city_name: str,
    region: str,
    max_beds: float | None,
) -> str | None:
    """Human-visible title similar to the site's heading (property kind + place + beds).

    GraphQL ``name`` is often a short or ALL-CAPS label; the site shows ``street + listingType``
    plus city/region and bedroom count (room vs house on rentals.ca listing pages).
    """
    name = (node.get("name") or "").strip()
    lt_raw = node.get("listingType")
    lt = rentals_ca_listing_type_word(lt_raw)

    street_line = street_line.strip()
    city_name = city_name.strip()
    region = region.strip()
    city_region = f"{city_name} {region}".strip()

    nb: int | None = None
    if max_beds is not None:
        try:
            nb = int(max_beds) if max_beds == int(max_beds) else int(round(max_beds))
        except (TypeError, ValueError):
            nb = None
    bed_suffix = f" ({nb}-Bedroom)" if nb is not None else ""

    left_base = street_line or name
    if not left_base:
        return name or None

    left = f"{left_base} {lt}".strip() if lt else left_base

    if lt == "room" and city_region:
        right = city_region
    elif name and street_line and name != street_line:
        right = f"{name}, {city_region}".strip().strip(",")
    elif street_line and city_region:
        right = f"{street_line}, {city_region}"
    elif city_region:
        right = city_region
    else:
        right = ""

    if right:
        return f"{left} — {right}{bed_suffix}"
    return f"{left}{bed_suffix}" if left else name
