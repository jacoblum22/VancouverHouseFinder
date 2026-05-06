from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path

from .models import Listing


def export_csv(path: Path, listings: list[Listing]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "price_cad",
                "bedrooms",
                "bathrooms",
                "availability_date",
                "transit_min_to_ubc",
                "neighborhood",
                "address_or_postal",
                "address_text",
                "source",
                "source_listing_id",
                "url",
                "title",
            ],
        )
        w.writeheader()
        for l in listings:
            w.writerow(
                {
                    "price_cad": l.price_cad,
                    "bedrooms": l.bedrooms,
                    "bathrooms": l.bathrooms,
                    "availability_date": l.availability_date.isoformat()
                    if l.availability_date
                    else "",
                    "transit_min_to_ubc": l.transit_minutes_to_ubc
                    if l.transit_minutes_to_ubc is not None
                    else "",
                    "neighborhood": l.neighborhood or "",
                    "address_or_postal": l.address_text or "",
                    "address_text": l.address_text or "",
                    "source": l.source,
                    "source_listing_id": l.source_listing_id or "",
                    "url": str(l.url),
                    "title": l.title or "",
                }
            )


def export_html(path: Path, listings: list[Listing], *, generated_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def td(val: str) -> str:
        return f"<td>{html.escape(val)}</td>"

    rows: list[str] = []
    for l in listings:
        price = "" if l.price_cad is None else f"${l.price_cad:,}"
        beds = "" if l.bedrooms is None else str(l.bedrooms)
        neigh = l.neighborhood or ""
        address_or_postal = l.address_text or ""
        transit = (
            "" if l.transit_minutes_to_ubc is None else f"{l.transit_minutes_to_ubc} min"
        )
        url = str(l.url)
        title = l.title or ""
        rows.append(
            "<tr>"
            + td(price)
            + td(beds)
            + td(transit)
            + td(neigh)
            + td(address_or_postal)
            + td(l.source)
            + f"<td><a href=\"{html.escape(url)}\" target=\"_blank\" rel=\"noreferrer\">link</a></td>"
            + td(title)
            + "</tr>"
        )

    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>VHF Results</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }}
    .meta {{ color: #444; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f6f6f6; text-align: left; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #fcfcfc; }}
    .nowrap {{ white-space: nowrap; }}
  </style>
</head>
<body>
  <h2>Vancouver House Finder — Results</h2>
  <div class="meta">Generated at: {html.escape(generated_at.isoformat())} — Count: {len(listings)}</div>
  <table>
    <thead>
      <tr>
        <th class="nowrap">Price</th>
        <th class="nowrap">Beds</th>
        <th class="nowrap">Transit to UBC</th>
        <th>Neighborhood</th>
        <th>Address/Postal</th>
        <th class="nowrap">Source</th>
        <th class="nowrap">URL</th>
        <th>Title</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")

