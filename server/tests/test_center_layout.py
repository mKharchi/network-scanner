"""Tests for the canonical training-center seed geometry."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.center_layout import (  # noqa: E402
    LOCATION_TYPE_PC_POSITION,
    LOCATION_TYPE_STAIRS,
    generate_center_locations,
    layout_counts,
    pc_position_records,
    seed_center_layout,
)
from server_components.physical_layout import build_floor_layout  # noqa: E402


class CenterLayoutSeedTests(unittest.TestCase):
    def setUp(self):
        self.records = generate_center_locations()
        self.counts = layout_counts(self.records)

    def test_creates_exactly_56_pc_positions(self):
        self.assertEqual(self.counts["pc_positions"], 56)
        self.assertEqual(self.counts["pc_positions_by_floor"].get(0, 0), 0)
        self.assertEqual(self.counts["pc_positions_by_floor"][1], 24)
        self.assertEqual(self.counts["pc_positions_by_floor"][2], 32)

    def test_structure_counts(self):
        types = self.counts["type_counts"]
        self.assertEqual(types["floor"], 3)
        self.assertEqual(types["formation_room"], 4)
        self.assertEqual(types["aisle"], 4)
        self.assertEqual(types["table"], 7)
        self.assertEqual(types["stairs"], 1)
        self.assertEqual(types["pc_position"], 56)

    def test_floor_1_aisle_1_has_stairs_instead_of_table_1(self):
        labels = {item["label"] for item in self.records}
        self.assertIn("F1-A1-Stairs", labels)
        self.assertNotIn("F1-A1-T1", labels)
        self.assertFalse(
            any(
                item["location_type"] == LOCATION_TYPE_PC_POSITION
                and item["floor"] == 1
                and item["aisle"] == 1
                and item["table"] == 1
                for item in self.records
            )
        )
        self.assertIn("F1-A1-T2-C1-P1", labels)

    def test_pc_labels_are_unique_and_deterministic(self):
        pc_labels = [item["label"] for item in pc_position_records(self.records)]
        self.assertEqual(len(pc_labels), len(set(pc_labels)))
        self.assertIn("F2-A1-T2-C2-P3", pc_labels)
        self.assertIn("F1-A2-T1-C2-P4", pc_labels)

    def test_each_table_has_two_columns_of_four(self):
        table = [
            item
            for item in pc_position_records(self.records)
            if item["label"].startswith("F2-A1-T1-")
        ]
        self.assertEqual(len(table), 8)
        self.assertEqual({item["column"] for item in table}, {1, 2})
        self.assertEqual({item["position"] for item in table}, {1, 2, 3, 4})

    def test_layout_hides_stairs_as_a_non_seat_slot(self):
        layout = build_floor_layout(self.records, 1)
        aisle_1 = next(aisle for aisle in layout["aisles"] if aisle["aisle"] == 1)
        kinds = [table["kind"] for table in aisle_1["tables"]]
        self.assertEqual(kinds, ["stairs", "table"])
        self.assertEqual(aisle_1["tables"][0]["label"], "F1-A1-Stairs")
        self.assertEqual(aisle_1["tables"][1]["table"], 2)
        self.assertEqual(len(aisle_1["tables"][1]["columns"]), 2)
        self.assertEqual(len(aisle_1["tables"][1]["columns"][0]["stations"]), 4)

    def test_floor_zero_has_no_visual_stations(self):
        layout = build_floor_layout(self.records, 0)
        self.assertEqual(layout["rooms"], [])
        self.assertEqual(layout["aisles"], [])
        self.assertFalse(layout["shows_clients"])

    def test_floor_two_has_four_tables(self):
        layout = build_floor_layout(self.records, 2)
        tables = [table for aisle in layout["aisles"] for table in aisle["tables"]]
        self.assertEqual(len(tables), 4)
        self.assertTrue(all(table["kind"] == "table" for table in tables))
        stations = [
            station
            for table in tables
            for column in table["columns"]
            for station in column["stations"]
        ]
        self.assertEqual(len(stations), 32)

    def test_seed_skips_existing_labels(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        conn = MagicMock()
        conn.cursor.return_value = cursor

        result = seed_center_layout(conn)

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["pc_positions"], 56)
        conn.commit.assert_called_once()

    def test_seed_inserts_missing_records(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value = cursor

        result = seed_center_layout(conn)

        self.assertEqual(result["created"], layout_counts()["total_records"])
        inserts = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if call.args and "INSERT INTO locations" in call.args[0]
        ]
        self.assertEqual(len(inserts), result["created"])
