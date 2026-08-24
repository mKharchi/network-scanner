"""Tests for server-derived center floor layout grouping."""

import sys
import unittest
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.physical_layout import available_floors, build_floor_layout  # noqa: E402


def loc(**overrides):
    item = {
        "id": 1,
        "floor": 1,
        "zone_type": "training",
        "zone_name": None,
        "aisle": 1,
        "table": 1,
        "row": 1,
        "position": 1,
        "label": "F1-A1-T1-R1-P1",
        "client_id": "client-a",
        "client_state": "ONLINE",
    }
    item.update(overrides)
    return item


class PhysicalLayoutTests(unittest.TestCase):
    def test_groups_aisles_tables_rows_and_rooms(self):
        locations = [
            loc(id=1, aisle=2, table=1, row=2, position=4, label="A2-T1-R2-P4", client_id="c-far"),
            loc(id=2, aisle=1, table=1, row=1, position=2, label="A1-T1-R1-P2", client_id="c-p2"),
            loc(id=3, aisle=1, table=1, row=1, position=1, label="A1-T1-R1-P1", client_id="c-p1"),
            loc(
                id=4,
                zone_type="conference_room",
                zone_name="Formation Room 1",
                aisle=None,
                table=None,
                row=None,
                position=None,
                label="F1-RM1",
                client_id=None,
                client_state=None,
            ),
        ]

        layout = build_floor_layout(locations, 1)

        self.assertTrue(layout["shows_clients"])
        self.assertEqual(layout["rooms"][0]["label"], "F1-RM1")
        self.assertEqual([aisle["aisle"] for aisle in layout["aisles"]], [1, 2])
        first_row = layout["aisles"][0]["tables"][0]["rows"][0]
        self.assertEqual([station["position"] for station in first_row["stations"]], [1, 2])

    def test_floor_zero_hides_assigned_clients(self):
        locations = [
            loc(id=9, floor=0, label="F0-A1-T1-R1-P1", client_id="should-hide", client_state="ONLINE"),
        ]

        layout = build_floor_layout(locations, 0)

        self.assertFalse(layout["shows_clients"])
        station = layout["aisles"][0]["tables"][0]["rows"][0]["stations"][0]
        self.assertNotIn("client_id", station)
        self.assertNotIn("health", station)
        self.assertNotIn("health_status", station)

    def test_available_floors_always_includes_zero(self):
        self.assertEqual(available_floors([loc(floor=1), loc(floor=2)]), [0, 1, 2])

    def test_floor_two_is_independent_of_floor_one(self):
        locations = [
            loc(id=1, floor=1, label="F1-A1-T1-R1-P1"),
            loc(id=2, floor=2, aisle=2, table=3, row=1, position=4, label="F2-A2-T3-R1-P4", client_id="c-f2"),
        ]

        layout = build_floor_layout(locations, 2)

        self.assertEqual(layout["floor"], 2)
        self.assertTrue(layout["shows_clients"])
        self.assertEqual(layout["aisles"][0]["aisle"], 2)
        self.assertEqual(layout["aisles"][0]["tables"][0]["table"], 3)
        station = layout["aisles"][0]["tables"][0]["rows"][0]["stations"][0]
        self.assertEqual(station["label"], "F2-A2-T3-R1-P4")
        self.assertEqual(station["client_id"], "c-f2")

    def test_empty_seats_remain_visible_without_a_client(self):
        locations = [loc(id=3, client_id=None, client_state=None, label="F1-A1-T1-R1-P3")]

        station = build_floor_layout(locations, 1)["aisles"][0]["tables"][0]["rows"][0]["stations"][0]

        self.assertIsNone(station.get("client_id"))
        self.assertEqual(station["position"], 1)

    def test_health_colors_travel_with_the_station(self):
        locations = [
            loc(
                id=1,
                client_id="pc-critical",
                client_state="ONLINE",
                health={"status": "critical", "cpu_percent": 95.0},
                health_status="critical",
            ),
            loc(id=2, position=2, label="offline", client_id="pc-off", client_state="OFFLINE", health_status="offline"),
            loc(id=3, position=3, label="isolated", client_id="pc-iso", client_state="ISOLATED", health_status="isolated"),
        ]

        stations = build_floor_layout(locations, 1)["aisles"][0]["tables"][0]["rows"][0]["stations"]
        by_id = {station["client_id"]: station["health_status"] for station in stations}

        self.assertEqual(by_id["pc-critical"], "critical")
        self.assertEqual(by_id["pc-off"], "offline")
        self.assertEqual(by_id["pc-iso"], "isolated")


if __name__ == "__main__":
    unittest.main()
