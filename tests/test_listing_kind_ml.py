"""Tests for listing_kind_ml (optional scikit-learn)."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

_SKLEARN = importlib.util.find_spec("sklearn") is not None


class TestRowListingKey(unittest.TestCase):
    def test_derives_from_source_columns(self) -> None:
        from vhf.listing_kind_ml import row_listing_key

        row = {"source": "craigslist_van", "source_listing_id": "7929666902", "url": "https://x"}
        self.assertEqual(row_listing_key(row), "craigslist_van:7929666902")

    def test_prefers_explicit_column(self) -> None:
        from vhf.listing_kind_ml import row_listing_key

        row = {
            "listing_key": "custom:key",
            "source": "a",
            "source_listing_id": "1",
        }
        self.assertEqual(row_listing_key(row), "custom:key")


@unittest.skipUnless(_SKLEARN, "scikit-learn not installed (pip install -e '.[ml]')")
class TestListingKindMLTrain(unittest.TestCase):
    def test_train_and_suggest(self) -> None:
        from vhf.listing_kind_ml import suggest_listing_kind_labels, train_listing_kind

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            export = base / "export.csv"
            labels = base / "labels.csv"

            rows = [
                {
                    "listing_key": f"k{i}",
                    "price_cad": str(1000 + i * 500),
                    "bedrooms": "4",
                    "bathrooms": "2" if i % 2 == 0 else "",
                    "title": "Room in shared house" if i % 2 == 0 else "Whole house for rent",
                    "description": (
                        "room for rent near campus"
                        if i % 2 == 0
                        else "entire home single family"
                    ),
                    "url": f"https://example.com/{i}",
                }
                for i in range(8)
            ]
            rows.extend(
                [
                    {
                        "listing_key": "u9",
                        "price_cad": "2000",
                        "bedrooms": "4",
                        "bathrooms": "",
                        "title": "Ambiguous basement",
                        "description": "might be suite",
                        "url": "https://example.com/9",
                    },
                    {
                        "listing_key": "u10",
                        "price_cad": "2100",
                        "bedrooms": "4",
                        "bathrooms": "",
                        "title": "Another ambiguous",
                        "description": "shared or not unclear",
                        "url": "https://example.com/10",
                    },
                ]
            )

            fieldnames = list(rows[0].keys())
            with export.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)

            labels.write_text(
                "listing_key,label,labeled_at,notes\n"
                "k0,room_or_partial,2026-01-01T00:00:00+00:00,\n"
                "k1,whole_unit,2026-01-01T00:00:00+00:00,\n"
                "k2,room_or_partial,2026-01-01T00:00:00+00:00,\n"
                "k3,whole_unit,2026-01-01T00:00:00+00:00,\n"
                "k4,room_or_partial,2026-01-01T00:00:00+00:00,\n"
                "k5,whole_unit,2026-01-01T00:00:00+00:00,\n"
                "k6,room_or_partial,2026-01-01T00:00:00+00:00,\n"
                "k7,whole_unit,2026-01-01T00:00:00+00:00,\n",
                encoding="utf-8",
            )

            report = train_listing_kind(export_csv=export, labels_csv=labels)
            self.assertEqual(report.n_fit, 8)
            self.assertGreaterEqual(report.cv_accuracy, 0.0)

            sug = suggest_listing_kind_labels(
                export_csv=export, labels_csv=labels, top_n=5
            )
            keys = {s.listing_key for s in sug}
            self.assertTrue(keys.issubset({"u9", "u10"}))
            self.assertGreater(len(sug), 0)


@unittest.skipUnless(_SKLEARN, "scikit-learn not installed")
class TestListingKindMLImportError(unittest.TestCase):
    def test_require_sklearn_message(self) -> None:
        # If sklearn is present, _require_sklearn should not raise.
        from vhf.listing_kind_ml import _require_sklearn

        _require_sklearn()


if __name__ == "__main__":
    unittest.main()
