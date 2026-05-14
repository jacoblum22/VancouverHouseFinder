from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from vhf.models import Listing
from vhf.state_file import (
    listing_key,
    listing_summary_for_state,
    listings_map_by_key,
    write_canonical_state_file,
)


class TestListingKey(unittest.TestCase):
    def test_prefers_source_id(self) -> None:
        lst = Listing.model_validate(
            {
                "source": "craigslist_van",
                "source_listing_id": "7933089018",
                "url": "https://vancouver.craigslist.org/van/apa/7933089018.html",
            }
        )
        self.assertEqual(listing_key(lst), "craigslist_van:7933089018")

    def test_falls_back_to_url(self) -> None:
        lst = Listing.model_validate(
            {
                "source": "x",
                "url": "https://Example.COM/path/",
            }
        )
        self.assertEqual(listing_key(lst), "https://example.com/path")


class TestListingsMapByKey(unittest.TestCase):
    def test_last_wins(self) -> None:
        first = Listing.model_validate(
            {"source": "s", "source_listing_id": "1", "url": "https://a/1", "title": "first"}
        )
        second = Listing.model_validate(
            {"source": "s", "source_listing_id": "1", "url": "https://a/1", "title": "second"}
        )
        m = listings_map_by_key([first, second])
        self.assertEqual(m["s:1"].title, "second")


class TestListingSummaryForState(unittest.TestCase):
    def test_shape(self) -> None:
        lst = Listing.model_validate(
            {
                "source": "s",
                "source_listing_id": "9",
                "url": "https://z.example/x",
                "title": "T",
                "price_cad": 1200,
            }
        )
        s = listing_summary_for_state(lst)
        self.assertEqual(s["title"], "T")
        self.assertEqual(s["price_cad"], 1200)
        self.assertIn("url", s)


class TestWriteCanonicalStateFile(unittest.TestCase):
    def test_entries_only_shape(self) -> None:
        fixed = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        entries = {"s:1": {"url": "https://x", "source": "s", "title": "T"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_seen.json"
            write_canonical_state_file(path, entries, updated_at=fixed)
            raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(raw.keys()), {"updated_at", "entries"})
        self.assertNotIn("keys", raw)
        self.assertEqual(raw["entries"]["s:1"]["title"], "T")

    def test_creates_parent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b" / "state.json"
            write_canonical_state_file(path, {})
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
