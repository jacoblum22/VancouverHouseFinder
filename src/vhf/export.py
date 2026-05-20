from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path

from .models import Listing
from .state_file import listing_key


def _listing_key_attr(listing: Listing) -> str:
    k = listing_key(listing)
    return f' data-listing-key="{html.escape(k, quote=True)}"'


def _description_cell(listing: Listing) -> str:
    raw = (listing.description or "").strip()
    if not raw:
        return "<td></td>"
    preview = raw.replace("\n", " ")
    if len(preview) > 140:
        preview = preview[:137] + "..."
    esc_full = html.escape(raw)
    esc_preview = html.escape(preview)
    body = esc_full.replace("\n", "<br />")
    return (
        '<td class="vhf-desc"><details><summary>'
        + esc_preview
        + '</summary><div class="vhf-desc-body">'
        + body
        + "</div></details></td>"
    )


def _tr_data_attrs(listing: Listing) -> str:
    """Optional data-* for map / tooling (not shown as table columns).

    Pins are omitted when Google Routes did not return a transit time to UBC,
    so the map only shows listings with a known-good routing response.
    """
    if (
        listing.latitude is None
        or listing.longitude is None
        or listing.transit_minutes_to_ubc is None
    ):
        return ""
    lat = html.escape(str(listing.latitude), quote=True)
    lng = html.escape(str(listing.longitude), quote=True)
    url = html.escape(str(listing.url), quote=True)
    return f' data-latitude="{lat}" data-longitude="{lng}" data-url="{url}"'


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
                "latitude",
                "longitude",
                "source",
                "source_listing_id",
                "listing_key",
                "url",
                "title",
                "description",
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
                    "latitude": l.latitude if l.latitude is not None else "",
                    "longitude": l.longitude if l.longitude is not None else "",
                    "source": l.source,
                    "source_listing_id": l.source_listing_id or "",
                    "listing_key": listing_key(l),
                    "url": str(l.url),
                    "title": l.title or "",
                    "description": l.description or "",
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
            "<tr"
            + _listing_key_attr(l)
            + _tr_data_attrs(l)
            + ">"
            + td(price)
            + td(beds)
            + td(transit)
            + td(neigh)
            + td(address_or_postal)
            + td(l.source)
            + f"<td><a href=\"{html.escape(url)}\" target=\"_blank\" rel=\"noreferrer\">link</a></td>"
            + td(title)
            + _description_cell(l)
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
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" crossorigin="" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" crossorigin="" />
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }}
    .meta {{ color: #444; margin-bottom: 16px; }}
    #vhf-map {{ height: 380px; width: 100%; max-width: 960px; margin-bottom: 20px; border-radius: 8px; border: 1px solid #e0e0e0; z-index: 0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f6f6f6; text-align: left; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #fcfcfc; }}
    .nowrap {{ white-space: nowrap; }}
    th.sortable {{ cursor: pointer; user-select: none; }}
    th.sortable .sort-indicator {{ color: #888; margin-left: 4px; font-size: 12px; }}
    tbody tr[data-latitude] {{ cursor: pointer; }}
    tbody tr.vhf-row-highlight {{ outline: 2px solid #2563eb; outline-offset: -2px; background: #eef5ff !important; }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; margin-bottom: 18px; padding: 14px 16px; background: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 8px; max-width: 960px; }}
    .filters label {{ display: flex; flex-direction: column; font-size: 13px; gap: 5px; color: #333; }}
    .filters input {{ min-width: 110px; padding: 7px 9px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; }}
    .filter-clear {{ padding: 8px 14px; font-size: 14px; cursor: pointer; border: 1px solid #ccc; border-radius: 4px; background: #fff; align-self: flex-end; }}
    .filter-clear:hover {{ background: #f0f0f0; }}
    .filters-hint {{ font-size: 12px; color: #666; width: 100%; margin: 0; line-height: 1.4; }}
    .leaflet-tooltip.vhf-pin-hover {{
      background: #fff;
      color: #111;
      border: 1px solid #ccc;
      border-radius: 8px;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
      padding: 0;
      max-width: 280px;
    }}
    .leaflet-tooltip.vhf-pin-hover .vhf-tip {{ padding: 10px 12px; font-size: 13px; line-height: 1.45; }}
    .leaflet-tooltip.vhf-pin-hover .vhf-tip p {{ margin: 0 0 6px 0; }}
    .leaflet-tooltip.vhf-pin-hover .vhf-tip p:last-child {{ margin-bottom: 0; }}
    .leaflet-tooltip.vhf-pin-hover .vhf-tip-link {{ margin-top: 8px; }}
    .leaflet-tooltip.vhf-pin-hover a {{ color: #1d4ed8; }}
    .vhf-desc {{ font-size: 13px; max-width: 420px; }}
    .vhf-desc summary {{ cursor: pointer; color: #1d4ed8; }}
    .vhf-desc-body {{ margin-top: 8px; white-space: normal; line-height: 1.45; }}
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
  <div id="vhf-map" role="application" aria-label="Listings map"></div>
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
        <th class="sortable">Description<span class="sort-indicator"></span></th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
  <script src="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js" crossorigin=""></script>
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
        window.dispatchEvent(new Event("vhf-filters-changed"));
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
  <script>
    (function () {{
      const mapEl = document.getElementById("vhf-map");
      const table = document.querySelector("table");
      if (!mapEl || !table || typeof L === "undefined") return;
      const tbody = table.querySelector("tbody");
      if (!tbody) return;

      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({{
        iconRetinaUrl: "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-shadow.png",
      }});

      const useClusters = typeof L.markerClusterGroup === "function";
      const layer = useClusters
        ? L.markerClusterGroup({{ showCoverageOnHover: false, maxClusterRadius: 55 }})
        : L.layerGroup();
      const map = L.map(mapEl).setView([49.25, -123.12], 11);
      L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }}).addTo(map);
      layer.addTo(map);

      let rowToMarker = new WeakMap();

      function clearRowHighlight() {{
        tbody.querySelectorAll("tr.vhf-row-highlight").forEach((r) => r.classList.remove("vhf-row-highlight"));
      }}

      function esc(s) {{
        return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
      }}

      const COL_TRANSIT_CELL = 2;
      const COL_BEDS_CELL = 1;
      const COL_PRICE_CELL = 0;

      function parseCellPrice(td) {{
        const t = (td && td.textContent || "").trim();
        if (!t) return null;
        const n = Number(t.replace(/[^0-9.-]/g, ""));
        return Number.isFinite(n) ? n : null;
      }}

      function parseCellTransitMin(td) {{
        const t = (td && td.textContent || "").trim();
        if (!t) return null;
        const n = Number(t.replace(/[^0-9.-]/g, ""));
        return Number.isFinite(n) ? n : null;
      }}

      function clusterTipHtml(cluster) {{
        const markers =
          cluster && cluster.getAllChildMarkers ? cluster.getAllChildMarkers() : [];
        let sumP = 0;
        let nP = 0;
        let sumT = 0;
        let nT = 0;
        markers.forEach(function (mk) {{
          const row = mk._vhfRow;
          if (!row) return;
          const cells = row.querySelectorAll("td");
          const p = parseCellPrice(cells[COL_PRICE_CELL]);
          const tr = parseCellTransitMin(cells[COL_TRANSIT_CELL]);
          if (p !== null) {{
            sumP += p;
            nP++;
          }}
          if (tr !== null) {{
            sumT += tr;
            nT++;
          }}
        }});
        const n = markers.length;
        const lines = [];
        lines.push("<p><strong>" + n + " listings</strong></p>");
        if (nP) {{
          const avg = Math.round(sumP / nP);
          lines.push(
            "<p><strong>Avg price:</strong> $" + avg.toLocaleString("en-CA") + "/mo</p>"
          );
        }} else {{
          lines.push("<p><strong>Avg price:</strong> —</p>");
        }}
        if (nT) {{
          lines.push("<p><strong>Avg transit:</strong> " + Math.round(sumT / nT) + " min</p>");
        }} else {{
          lines.push("<p><strong>Avg transit:</strong> —</p>");
        }}
        return '<div class="vhf-tip vhf-cluster-tip">' + lines.join("") + "</div>";
      }}

      if (useClusters) {{
        layer.on("clustermouseover", function (e) {{
          const c = e.layer;
          const html = clusterTipHtml(c);
          c.unbindTooltip();
          c.bindTooltip(html, {{
            sticky: true,
            direction: "auto",
            opacity: 1,
            className: "vhf-pin-hover vhf-cluster-hover",
            interactive: false,
          }});
          c.openTooltip();
        }});
      }}

      function rowHasTransitMinutes(row) {{
        const cells = row.querySelectorAll("td");
        const td = cells[COL_TRANSIT_CELL];
        const t = (td && td.textContent || "").trim();
        return /[0-9]/.test(t);
      }}

      function visibleGeoRows() {{
        return Array.from(tbody.querySelectorAll("tr")).filter((row) => {{
          if (row.style.display === "none") return false;
          const lat = row.getAttribute("data-latitude");
          const lng = row.getAttribute("data-longitude");
          if (!lat || !lng) return false;
          // Match table: no pin if Google transit did not return a time (stale data-* safe).
          return rowHasTransitMinutes(row);
        }});
      }}

      function rebuildMarkers() {{
        clearRowHighlight();
        layer.clearLayers();
        rowToMarker = new WeakMap();
        const latlngs = [];
        visibleGeoRows().forEach((row) => {{
          const lat = parseFloat(row.getAttribute("data-latitude") || "");
          const lng = parseFloat(row.getAttribute("data-longitude") || "");
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
          latlngs.push([lat, lng]);
          const url = row.getAttribute("data-url") || "";
          const cells = row.querySelectorAll("td");
          const priceTxt = (cells[COL_PRICE_CELL] && cells[COL_PRICE_CELL].textContent || "").trim();
          const bedsTxt = (cells[COL_BEDS_CELL] && cells[COL_BEDS_CELL].textContent || "").trim();
          const transitTxt = (cells[COL_TRANSIT_CELL] && cells[COL_TRANSIT_CELL].textContent || "").trim();
          const m = L.marker([lat, lng]);
          const link = url
            ? '<p class="vhf-tip-link"><a href="' + esc(url) + '" target="_blank" rel="noreferrer">Open listing</a></p>'
            : "";
          const tip =
            '<div class="vhf-tip">' +
            "<p><strong>Price:</strong> " + esc(priceTxt || "—") + "</p>" +
            "<p><strong>Beds:</strong> " + esc(bedsTxt || "—") + "</p>" +
            "<p><strong>Transit to UBC:</strong> " + esc(transitTxt || "—") + "</p>" +
            link +
            "</div>";
          m.bindTooltip(tip, {{
            interactive: true,
            sticky: true,
            direction: "auto",
            opacity: 1,
            className: "vhf-pin-hover",
          }});
          m._vhfRow = row;
          m.addTo(layer);
          rowToMarker.set(row, m);
          m.on("click", () => {{
            clearRowHighlight();
            row.classList.add("vhf-row-highlight");
            row.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
            m.openTooltip();
          }});
        }});
        if (latlngs.length) {{
          map.fitBounds(latlngs, {{ padding: [28, 28], maxZoom: 14 }});
        }}
      }}

      tbody.addEventListener("click", (ev) => {{
        if (ev.target.closest("a")) return;
        const tr = ev.target.closest("tr");
        if (!tr || tr.parentElement !== tbody) return;
        if (!tr.getAttribute("data-latitude")) return;
        const marker = rowToMarker.get(tr);
        if (!marker) return;
        const ll = marker.getLatLng();
        map.flyTo(ll, Math.max(map.getZoom(), 15), {{ duration: 0.45 }});
        marker.openTooltip();
      }});

      rebuildMarkers();
      window.addEventListener("vhf-filters-changed", rebuildMarkers);
      setTimeout(() => map.invalidateSize(), 100);
    }})();
  </script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
