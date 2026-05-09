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

    n = len(listings)
    listing_word = "listing" if n == 1 else "listings"
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
    th.sortable {{ cursor: pointer; user-select: none; }}
    th.sortable .sort-indicator {{ color: #888; margin-left: 4px; font-size: 12px; }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; margin-bottom: 18px; padding: 14px 16px; background: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 8px; max-width: 960px; }}
    .filters label {{ display: flex; flex-direction: column; font-size: 13px; gap: 5px; color: #333; }}
    .filters input {{ min-width: 110px; padding: 7px 9px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; }}
    .filter-clear {{ padding: 8px 14px; font-size: 14px; cursor: pointer; border: 1px solid #ccc; border-radius: 4px; background: #fff; align-self: flex-end; }}
    .filter-clear:hover {{ background: #f0f0f0; }}
    .filters-hint {{ font-size: 12px; color: #666; width: 100%; margin: 0; line-height: 1.4; }}
  </style>
</head>
<body>
  <h2>Vancouver House Finder — Results</h2>
  <div class="meta">
    <span id="vhf-timestamp">Generated at: {html.escape(generated_at.isoformat())}</span>
    — <span id="vhf-count-line">{n} {listing_word}</span>
  </div>
  <div class="filters" aria-label="Filter listings in the browser">
    <p class="filters-hint">These filters only change what you see on this page. Scraped data, CSV, and email alerts are unchanged.</p>
    <label>Min price (CAD)<input type="number" id="vhf-min-price" min="0" step="1" placeholder="Any" inputmode="numeric" /></label>
    <label>Max price (CAD)<input type="number" id="vhf-max-price" min="0" step="1" placeholder="Any" inputmode="numeric" /></label>
    <label>Max transit (min to UBC)<input type="number" id="vhf-max-transit" min="0" step="1" placeholder="Any" inputmode="numeric" /></label>
    <button type="button" id="vhf-clear-filters" class="filter-clear">Clear</button>
  </div>
  <table>
    <thead>
      <tr>
        <th class="nowrap sortable">Price<span class="sort-indicator"></span></th>
        <th class="nowrap sortable">Beds<span class="sort-indicator"></span></th>
        <th class="nowrap sortable">Transit to UBC<span class="sort-indicator"></span></th>
        <th class="sortable">Neighborhood<span class="sort-indicator"></span></th>
        <th class="sortable">Address/Postal<span class="sort-indicator"></span></th>
        <th class="nowrap sortable">Source<span class="sort-indicator"></span></th>
        <th class="nowrap sortable">URL<span class="sort-indicator"></span></th>
        <th class="sortable">Title<span class="sort-indicator"></span></th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <script>
    (function () {{
      const COL_PRICE = 0;
      const COL_TRANSIT = 2;
      const table = document.querySelector("table");
      if (!table) return;
      const tbody = table.querySelector("tbody");
      const countLine = document.getElementById("vhf-count-line");
      const minEl = document.getElementById("vhf-min-price");
      const maxEl = document.getElementById("vhf-max-price");
      const transitEl = document.getElementById("vhf-max-transit");
      const clearBtn = document.getElementById("vhf-clear-filters");
      const headers = Array.from(table.querySelectorAll("thead th.sortable"));
      let sortedCol = -1;
      let ascending = true;

      function parsePrice(td) {{
        const t = (td && td.textContent || "").trim();
        if (!t) return null;
        const n = Number(t.replace(/[^0-9.-]/g, ""));
        return Number.isFinite(n) ? n : null;
      }}

      function parseTransit(td) {{
        const t = (td && td.textContent || "").trim();
        if (!t) return null;
        const n = Number(t.replace(/[^0-9.-]/g, ""));
        return Number.isFinite(n) ? n : null;
      }}

      function filtersActive() {{
        return (
          (minEl.value.trim() !== "" && Number.isFinite(Number(minEl.value))) ||
          (maxEl.value.trim() !== "" && Number.isFinite(Number(maxEl.value))) ||
          (transitEl.value.trim() !== "" && Number.isFinite(Number(transitEl.value)))
        );
      }}

      function applyFilters() {{
        const minV = Number(minEl.value);
        const maxV = Number(maxEl.value);
        const maxT = Number(transitEl.value);
        const hasMin = minEl.value.trim() !== "" && Number.isFinite(minV);
        const hasMax = maxEl.value.trim() !== "" && Number.isFinite(maxV);
        const hasTransit = transitEl.value.trim() !== "" && Number.isFinite(maxT);
        let visible = 0;
        const total = tbody.querySelectorAll("tr").length;
        tbody.querySelectorAll("tr").forEach((row) => {{
          const cells = row.children;
          const price = parsePrice(cells[COL_PRICE]);
          const transit = parseTransit(cells[COL_TRANSIT]);
          let show = true;
          if (price !== null && price <= 0) show = false;
          if (show && hasMin && price !== null && price < minV) show = false;
          if (show && hasMax && price !== null && price > maxV) show = false;
          if (show && hasTransit && transit !== null && transit > maxT) show = false;
          row.style.display = show ? "" : "none";
          if (show) visible++;
        }});
        if (countLine) {{
          if (filtersActive()) {{
            countLine.textContent = `Showing ${{visible}} of ${{total}}`;
          }} else {{
            countLine.textContent = total + (total === 1 ? " listing" : " listings");
          }}
        }}
      }}

      function toSortValue(text, colIndex) {{
        const raw = text.trim();
        if (colIndex === 0) return Number(raw.replace(/[^0-9.-]/g, "")) || 0;
        if (colIndex === 1) return Number(raw.replace(/[^0-9.-]/g, "")) || 0;
        if (colIndex === 2) return Number(raw.replace(/[^0-9.-]/g, "")) || 0;
        return raw.toLowerCase();
      }}

      function updateIndicators() {{
        headers.forEach((h, i) => {{
          const indicator = h.querySelector(".sort-indicator");
          if (!indicator) return;
          indicator.textContent = i === sortedCol ? (ascending ? "▲" : "▼") : "";
        }});
      }}

      headers.forEach((header, colIndex) => {{
        header.addEventListener("click", () => {{
          const rows = Array.from(tbody.querySelectorAll("tr"));
          if (sortedCol === colIndex) {{
            ascending = !ascending;
          }} else {{
            sortedCol = colIndex;
            ascending = true;
          }}

          rows.sort((a, b) => {{
            const aText = a.children[colIndex]?.textContent || "";
            const bText = b.children[colIndex]?.textContent || "";
            const av = toSortValue(aText, colIndex);
            const bv = toSortValue(bText, colIndex);
            if (av < bv) return ascending ? -1 : 1;
            if (av > bv) return ascending ? 1 : -1;
            return 0;
          }});

          rows.forEach((row) => tbody.appendChild(row));
          updateIndicators();
          applyFilters();
        }});
      }});

      [minEl, maxEl, transitEl].forEach((el) => el.addEventListener("input", applyFilters));
      clearBtn.addEventListener("click", () => {{
        minEl.value = "";
        maxEl.value = "";
        transitEl.value = "";
        applyFilters();
      }});
    }})();
  </script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
