"""Rentals.ca scraper using the site's GraphQL API.

Auth flow (discovered from JS bundle app-CZpfPB5z.js, D5 class):
  1. POST /graphql with `acquireAuthInfo` mutation + the public API key
     (embedded as window.appconf.rentalsGqlKey on every page load)
  2. Response contains {accessToken, refreshToken} (access expires in ~15 min)
  3. Use accessToken as `Authorization: Bearer <token>` for search queries
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from curl_cffi.requests import AsyncSession
from rich.console import Console

from ..models import Listing, RawDocument
from ..paths import RAW_DIR
from ..rentals_ca_title import format_rentals_listing_title, is_rentals_ca_room_listing
from .base import SiteScraper

console = Console()

_GQL_URL = "https://rentals.ca/graphql"
_GQL_KEY = "kJFM-mm4c-xg6B-qiwy"  # public key embedded in every page's window.appconf
_RENTALS_BASE = "https://rentals.ca"
_VANCOUVER_H3 = "8628de8c7ffffff"
_PAGE_SIZE = 100

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://rentals.ca",
    "Referer": "https://rentals.ca/vancouver",
}

_ACQUIRE_MUTATION = json.dumps({
    "operationName": "getToken",
    "query": (
        "mutation getToken($apiKey: String!) {"
        "  acquireAuthInfo(credentials: {apiKey: $apiKey}) { status jwt message }"
        "}"
    ),
    "variables": {"apiKey": _GQL_KEY},
})

_SEARCH_QUERY = """\
query RentalListingSearch(
  $first: PositiveInt,
  $after: String,
  $place: PlaceInput!,
  $filters: RentalListingsConnectionFilterSet
) {
  rentalListings(first: $first, after: $after, place: $place, filters: $filters) {
    meta { totalCount totalFloorPlanCount }
    pageInfo { endCursor hasNextPage }
    edges {
      node {
        id
        path
        name
        listingType
        location
        address { street streetSuffix cityName regionCode postalCode }
        rentRange
        bedsRange
        bathsRange
        floorPlans { beds baths rent availability }
      }
    }
  }
}"""


class RentalsCaScraper(SiteScraper):
    """Fetch Vancouver rental listings from the Rentals.ca GraphQL API."""

    name = "rentals_ca"

    def __init__(self, max_price: int = 6600, min_bedrooms: int = 4) -> None:
        self.max_price = max_price
        self.min_bedrooms = min_bedrooms
        self._raw_dir = RAW_DIR / "rentals_ca"

    async def fetch(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        self._raw_dir.mkdir(parents=True, exist_ok=True)

        async with AsyncSession(impersonate="chrome") as session:
            # Step 1: acquire a short-lived JWT via the public API key
            access_token = await _acquire_token(session)
            if not access_token:
                console.print("  [red]ERROR[/red] Rentals.ca: failed to acquire auth token")
                return docs

            console.print(f"  [cyan]Rentals.ca[/cyan] auth token acquired, fetching listings...")

            cursor: str | None = None
            page = 1

            while True:
                variables: dict[str, Any] = {
                    "first": _PAGE_SIZE,
                    "place": {"h3": {"indexes": [_VANCOUVER_H3], "ringDepth": 1}},
                    "filters": {},
                }
                if cursor:
                    variables["after"] = cursor

                body = json.dumps({
                    "operationName": "RentalListingSearch",
                    "query": _SEARCH_QUERY,
                    "variables": variables,
                })

                console.print(
                    f"  Fetching [cyan]Rentals.ca[/cyan] page {page}"
                    + (f" (after={cursor[:20]}...)" if cursor else ""),
                    end=" ",
                )

                try:
                    resp = await session.post(
                        _GQL_URL,
                        data=body,
                        headers={**_HEADERS, "Authorization": f"Bearer {access_token}"},
                        timeout=30,
                    )
                except Exception as exc:
                    console.print(f"[red]FAILED[/red] (network error: {exc})")
                    break

                if resp.status_code == 401:
                    console.print("[yellow]WARN[/yellow] token expired, re-acquiring...")
                    access_token = await _acquire_token(session)
                    if not access_token:
                        console.print("[red]ERROR[/red] re-acquire failed, aborting")
                        break
                    continue

                if resp.status_code != 200:
                    console.print(f"[red]FAILED[/red] (HTTP {resp.status_code})")
                    break

                payload = resp.text
                raw_path = self._raw_dir / f"{ts}_page{page:03d}.json"
                raw_path.write_text(payload, encoding="utf-8")

                try:
                    data = json.loads(payload)
                    rl = (data.get("data") or {}).get("rentalListings") or {}
                    edges = rl.get("edges") or []
                    page_info = rl.get("pageInfo") or {}
                    n = len(edges)
                    has_next = page_info.get("hasNextPage", False)
                    cursor = page_info.get("endCursor")
                except Exception:
                    n = 0
                    has_next = False

                console.print(f"[green]OK[/green] -> {raw_path.name} ({n} items)")

                docs.append(RawDocument(
                    source=self.name,
                    url=_GQL_URL,  # type: ignore[arg-type]
                    content_type="application/json",
                    body=payload,
                ))

                if not has_next or not cursor:
                    break
                page += 1

        return docs

    def parse(self, docs: list[RawDocument]) -> list[Listing]:
        seen_ids: set[str] = set()
        listings: list[Listing] = []

        for doc in docs:
            try:
                data = json.loads(doc.body)
            except json.JSONDecodeError:
                console.print("  [yellow]WARNING[/yellow] Rentals.ca: failed to parse JSON")
                continue

            edges = ((data.get("data") or {}).get("rentalListings") or {}).get("edges") or []

            for edge in edges:
                node = edge.get("node") or {}
                listing = _parse_node(node, self.name)
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

async def _acquire_token(session: AsyncSession) -> str | None:
    """Exchange the public API key for a short-lived JWT access token."""
    try:
        resp = await session.post(
            _GQL_URL,
            data=_ACQUIRE_MUTATION,
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        d = resp.json()
        jwt_obj = ((d.get("data") or {}).get("acquireAuthInfo") or {}).get("jwt") or {}
        if isinstance(jwt_obj, dict):
            return jwt_obj.get("accessToken")
        return jwt_obj if isinstance(jwt_obj, str) else None
    except Exception:
        return None


def _parse_node(node: dict[str, Any], source: str) -> Listing | None:
    """Normalize a single RentalListing GraphQL node into a Listing."""
    path: str = node.get("path") or ""
    if not path:
        return None

    node_id: str = node.get("id") or ""
    full_url = f"{_RENTALS_BASE}/{path}"

    if is_rentals_ca_room_listing(node):
        return None

    # -- City filter: Vancouver proper only --
    addr: dict[str, Any] = node.get("address") or {}
    city_name = (addr.get("cityName") or "").strip()
    if city_name and city_name.lower() != "vancouver":
        return None

    street = (addr.get("street") or "").strip()
    suffix = (addr.get("streetSuffix") or "").strip()
    street_line = f"{street} {suffix}".strip() if suffix else street
    region = (addr.get("regionCode") or "").strip()

    # -- Bedrooms --
    beds_range: list[float] = node.get("bedsRange") or []
    max_beds = float(max(beds_range)) if beds_range else None

    title: str | None = format_rentals_listing_title(
        node,
        street_line=street_line,
        city_name=city_name,
        region=region,
        max_beds=max_beds,
    )
    if not title:
        title = (node.get("name") or "").strip() or None

    # -- Price: find the cheapest floor plan at the highest bedroom count --
    floor_plans: list[dict[str, Any]] = node.get("floorPlans") or []
    rent_range: list[float] = node.get("rentRange") or []

    price_cad: int | None = None
    avail_date: date | None = None

    if floor_plans and max_beds is not None:
        # Floor plans matching the highest bed count in this listing
        top_fps = [fp for fp in floor_plans if (fp.get("beds") or 0) == max_beds]
        if top_fps:
            rents = [fp.get("rent") for fp in top_fps if fp.get("rent") is not None]
            if rents:
                price_cad = int(min(rents))
            # Earliest future availability date among top-bed floor plans
            for fp in top_fps:
                avail_obj = fp.get("availability") or {}
                if isinstance(avail_obj, dict):
                    d_str = avail_obj.get("date")
                    if d_str:
                        try:
                            fp_date = date.fromisoformat(str(d_str)[:10])
                            if avail_date is None or fp_date < avail_date:
                                avail_date = fp_date
                        except (ValueError, TypeError):
                            pass

    # Fallback to aggregate range if floorplan data is missing
    if price_cad is None and rent_range:
        price_cad = int(min(rent_range))

    # -- Address string --
    city = city_name
    postal = (addr.get("postalCode") or "").strip()
    parts = [street_line, city, region, postal]
    address_text: str | None = ", ".join(p for p in parts if p) or None

    # GeographyPoint scalar: [longitude, latitude]
    lat: float | None = None
    lng: float | None = None
    loc = node.get("location")
    if isinstance(loc, (list, tuple)) and len(loc) >= 2:
        try:
            lng = float(loc[0])
            lat = float(loc[1])
        except (TypeError, ValueError):
            pass

    # -- Bathrooms (from first matching floor plan) --
    bathrooms: float | None = None
    if floor_plans and max_beds is not None:
        top_fps_b = [fp for fp in floor_plans if (fp.get("beds") or 0) == max_beds and fp.get("baths") is not None]
        if top_fps_b:
            bathrooms = float(top_fps_b[0]["baths"])

    return Listing(
        source=source,
        source_listing_id=node_id or None,
        url=full_url,  # type: ignore[arg-type]
        title=title,
        price_cad=price_cad,
        bedrooms=max_beds,
        bathrooms=bathrooms,
        address_text=address_text,
        availability_date=avail_date,
        latitude=lat,
        longitude=lng,
    )
