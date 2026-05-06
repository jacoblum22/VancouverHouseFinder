from __future__ import annotations

import sys

# Ensure UTF-8 output on Windows so Rich can render box-drawing and other
# non-ASCII characters without hitting the cp1252 codec limitation.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from datetime import date
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .models import SearchCriteria
from .pipeline import run_once

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def run(
    max_rent_cad: int = typer.Option(6600, help="Max rent in CAD/month."),
    min_bedrooms: int = typer.Option(4, help="Minimum number of bedrooms."),
    available_before: Optional[str] = typer.Option(
        "2026-09-01", help="Only include listings available on/before this date (YYYY-MM-DD)."
    ),
    city: str = typer.Option("Vancouver", help="City filter (normalized text)."),
) -> None:
    """Run the pipeline once (MVP entrypoint)."""
    avail_date: date | None = None
    if available_before:
        try:
            avail_date = date.fromisoformat(available_before)
        except ValueError:
            console.print(f"[red]Invalid date '{available_before}' — expected YYYY-MM-DD. Ignoring.[/red]")

    criteria = SearchCriteria(
        max_rent_cad=max_rent_cad,
        min_bedrooms=min_bedrooms,
        available_before=avail_date,
        city=city,
    )
    result = run_once(criteria=criteria)

    table = Table(title=f"VHF results (count={len(result.listings)})")
    table.add_column("Price", justify="right")
    table.add_column("Beds", justify="right")
    table.add_column("Availability")
    table.add_column("Neighborhood/Address")
    table.add_column("Source")
    table.add_column("URL", overflow="fold")

    for l in result.listings:
        table.add_row(
            "" if l.price_cad is None else f"${l.price_cad:,}",
            "" if l.bedrooms is None else str(l.bedrooms),
            "" if l.availability_date is None else l.availability_date.isoformat(),
            (l.neighborhood or l.address_text or ""),
            l.source,
            str(l.url),
        )

    console.print(table)

