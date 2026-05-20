"""HTML export: geo data-* on rows + map assets (smoke)."""

from __future__ import annotations

import unittest

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from vhf.export import export_html
from vhf.models import Listing


def _listing(**kwargs: object) -> Listing:
    base: dict[str, object] = {
        "source": "test_src",
        "url": "https://example.com/listing",
        "title": "Example title",
    }
    base.update(kwargs)
    return Listing(**base)


class TestExportHtmlGeoAttrs(unittest.TestCase):
    def test_tr_has_data_attrs_when_coords_present(self) -> None:
        listings = [
            _listing(
                url="https://example.com/a",
                latitude=49.25,
                longitude=-123.12,
                transit_minutes_to_ubc=42,
                title="With coords",
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.html"
            export_html(path, listings, generated_at=datetime.now(timezone.utc))
            soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        rows = soup.select("tbody tr")
        self.assertEqual(len(rows), 1)
        tr = rows[0]
        self.assertEqual(tr["data-listing-key"], "https://example.com/a")
        self.assertAlmostEqual(float(tr["data-latitude"]), 49.25)
        self.assertAlmostEqual(float(tr["data-longitude"]), -123.12)
        self.assertEqual(tr["data-url"], "https://example.com/a")

    def test_tr_omits_geo_attrs_when_coords_missing(self) -> None:
        listings = [_listing(latitude=None, longitude=None)]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.html"
            export_html(path, listings, generated_at=datetime.now(timezone.utc))
            soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        tr = soup.select_one("tbody tr")
        self.assertIsNotNone(tr)
        self.assertIsNone(tr.get("data-latitude"))
        self.assertIsNone(tr.get("data-longitude"))
        self.assertIsNone(tr.get("data-url"))
        self.assertEqual(tr.get("data-listing-key"), "https://example.com/listing")

    def test_tr_omits_geo_when_transit_missing(self) -> None:
        listings = [
            _listing(
                latitude=49.25,
                longitude=-123.12,
                transit_minutes_to_ubc=None,
                title="No transit",
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.html"
            export_html(path, listings, generated_at=datetime.now(timezone.utc))
            soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        tr = soup.select_one("tbody tr")
        self.assertIsNotNone(tr)
        self.assertIsNone(tr.get("data-latitude"))


class TestExportHtmlMapSmoke(unittest.TestCase):
    def test_leaflet_and_map_container_present(self) -> None:
        listings = [_listing(latitude=49.0, longitude=-123.0, transit_minutes_to_ubc=30)]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.html"
            export_html(path, listings, generated_at=datetime.now(timezone.utc))
            text = path.read_text(encoding="utf-8")
        self.assertIn('id="vhf-map"', text)
        self.assertIn("leaflet@1.9.4/dist/leaflet.css", text)
        self.assertIn("leaflet@1.9.4/dist/leaflet.js", text)
        self.assertIn("markercluster", text.lower())
        self.assertIn("bindTooltip", text)
        self.assertIn("clustermouseover", text)
        self.assertIn("getAllChildMarkers", text)
        self.assertIn("clusterTipHtml", text)
        self.assertIn("openTooltip", text)
        self.assertIn("vhf-pin-hover", text)
        self.assertIn("<strong>Price:</strong>", text)
        self.assertIn("<strong>Beds:</strong>", text)
        self.assertIn("<strong>Transit to UBC:</strong>", text)
        self.assertIn("<strong>Avg price:</strong>", text)
        self.assertIn("<strong>Avg transit:</strong>", text)
        self.assertNotIn("bindPopup", text)
        self.assertIn("flyTo", text)
        self.assertIn("vhf-row-highlight", text)
        self.assertIn("vhf-filters-changed", text)
        self.assertIn("tile.openstreetmap.org", text)


class TestExportHtmlDescription(unittest.TestCase):
    def test_data_listing_key_and_description_details(self) -> None:
        lst = Listing.model_validate(
            {
                "source": "src_a",
                "source_listing_id": "1",
                "url": "https://example.com/u",
                "title": "Hi",
                "description": "First line\nSecond line with <b>html</b> & chars",
            }
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.html"
            export_html(path, [lst], generated_at=datetime.now(timezone.utc))
            text = path.read_text(encoding="utf-8")
        self.assertIn('data-listing-key="src_a:1"', text)
        self.assertIn("<details>", text)
        self.assertIn("&lt;b&gt;html&lt;/b&gt;", text)
        self.assertIn("First line", text)


if __name__ == "__main__":
    unittest.main()
