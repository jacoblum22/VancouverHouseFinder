from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from vhf.listing_labels import (
    append_listing_kind_label,
    init_labels_file,
    read_listing_kind_labels,
)
from vhf.models import Listing


class TestListingLabelsFile(unittest.TestCase):
    def test_init_creates_header_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.csv"
            self.assertTrue(init_labels_file(path))
            self.assertFalse(init_labels_file(path))
            text = path.read_text(encoding="utf-8")
            self.assertIn("listing_key", text)
            self.assertIn("label", text)
            self.assertEqual(read_listing_kind_labels(path), {})

    def test_read_latest_row_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.csv"
            init_labels_file(path)
            append_listing_kind_label(path, row_key="s:1", label="whole_unit")
            append_listing_kind_label(path, row_key="s:1", label="room_or_partial")
            self.assertEqual(read_listing_kind_labels(path), {"s:1": "room_or_partial"})

    def test_append_invalid_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.csv"
            init_labels_file(path)
            with self.assertRaises(ValueError):
                append_listing_kind_label(path, row_key="s:1", label="not_a_label")

    def test_read_rejects_bad_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.csv"
            path.write_text(
                "listing_key,label,labeled_at,notes\ns:1,bad,x,\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                read_listing_kind_labels(path)

    def test_append_creates_file_without_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "labels.csv"
            fixed = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
            append_listing_kind_label(
                path, row_key="x:9", label="unclear", labeled_at=fixed
            )
            rows = read_listing_kind_labels(path)
            self.assertEqual(rows, {"x:9": "unclear"})
            body = path.read_text(encoding="utf-8")
            self.assertIn("2026-05-01T12:00:00+00:00", body)


class TestListingKeyReexport(unittest.TestCase):
    def test_matches_state_file_key(self) -> None:
        from vhf.listing_labels import listing_key as lk_labels
        from vhf.state_file import listing_key as lk_state

        lst = Listing.model_validate(
            {
                "source": "craigslist_van",
                "source_listing_id": "7933089018",
                "url": "https://vancouver.craigslist.org/van/apa/7933089018.html",
            }
        )
        self.assertEqual(lk_labels(lst), lk_state(lst))


if __name__ == "__main__":
    unittest.main()
