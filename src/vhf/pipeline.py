from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from rich.console import Console

from .dedupe import deduplicate, deduplicate_by_address
from .export import export_csv, export_html
from .filter import apply_criteria
from .models import Listing, SearchCriteria
from .paths import EXPORTS_DIR, PROCESSED_DIR
from .storage import write_jsonl

console = Console()


@dataclass(frozen=True)
class PipelineResult:
    listings: list[Listing]
    ran_at: datetime


def run_once(*, criteria: SearchCriteria) -> PipelineResult:
    """Synchronous entrypoint — drives the async pipeline internally."""
    return asyncio.run(_run_async(criteria=criteria))


async def _run_async(*, criteria: SearchCriteria) -> PipelineResult:
    from .sites.craigslist import CraigslistVancouverScraper
    from .sites.padmapper import PadMapperScraper
    from .sites.rentals_ca import RentalsCaScraper
    from .sites.zumper import ZumperScraper

    ran_at = datetime.utcnow()
    console.rule("[bold]Vancouver House Finder[/bold]")

    # ------------------------------------------------------------------ #
    # Stage 1: Craigslist — fetch search pages + detail-page enrichment   #
    # ------------------------------------------------------------------ #
    console.print("[bold]Craigslist[/bold]")
    cl_scraper = CraigslistVancouverScraper(
        max_price=criteria.max_rent_cad,
        min_bedrooms=criteria.min_bedrooms,
    )
    cl_docs = await cl_scraper.fetch()
    console.print(f"  HTML pages fetched: {len(cl_docs)}")

    cl_listings = cl_scraper.parse(cl_docs)
    console.print(f"  Listings parsed:    {len(cl_listings)}")

    cl_detail_docs, n_fetched, n_disk, n_state = await cl_scraper.fetch_details(cl_listings)
    parts = []
    if n_fetched:
        parts.append(f"{n_fetched} fetched")
    if n_disk:
        parts.append(f"{n_disk} disk-cached")
    if n_state:
        parts.append(f"{n_state} state-reused")
    note = f"  ({', '.join(parts)})" if parts else ""
    console.print(
        f"  Detail pages loaded:   {len(cl_detail_docs)}/{len(cl_listings)}{note}"
    )
    cl_listings, n_cl_enriched = cl_scraper.enrich_listings(cl_listings, cl_detail_docs)
    console.print(f"  Listings enriched:     {n_cl_enriched}")

    # ------------------------------------------------------------------ #
    # Stage 2: PadMapper — structured JSON, no detail pass needed         #
    # ------------------------------------------------------------------ #
    console.print("[bold]PadMapper[/bold]")
    pm_scraper = PadMapperScraper(
        max_price=criteria.max_rent_cad,
        min_bedrooms=criteria.min_bedrooms,
    )
    pm_docs = await pm_scraper.fetch()
    pm_listings = pm_scraper.parse(pm_docs)
    console.print(f"  Listings parsed:    {len(pm_listings)}")

    # ------------------------------------------------------------------ #
    # Stage 3: Rentals.ca — GraphQL API, structured data, no detail pass  #
    # ------------------------------------------------------------------ #
    console.print("[bold]Rentals.ca[/bold]")
    rc_scraper = RentalsCaScraper(
        max_price=criteria.max_rent_cad,
        min_bedrooms=criteria.min_bedrooms,
    )
    rc_docs = await rc_scraper.fetch()
    rc_listings = rc_scraper.parse(rc_docs)
    console.print(f"  Listings parsed:    {len(rc_listings)}")

    # ------------------------------------------------------------------ #
    # Stage 4: Zumper — same API family as PadMapper, no detail pass     #
    # ------------------------------------------------------------------ #
    console.print("[bold]Zumper[/bold]")
    zu_scraper = ZumperScraper(
        max_price=criteria.max_rent_cad,
        min_bedrooms=criteria.min_bedrooms,
    )
    zu_docs = await zu_scraper.fetch()
    zu_listings = zu_scraper.parse(zu_docs)
    console.print(f"  Listings parsed:    {len(zu_listings)}")

    # ------------------------------------------------------------------ #
    # Stage 5: combine, filter, dedupe, persist                           #
    # ------------------------------------------------------------------ #
    listings: list[Listing] = cl_listings + pm_listings + rc_listings + zu_listings
    console.print(f"  Combined total:        {len(listings)}")

    listings = apply_criteria(listings, criteria)
    console.print(f"  After filtering:       {len(listings)}")

    listings, n_addr_dropped = deduplicate_by_address(listings)
    console.print(
        f"  After address dedupe:  {len(listings)}"
        + (f" (-{n_addr_dropped} duplicates)" if n_addr_dropped else "")
    )
    listings = deduplicate(listings)
    console.print(f"  After URL dedupe:      {len(listings)}")

    # ------------------------------------------------------------------ #
    # Stage 6: transit enrichment — Google Routes API, cached per listing #
    # ------------------------------------------------------------------ #
    from .transit import enrich_transit
    console.print("[bold]Transit to UBC[/bold]")
    listings, n_transit = await enrich_transit(listings)
    if n_transit:
        console.print(f"  Newly enriched:        {n_transit}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "listings.jsonl"
    write_jsonl(out_path, listings)
    console.print(f"  Saved ->               {out_path}")

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = EXPORTS_DIR / "results.csv"
    html_path = EXPORTS_DIR / "results.html"
    export_csv(csv_path, listings)
    export_html(html_path, listings, generated_at=ran_at)
    console.print(f"  Exported CSV ->        {csv_path}")
    console.print(f"  Exported HTML ->       {html_path}")
    n_geo = sum(
        1 for x in listings if x.latitude is not None and x.longitude is not None
    )
    console.print(
        f"  Listings with lat/lng: {n_geo}/{len(listings)} "
        f"({100 * n_geo / len(listings):.0f}%)" if listings else "  Listings with lat/lng: 0/0"
    )
    console.rule()

    return PipelineResult(listings=listings, ran_at=ran_at)
