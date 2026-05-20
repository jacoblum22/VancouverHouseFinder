from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import httpx
from rich.console import Console

from ..models import Listing, RawDocument
from ..paths import RAW_DIR
from .base import SiteScraper

# Same underlying API family as PadMapper (Zumper acquired PadMapper).
# The filtered URL path bakes bedrooms + max-price into the request body,
# so no extra query-string fiddling is needed.
_API_URL = "https://www.zumper.com/api/t/1/pages/listables"
_BASE_URL = "https://www.zumper.com"
_PAGE_SIZE = 25

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

console = Console()


class ZumperScraper(SiteScraper):
    """Fetches Vancouver rental listings from Zumper's internal JSON API.

    Endpoint: POST /api/t/1/pages/listables
    Body: {"url": "vancouver-bc/4+beds/under-6600", "limit": 25, "offset": N}
    Response: {"listables": [...], "listing_count": N, ...}
    """

    name = "zumper"

    def __init__(self, max_price: int = 6600, min_bedrooms: int = 4) -> None:
        self.max_price = max_price
        self.min_bedrooms = min_bedrooms
        self._raw_dir = RAW_DIR / "zumper"

    async def fetch(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        self._raw_dir.mkdir(parents=True, exist_ok=True)

        url_slug = f"vancouver-bc/{self.min_bedrooms}+beds/under-{self.max_price}"
        referer = f"https://www.zumper.com/apartments-for-rent/{url_slug}"

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": referer,
            "Origin": _BASE_URL,
        }

        async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
            offset = 0
            page = 1
            while True:
                body = {
                    "url": url_slug,
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                }
                console.print(
                    f"  Fetching [cyan]Zumper[/cyan] page {page} (offset={offset})...",
                    end=" ",
                )
                try:
                    resp = await client.post(_API_URL, json=body)
                    resp.raise_for_status()
                    payload = resp.text
                except httpx.HTTPError as exc:
                    console.print(f"[red]FAILED[/red] ({exc})")
                    break

                try:
                    data = json.loads(payload)
                    items: list[Any] = data.get("listables") or []
                    n = len(items)
                except (json.JSONDecodeError, AttributeError):
                    n = 0

                raw_path = self._raw_dir / f"{ts}_page{page}.json"
                raw_path.write_text(payload, encoding="utf-8")
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
                    break

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
                console.print("  [yellow]WARNING[/yellow] Zumper: failed to parse JSON")
                continue

            items: list[Any] = data.get("listables") or []
            if not items:
                console.print("  [yellow]WARNING[/yellow] Zumper: empty listables in response")
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
    """Normalise a single Zumper listable JSON object into a Listing."""
    url_path: str = item.get("url") or ""
    if not url_path:
        return None

    # Drop shared-room / room-for-rent listings.
    # property_type 16 = shared room, 17 = room in home.
    prop_type = item.get("property_type")
    if prop_type in (16, 17):
        return None
    pl_url = (item.get("pl_url") or "").lower()
    if "room-for-rent" in url_path.lower() or "room-for-rent" in pl_url:
        return None

    # City filter — restrict to City of Vancouver only.
    city: str = (item.get("city") or "").strip()
    state_code: str = (item.get("state") or "").strip()
    if city and city.lower() != "vancouver":
        return None
    if state_code and state_code.upper() != "BC":
        return None

    full_url = f"{_BASE_URL}{url_path}"

    listing_id = item.get("listing_id")
    source_id = str(listing_id) if listing_id is not None else None

    price_raw = item.get("min_price") or item.get("max_price")
    price = int(price_raw) if price_raw is not None else None

    beds_raw = item.get("min_bedrooms")
    if beds_raw is None:
        beds_raw = item.get("max_bedrooms")
    bedrooms = float(beds_raw) if beds_raw is not None else None

    addr_parts = [
        (item.get("address") or "").strip(),
        (item.get("city") or "").strip(),
        (item.get("state") or "").strip(),
        (item.get("zipcode") or "").strip(),
    ]
    address_text: str | None = ", ".join(p for p in addr_parts if p) or None

    neighborhood: str | None = item.get("neighborhood_name") or None

    lat: float | None = None
    lng: float | None = None
    try:
        if item.get("lat") is not None and item.get("lng") is not None:
            lat = float(item["lat"])
            lng = float(item["lng"])
    except (TypeError, ValueError):
        pass

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
        title=None,
        price_cad=price,
        bedrooms=bedrooms,
        address_text=address_text,
        neighborhood=neighborhood,
        availability_date=avail_date,
        latitude=lat,
        longitude=lng,
    )
