"""Tests for results.html export verification (CI guard)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vhf.verify_export_html import collect_results_html_errors


def _minimal_valid_html(n_rows: int = 1) -> str:
    # One row with map pin; optional extra row without pin (no transit / no geo).
    parts: list[str] = []
    for i in range(n_rows):
        if i == 0:
            parts.append(
                f'<tr data-listing-key="k{i}" data-latitude="49.{i}" data-longitude="-123.{i}" '
                f'data-url="https://example.com/{i}">'
                f"<td>$1</td><td>2</td><td>42 min</td>"
                f"<td></td><td></td><td></td><td></td><td></td><td></td></tr>"
            )
        else:
            parts.append('<tr data-listing-key="k99">' + "<td></td>" * 9 + "</tr>")
    rows = "\n".join(parts)
    return f"""<!doctype html>
<html><head><title>t</title></head><body>
<div id="vhf-map"></div>
<table><thead><tr><th>x</th></tr></thead><tbody>
{rows}
</tbody></table>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
</body></html>"""


class TestVerifyExportHtml(unittest.TestCase):
    def test_valid_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "results.html"
            p.write_text(_minimal_valid_html(2), encoding="utf-8")
            self.assertEqual(collect_results_html_errors(p), [])

    def test_missing_file(self) -> None:
        errs = collect_results_html_errors(Path("/nonexistent/path/results.html"))
        self.assertTrue(any("Missing export" in e for e in errs))

    def test_missing_map_div(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "results.html"
            p.write_text(
                _minimal_valid_html(1).replace('id="vhf-map"', 'id="no-map"'),
                encoding="utf-8",
            )
            errs = collect_results_html_errors(p)
            self.assertTrue(any("vhf-map" in e for e in errs))

    def test_missing_leaflet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "results.html"
            p.write_text(_minimal_valid_html(1).replace("leaflet", "nomaplib"), encoding="utf-8")
            errs = collect_results_html_errors(p)
            self.assertTrue(any("Leaflet" in e for e in errs))

    def test_row_partial_geo_errors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "results.html"
            body = _minimal_valid_html(1).replace("data-longitude=", "data-x-longitude=")
            p.write_text(body, encoding="utf-8")
            errs = collect_results_html_errors(p)
            self.assertTrue(any("partial geo" in e for e in errs))

    def test_pin_without_transit_cell_errors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "results.html"
            body = _minimal_valid_html(1).replace("42 min", "")
            p.write_text(body, encoding="utf-8")
            errs = collect_results_html_errors(p)
            self.assertTrue(any("transit column" in e for e in errs))
