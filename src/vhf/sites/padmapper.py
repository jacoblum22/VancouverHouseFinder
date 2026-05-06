from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import httpx
from rich.console import Console

from ..models import Listing, RawDocument
from ..paths import RAW_DIR
from .base import SiteScraper

# Internal JSON API discovered from JS bundle analysis.
# Uses POST with a URL-path body that mirrors the browser URL pattern.
_API_URL = "https://www.padmapper.com/api/t/1/pages/listables"
_PADMAPPER_BASE = "https://www.padmapper.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_PAGE_SIZE = 20

console = Console()


class PadMapperScraper(SiteScraper):
    """Fetches Vancouver rental listings from PadMapper's internal JSON API.

    Discovered path: POST /api/t/1/pages/listables
    Body: {"url": "vancouver-bc/4+beds", "limit": 20, "offset": N, "max_price": M}
    Response: {"listables": {"listables": [...]}, "filters": {...}, ...}
    """

    name = "padmapper"

    def __init__(self, max_price: int = 6600, min_bedrooms: int = 4) -> None:
        self.max_price = max_price
        self.min_bedrooms = min_bedrooms
        self._raw_dir = RAW_DIR / "padmapper"

    async def fetch(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        self._raw_dir.mkdir(parents=True, exist_ok=True)

        url_filter = f"vancouver-bc/{self.min_bedrooms}+beds"
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": f"https://www.padmapper.com/apartments/{url_filter}",
            "Origin": "https://www.padmapper.com",
        }

        async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
            offset = 0
            page = 1
            while True:
                body = {
                    "url": url_filter,
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                    "max_price": self.max_price,
                }
                console.print(
                    f"  Fetching [cyan]PadMapper[/cyan] page {page} (offset={offset})...",
                    end=" ",
                )
                try:
                    resp = await client.post(_API_URL, json=body)
                    resp.raise_for_status()
                    payload = resp.text
                except httpx.HTTPError as exc:
                    console.print(f"[red]FAILED[/red] ({exc})")
                    break

                raw_path = self._raw_dir / f"{ts}_page{page}.json"
                raw_path.write_text(payload, encoding="utf-8")

                # Count items to decide whether to paginate
                try:
                    data = json.loads(payload)
                    lb = data.get("listables", {})
                    items = lb.get("listables", []) if isinstance(lb, dict) else (lb or [])
                    n = len(items)
                except (json.JSONDecodeError, AttributeError):
                    n = 0

                console.print(f"[green]OK[/green] -> {raw_path.name} ({n} items)")

                docs.append(
                    RawDocument(
                        source=self.name,
                        url=_API_URL,  # type: ignore[arg-type]
                        content_type="application/json",
                        body=payload,
                    )
                )

                if n < _PAGE_SIZE:
                    break  # last page

                offset += _PAGE_SIZE
                page += 1

        return docs

    def parse(self, docs: list[RawDocument]) -> list[Listing]:
        seen_ids: set[str] = set()
        listings: list[Listing] = []

        for doc in docs:
            try:
                data = json.loads(doc.body)
            except json.JSONDecodeError:
                console.print("  [yellow]WARNING[/yellow] PadMapper: failed to parse JSON response")
                continue

            lb = data.get("listables", {})
            items: list[Any] = lb.get("listables", []) if isinstance(lb, dict) else (lb or [])

            if not items:
                console.print("  [yellow]WARNING[/yellow] PadMapper: empty listables in response")
                continue

            for item in items:
                listing = _parse_listable(item, self.name)
                if listing is None:
                    continue
                lid = listing.source_listing_id or str(listing.url)
                if lid in seen_ids:
                    continue
                seen_ids.add(lid)
                listings.append(listing)

        return listings


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_listable(item: dict[str, Any], source: str) -> Listing | None:
    """Normalize a single PadMapper listable JSON object into a Listing."""
    url_path: str = item.get("url") or ""
    if not url_path:
        return None

    # Room-for-rent filter — skip rooms inside shared houses, not whole-unit rentals.
    # property_type 16 = shared room (PadMapper's own search excludes this type).
    # URL/pl_url slug check is a redundant safety net.
    # NOTE: check for "room-for-rent" not just "room" — "bedroom" contains "room".
    prop_type = item.get("property_type")
    if prop_type == 16:
        return None
    pl_url = (item.get("pl_url") or "").lower()
    if "room-for-rent" in url_path.lower() or "room-for-rent" in pl_url:
        return None

    # City filter — include only City of Vancouver (or unknown city, to be lenient)
    city: str = (item.get("city") or "").strip()
    state_code: str = (item.get("state") or "").strip()
    if city and city.lower() != "vancouver":
        return None
    if state_code and state_code.upper() != "BC":
        return None

    full_url = f"{_PADMAPPER_BASE}{url_path}"

    listing_id = item.get("listing_id")
    source_id = str(listing_id) if listing_id is not None else None

    # Price: prefer min_price (equals max_price for single-unit listings)
    price_raw = item.get("min_price") or item.get("max_price")
    price = int(price_raw) if price_raw is not None else None

    # Bedrooms: prefer min_bedrooms
    beds_raw = item.get("min_bedrooms")
    if beds_raw is None:
        beds_raw = item.get("max_bedrooms")
    bedrooms = float(beds_raw) if beds_raw is not None else None

    # Address: combine structured fields into a single readable string
    addr_parts = [
        (item.get("address") or "").strip(),
        (item.get("city") or "").strip(),
        (item.get("state") or "").strip(),
        (item.get("zipcode") or "").strip(),
    ]
    non_empty = [p for p in addr_parts if p]
    address_text = ", ".join(non_empty) if non_empty else None

    neighborhood = item.get("neighborhood_name") or None
    title = item.get("title") or item.get("building_name") or None

    # Availability date — API returns 'YYYY/MM/DD' or 'YYYY-MM-DD'
    avail_date: date | None = None
    avail_raw = item.get("date_available")
    if avail_raw:
        try:
            avail_date = date.fromisoformat(str(avail_raw)[:10].replace("/", "-"))
        except (ValueError, TypeError):
            pass

    return Listing(
        source=source,
        source_listing_id=source_id,
        url=full_url,  # type: ignore[arg-type]
        title=title,
        price_cad=price,
        bedrooms=bedrooms,
        address_text=address_text,
        neighborhood=neighborhood,
        availability_date=avail_date,
    )
