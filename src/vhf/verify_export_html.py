"""CI/local checks that the published results HTML still has map + valid geo rows."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from .paths import EXPORTS_DIR


def collect_results_html_errors(path: Path) -> list[str]:
    """Return human-readable errors; empty list means the export looks valid."""
    errs: list[str] = []
    if not path.is_file():
        errs.append(f"Missing export file: {path}")
        return errs

    text = path.read_text(encoding="utf-8")
    if 'id="vhf-map"' not in text:
        errs.append('Expected id="vhf-map" in HTML')
    if "leaflet" not in text.lower():
        errs.append("Expected Leaflet assets (leaflet.js or leaflet.css) in HTML")
    if "markercluster" not in text.lower():
        errs.append("Expected Leaflet.markercluster assets in HTML")

    soup = BeautifulSoup(text, "html.parser")
    rows = soup.select("table > tbody > tr")
    if not rows:
        return errs

    for i, tr in enumerate(rows):
        lat_a = tr.get("data-latitude")
        lng_a = tr.get("data-longitude")
        if lat_a is None and lng_a is None:
            # No map pin (e.g. no transit time from Google Routes).
            continue
        if lat_a is None or lng_a is None:
            errs.append(f"Row {i}: partial geo (latitude/longitude must both be set)")
            continue
        try:
            float(lat_a)
            float(lng_a)
        except (TypeError, ValueError):
            errs.append(f"Row {i}: non-numeric data-latitude or data-longitude")
            continue

        tds = tr.find_all("td")
        if len(tds) < 3:
            errs.append(
                f"Row {i}: map pin row has fewer than 3 <td> cells (need transit column)"
            )
            continue
        transit_txt = tds[2].get_text(strip=True)
        if not transit_txt or not re.search(r"\d", transit_txt):
            errs.append(
                f"Row {i}: map pin (data-latitude) but transit column is empty "
                "(must match Google transit time in table)"
            )

    return errs


def main() -> int:
    path = EXPORTS_DIR / "results.html"
    errs = collect_results_html_errors(path)
    for e in errs:
        print(e, file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
