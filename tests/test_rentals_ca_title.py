"""Rentals.ca display title (listingType + address + beds)."""

from __future__ import annotations

import unittest

from vhf.rentals_ca_title import format_rentals_listing_title, is_rentals_ca_room_listing


class TestRentalsCaRoomFilter(unittest.TestCase):
    def test_room_listing_type(self) -> None:
        self.assertTrue(
            is_rentals_ca_room_listing({"listingType": "residential:room:room"})
        )
        self.assertTrue(
            is_rentals_ca_room_listing({"listingType": "residential:room:private-room"})
        )

    def test_not_room(self) -> None:
        self.assertFalse(
            is_rentals_ca_room_listing({"listingType": "residential:house:house"})
        )
        self.assertFalse(
            is_rentals_ca_room_listing({"listingType": "residential:apartment:apartment"})
        )
        self.assertFalse(is_rentals_ca_room_listing({}))


class TestRentalsCaTitle(unittest.TestCase):
    def test_room_listing_matches_site_shape(self) -> None:
        node = {
            "name": "",
            "listingType": "residential:room:room",
            "address": {},
        }
        t = format_rentals_listing_title(
            node,
            street_line="6423 Main Street",
            city_name="Vancouver",
            region="BC",
            max_beds=6.0,
        )
        self.assertEqual(t, "6423 Main Street room — Vancouver BC (6-Bedroom)")

    def test_house_listing_when_name_differs_from_street(self) -> None:
        node = {
            "name": "1500 66TH WEST STREET",
            "listingType": "residential:house:house",
            "address": {},
        }
        t = format_rentals_listing_title(
            node,
            street_line="1500 66TH WEST Street",
            city_name="Vancouver",
            region="BC",
            max_beds=5.0,
        )
        self.assertEqual(
            t,
            "1500 66TH WEST Street house — 1500 66TH WEST STREET, Vancouver BC (5-Bedroom)",
        )

    def test_listing_type_case_insensitive(self) -> None:
        node = {"name": "", "listingType": "residential:room:room", "address": {}}
        t = format_rentals_listing_title(
            node,
            street_line="1 Main Street",
            city_name="Vancouver",
            region="BC",
            max_beds=2.0,
        )
        self.assertIn("room", t.lower())

    def test_fallback_without_listing_type(self) -> None:
        node = {"name": "Some Tower", "listingType": "residential:apartment:apartment", "address": {}}
        t = format_rentals_listing_title(
            node,
            street_line="100 Fake Ave",
            city_name="Vancouver",
            region="BC",
            max_beds=4.0,
        )
        self.assertIn("100 Fake Ave", t)
        self.assertIn("Vancouver BC", t)


if __name__ == "__main__":
    unittest.main()
