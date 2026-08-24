"""Unit tests for centralized physical-neighbor classification."""

import sys
import unittest
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.physical_neighbors import (  # noqa: E402
    NEIGHBORING_TABLE,
    SAME_ROW,
    SAME_TABLE,
    SAME_ZONE,
    classify_physical_neighbor,
    neighbor_sort_key,
)


ORIGIN = {
    "floor": 1,
    "zone_type": "training",
    "zone_name": None,
    "aisle": 1,
    "table_no": 2,
    "row_no": 1,
    "position": 3,
}


class PhysicalNeighborClassificationTests(unittest.TestCase):
    def test_same_row_adjacent_positions(self):
        left = {**ORIGIN, "position": 2}
        right = {**ORIGIN, "position": 4}

        self.assertEqual(classify_physical_neighbor(ORIGIN, left), (SAME_ROW, 1))
        self.assertEqual(classify_physical_neighbor(ORIGIN, right), (SAME_ROW, 1))

    def test_same_table_other_row_same_position(self):
        other_row = {**ORIGIN, "row_no": 2}

        self.assertEqual(classify_physical_neighbor(ORIGIN, other_row), (SAME_TABLE, 1))

    def test_neighboring_table_same_row_and_position(self):
        other_table = {**ORIGIN, "table_no": 1}

        self.assertEqual(classify_physical_neighbor(ORIGIN, other_table), (NEIGHBORING_TABLE, 1))

    def test_farther_table_is_not_a_neighbor(self):
        far_table = {**ORIGIN, "table_no": 4}

        self.assertIsNone(classify_physical_neighbor(ORIGIN, far_table))

    def test_different_aisle_is_not_a_neighbor(self):
        other_aisle = {**ORIGIN, "aisle": 2}

        self.assertIsNone(classify_physical_neighbor(ORIGIN, other_aisle))

    def test_different_floor_is_not_a_neighbor(self):
        other_floor = {**ORIGIN, "floor": 2}

        self.assertIsNone(classify_physical_neighbor(ORIGIN, other_floor))

    def test_conference_room_shares_zone_neighbors(self):
        room = {
            "floor": 1,
            "zone_type": "conference_room",
            "zone_name": "Formation Room 1",
            "aisle": None,
            "table": None,
            "row": None,
            "position": None,
        }
        other = {**room}

        self.assertEqual(classify_physical_neighbor(room, other), (SAME_ZONE, 1))

    def test_sort_orders_same_row_before_other_relationships(self):
        items = [
            {"client_id": "c-table", "relationship": SAME_TABLE, "distance": 1},
            {"client_id": "c-row-far", "relationship": SAME_ROW, "distance": 2},
            {"client_id": "c-row-near", "relationship": SAME_ROW, "distance": 1},
        ]

        ordered = sorted(items, key=neighbor_sort_key)

        self.assertEqual(
            [item["client_id"] for item in ordered],
            ["c-row-near", "c-row-far", "c-table"],
        )


if __name__ == "__main__":
    unittest.main()
