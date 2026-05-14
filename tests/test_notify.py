from __future__ import annotations

import unittest
from datetime import UTC, datetime

from vhf.notify import _build_email, _price_display_stored


class TestNotifyFormatting(unittest.TestCase):
    def test_price_display_int(self) -> None:
        self.assertEqual(_price_display_stored(3800), "$3,800")

    def test_price_display_whole_float(self) -> None:
        self.assertEqual(_price_display_stored(3800.0), "$3,800")

    def test_price_display_nonwhole_float(self) -> None:
        self.assertEqual(_price_display_stored(1999.6), "$2,000")

    def test_price_display_none_and_bool(self) -> None:
        self.assertEqual(_price_display_stored(None), "?")
        self.assertEqual(_price_display_stored(True), "?")

    def test_build_email_includes_removed_table(self) -> None:
        plain, html = _build_email(
            [],
            [
                {
                    "title": "Gone",
                    "url": "https://example.com/a",
                    "source": "src",
                    "price_cad": 2500,
                    "bedrooms": 3.0,
                    "neighborhood": "Kits",
                    "address_text": "1 Main",
                    "transit_minutes_to_ubc": 40,
                }
            ],
            3,
            datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        )
        self.assertIn("REMOVED", plain)
        self.assertIn("Gone", plain)
        self.assertIn("$2,500", plain)
        self.assertIn("Removed (1)", html)
        self.assertIn("Gone", html)


if __name__ == "__main__":
    unittest.main()
