from __future__ import annotations

import asyncio
import hashlib
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from rich.console import Console

from ..models import Listing, RawDocument
from ..paths import RAW_DIR
from .base import SiteScraper

# Both housing categories on Craigslist
_CATEGORIES = ["apa", "hou"]
_BASE = "https://vancouver.craigslist.org"

# Area code in the URL path (position 3 of the path) that means "City of Vancouver"
# e.g. https://vancouver.craigslist.org/van/apa/d/.../12345.html -> area = "van"
_VANCOUVER_AREA_CODE = "van"

# Patterns applied to listing title / detail-page text
_RE_BEDS = re.compile(r"(\d+)[\s-]*(?:br|bd|bed|bedroom)s?\b", re.IGNORECASE)
_RE_BATHS = re.compile(r"(\d+(?:\.\d+)?)[\s-]*(?:ba|bath|bathroom)s?\b", re.IGNORECASE)
_RE_PRICE_TEXT = re.compile(r"[\d,]+")
# Canadian postal code: A1A 1A1 or A1A1A1
_RE_POSTAL_CODE = re.compile(r"\b[A-Za-z]\d[A-Za-z][\s-]?\d[A-Za-z]\d\b")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

console = Console()


class CraigslistVancouverScraper(SiteScraper):
    name = "craigslist_van"

    def __init__(self, max_price: int = 6600, min_bedrooms: int = 4) -> None:
        self.max_price = max_price
        self.min_bedrooms = min_bedrooms
        self._raw_dir = RAW_DIR / "craigslist"

    # ------------------------------------------------------------------
    # Search-page fetch + parse (stage 1)
    # ------------------------------------------------------------------

    async def fetch(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        self._raw_dir.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
            follow_redirects=True,
        ) as client:
            for i, category in enumerate(_CATEGORIES):
                url = (
                    f"{_BASE}/search/{category}"
                    f"?min_bedrooms={self.min_bedrooms}"
                    f"&max_price={self.max_price}"
                )
                console.print(f"  Fetching [cyan]{category}[/cyan] HTML...", end=" ")
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    body = resp.text
                except httpx.HTTPError as exc:
                    console.print(f"[red]FAILED[/red] ({exc})")
                    continue

                raw_path = self._raw_dir / f"{ts}_{category}.html"
                raw_path.write_text(body, encoding="utf-8")
                console.print(f"[green]OK[/green] -> {raw_path.name}")

                docs.append(
                    RawDocument(
                        source=self.name,
                        url=url,  # type: ignore[arg-type]
                        content_type="text/html",
                        body=body,
                    )
                )

                if i < len(_CATEGORIES) - 1:
                    await asyncio.sleep(2)

        return docs

    def parse(self, docs: list[RawDocument]) -> list[Listing]:
        seen_ids: set[str] = set()
        listings: list[Listing] = []

        for doc in docs:
            soup = BeautifulSoup(doc.body, "lxml")
            for item in soup.select("li.cl-static-search-result"):
                listing = self._parse_item(item)
                if listing is None:
                    continue
                lid = listing.source_listing_id or str(listing.url)
                if lid in seen_ids:
                    continue
                seen_ids.add(lid)
                listings.append(listing)

        return listings

    def _parse_item(self, item: Any) -> Listing | None:
        a_tag = item.select_one("a")
        if not a_tag:
            return None

        url: str = a_tag.get("href", "")
        if not url:
            return None

        if _area_code(url) != _VANCOUVER_AREA_CODE:
            return None

        title_tag = item.select_one("div.title")
        title: str = (
            item.get("title") or (title_tag.get_text(strip=True) if title_tag else "") or ""
        )

        price_tag = item.select_one("div.price")
        price = _parse_price(price_tag.get_text(strip=True) if price_tag else "")

        loc_tag = item.select_one("div.location")
        neighborhood = loc_tag.get_text(strip=True) if loc_tag else None

        return Listing(
            source=self.name,
            source_listing_id=_extract_id(url),
            url=url,  # type: ignore[arg-type]
            title=title or None,
            price_cad=price,
            bedrooms=_parse_beds(title),
            bathrooms=_parse_baths(title),
            neighborhood=neighborhood or None,
        )

    # ------------------------------------------------------------------
    # Detail-page fetch + enrich (stage 2)
    # ------------------------------------------------------------------

    async def fetch_details(
        self, listings: list[Listing]
    ) -> tuple[dict[str, RawDocument], int, int]:
        """Fetch individual listing pages for the given candidates.

        Returns (doc_map, n_fetched, n_cached):
          - doc_map:   source_listing_id -> RawDocument
          - n_fetched: listings fetched from network this run
          - n_cached:  listings loaded from the on-disk cache

        Cache key: data/raw/craigslist/details/{listing_id}.html
        A file is only fetched when its cache file does not exist yet.
        Concurrency is limited to 2 simultaneous requests with jitter.
        """
        results: dict[str, RawDocument] = {}
        details_dir = self._raw_dir / "details"
        details_dir.mkdir(parents=True, exist_ok=True)

        # Separate into cached vs needs-fetch
        cached_listings: list[tuple[str, str]] = []   # (lid, url)
        pending_listings: list[Listing] = []
        for listing in listings:
            url = str(listing.url)
            lid = listing.source_listing_id or _extract_id(url)
            cache_path = details_dir / f"{lid}.html"
            if cache_path.exists():
                cached_listings.append((lid, url))
            else:
                pending_listings.append(listing)

        # Load cached pages from disk (instant, no HTTP)
        for lid, url in cached_listings:
            body = (details_dir / f"{lid}.html").read_text(encoding="utf-8")
            results[lid] = RawDocument(
                source=self.name,
                url=url,  # type: ignore[arg-type]
                content_type="text/html",
                body=body,
            )

        n_cached = len(cached_listings)
        n_fetched = 0

        if not pending_listings:
            return results, n_fetched, n_cached

        sem = asyncio.Semaphore(2)
        total_pending = len(pending_listings)
        done_count: list[int] = [0]  # mutable container for nested async

        async def fetch_one(client: httpx.AsyncClient, listing: Listing) -> None:
            nonlocal n_fetched
            url = str(listing.url)
            lid = listing.source_listing_id or _extract_id(url)
            async with sem:
                for attempt in range(2):
                    await asyncio.sleep(
                        random.uniform(1.5, 3.0) if attempt == 0 else random.uniform(5.0, 9.0)
                    )
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 403 and attempt == 0:
                            continue  # back off and retry once
                        resp.raise_for_status()
                        body = resp.text
                        break
                    except httpx.HTTPError as exc:
                        if attempt == 1:
                            done_count[0] += 1
                            console.print(
                                f"    [{done_count[0]}/{total_pending}] [red]FAIL[/red] {lid}: {exc}"
                            )
                            return
                else:
                    done_count[0] += 1
                    console.print(
                        f"    [{done_count[0]}/{total_pending}] [red]FAIL[/red] {lid}: 403 after retry"
                    )
                    return

                (details_dir / f"{lid}.html").write_text(body, encoding="utf-8")
                results[lid] = RawDocument(
                    source=self.name,
                    url=url,  # type: ignore[arg-type]
                    content_type="text/html",
                    body=body,
                )
                n_fetched += 1
                done_count[0] += 1
                console.print(f"    [{done_count[0]}/{total_pending}] [green]OK[/green] {lid}")

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
            follow_redirects=True,
        ) as client:
            await asyncio.gather(*[fetch_one(client, l) for l in pending_listings])

        return results, n_fetched, n_cached

    def enrich_listings(
        self, listings: list[Listing], detail_docs: dict[str, RawDocument]
    ) -> tuple[list[Listing], int]:
        """Apply detail-page data to listings with missing bedrooms or address.

        Only fills None fields — does not overwrite existing values.
        Returns (updated_listings, enriched_count).
        """
        enriched_count = 0
        result: list[Listing] = []

        for listing in listings:
            lid = listing.source_listing_id or ""
            doc = detail_docs.get(lid)
            if doc is None:
                result.append(listing)
                continue

            detail = _parse_detail_page(doc.body)
            updates: dict[str, Any] = {}

            if listing.bedrooms is None and detail.get("bedrooms") is not None:
                updates["bedrooms"] = detail["bedrooms"]
            if listing.address_text is None:
                detail_addr = detail.get("address_text")
                lat = detail.get("latitude")
                lon = detail.get("longitude")
                has_coords = lat is not None and lon is not None
                # Parenthetical title spans often yield just the neighbourhood name.
                # When that happens, prefer map coords over the neighbourhood duplicate.
                addr_is_neighborhood = _addr_equals_neighborhood(detail_addr, listing.neighborhood)
                if detail_addr is not None and not addr_is_neighborhood:
                    updates["address_text"] = detail_addr
                elif has_coords:
                    updates["address_text"] = f"Approx map: {lat:.6f}, {lon:.6f}"
                elif detail_addr is not None:
                    # No coords available — neighbourhood text is better than nothing
                    updates["address_text"] = detail_addr

            if updates:
                result.append(listing.model_copy(update=updates))
                enriched_count += 1
            else:
                result.append(listing)

        return result, enriched_count


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _addr_equals_neighborhood(addr: str | None, neighborhood: str | None) -> bool:
    """Return True when addr is just a copy of the neighbourhood label.

    Craigslist title parentheticals like '(Shaughnessy)' often match the
    neighbourhood field exactly, making them useless as addresses.
    """
    if not addr or not neighborhood:
        return False
    def _norm(s: str) -> str:
        return "".join(ch.lower() for ch in s if ch.isalnum())
    return _norm(addr) == _norm(neighborhood)


