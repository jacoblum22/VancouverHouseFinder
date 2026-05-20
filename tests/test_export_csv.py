"""CSV export: listing_key, description, and safe quoting."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from vhf.export import export_csv
from vhf.models import Listing
from vhf.state_file import listing_key


class TestExportCsvListingKindFields(unittest.TestCase):
    def test_listing_key_and_description_columns(self) -> None:
        lst = Listing.model_validate(
            {
                "source": "test",
                "source_listing_id": "42",
                "url": "https://example.com/a",
                "title": "T",
                "description": "Line one\nLine two & <tag>",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            export_csv(path, [lst])
            with path.open(encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["listing_key"], listing_key(lst))
        self.assertIn("Line one", row["description"])
        self.assertIn("\n", row["description"] or "")
        self.assertIn("<tag>", row["description"] or "")

    def test_empty_description(self) -> None:
        lst = Listing.model_validate(
            {"source": "s", "url": "https://example.com/z", "title": "Only"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            export_csv(path, [lst])
            with path.open(encoding="utf-8", newline="") as fh:
                row = next(csv.DictReader(fh))
        self.assertEqual(row.get("description"), "")


if __name__ == "__main__":
    unittest.main()