def _area_code(url: str) -> str:
    """Return the Craigslist sub-area code from a listing URL.

    e.g. https://vancouver.craigslist.org/van/apa/d/.../12345.html -> 'van'
    """
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts else ""


def _extract_id(url: str) -> str:
    """Pull the numeric listing ID from a Craigslist URL.

    e.g. /van/apa/d/spacious-house/7932451130.html -> '7932451130'
    """
    stem = Path(urlparse(url).path).stem
    return stem if stem.isdigit() else hashlib.md5(url.encode()).hexdigest()[:16]


def _parse_price(text: str) -> int | None:
    m = _RE_PRICE_TEXT.search(text.replace(",", ""))
    return int(m.group()) if m else None


def _parse_beds(text: str) -> float | None:
    m = _RE_BEDS.search(text)
    return float(m.group(1)) if m else None


def _parse_baths(text: str) -> float | None:
    m = _RE_BATHS.search(text)
    return float(m.group(1)) if m else None


def _parse_detail_page(html: str) -> dict[str, Any]:
    """Extract bedrooms and address from a Craigslist detail-page HTML.

    Bedroom priority:
      1. span.housing          e.g. "/ 7br -"
      2. span#titletextonly    when housing span is empty
      3. full page text regex  last resort

    Address priority:
      1. h2.street-address     most reliable structured source
      2. parenthetical span    last span inside span.postingtitletext
      3. postal code regex     from full page text
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict[str, Any] = {}

    # --- Bedrooms ---
    housing = soup.select_one("span.housing")
    if housing:
        beds = _parse_beds(housing.get_text())
        if beds is not None:
            result["bedrooms"] = beds

    if "bedrooms" not in result:
        title_only = soup.select_one("span#titletextonly")
        if title_only:
            beds = _parse_beds(title_only.get_text())
            if beds is not None:
                result["bedrooms"] = beds

    if "bedrooms" not in result:
        beds = _parse_beds(soup.get_text(" "))
        if beds is not None:
            result["bedrooms"] = beds

    # --- Address ---
    street = soup.select_one("h2.street-address")
    if street:
        result["address_text"] = street.get_text(strip=True)

    if "address_text" not in result:
        for span in reversed(soup.select("span.postingtitletext > span")):
            text = span.get_text(strip=True)
            if text.startswith("(") and text.endswith(")"):
                inner = text[1:-1].strip()
                if inner:
                    result["address_text"] = inner
                break

    if "address_text" not in result:
        m = _RE_POSTAL_CODE.search(soup.get_text(" "))
        if m:
            result["address_text"] = m.group()

    # --- Map coordinates (fallback only — used when no address/postal found) ---
    map_div = soup.select_one("div#map[data-latitude]")
    if map_div:
        try:
            result["latitude"] = float(map_div["data-latitude"])
            result["longitude"] = float(map_div["data-longitude"])
        except (KeyError, ValueError, TypeError):
            pass

    return result
