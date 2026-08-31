"""Focused tests for Floor 1 elevation and DHCP-retention map filtering."""

import sys
import unittest
from datetime import datetime
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components import api_service  # noqa: E402
from server_components.floor1_spatial import (  # noqa: E402
    FLOOR1_ELEVATION_METERS,
    FLOOR1_ELEVATION_TOLERANCE_METERS,
    device_position_payload,
    is_floor1_elevation,
)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.params = ()

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_instance = _Cursor(rows)
        self.closed = False

    def cursor(self, dictionary=True):
        self.dictionary = dictionary
        return self.cursor_instance

    def close(self):
        self.closed = True


class Floor1SpatialMapTests(unittest.TestCase):
    def test_floor1_elevation_requires_tight_z_match(self):
        self.assertTrue(is_floor1_elevation(FLOOR1_ELEVATION_METERS))
        self.assertTrue(is_floor1_elevation(FLOOR1_ELEVATION_METERS + FLOOR1_ELEVATION_TOLERANCE_METERS))
        self.assertFalse(is_floor1_elevation(FLOOR1_ELEVATION_METERS + FLOOR1_ELEVATION_TOLERANCE_METERS + 0.01))
        self.assertFalse(is_floor1_elevation(None))

    def test_device_payload_exposes_elevation_and_dhcp_activity(self):
        payload = device_position_payload(
            {
                "device_id": 8,
                "floor": 1,
                "aisle": 2,
                "table_no": 2,
                "row_no": 1,
                "position": 2,
                "confidence": 0.8,
                "estimate_z": 3.1,
                "elevation_delta_meters": 0.1,
                "activity_source": "dhcp",
                "last_dhcp_observed_at": datetime(2026, 8, 30, 12, 0),
            }
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["floor"], 1)
        self.assertEqual(payload["activity_source"], "dhcp")
        self.assertEqual(payload["estimate_z"], 3.1)
        self.assertEqual(payload["elevation_delta_meters"], 0.1)

    def test_map_query_requires_elevation_and_dhcp_can_retain_position(self):
        connection = _Connection([])
        original_connection = api_service.get_connection
        original_locations = api_service.list_locations
        api_service.get_connection = lambda: connection
        api_service.list_locations = lambda: []
        try:
            result = api_service.get_floor1_spatial_map()
        finally:
            api_service.get_connection = original_connection
            api_service.list_locations = original_locations

        query = connection.cursor_instance.query
        params = connection.cursor_instance.params
        self.assertIn("e.z IS NOT NULL", query)
        self.assertIn("ABS(e.z - %s) <= %s", query)
        self.assertIn("o.source_type = 'CLIENT_DHCP'", query)
        self.assertIn("GREATEST(o.observed_at, o.received_at) >= %s", query)
        self.assertIn(FLOOR1_ELEVATION_METERS, params)
        self.assertIn(FLOOR1_ELEVATION_TOLERANCE_METERS, params)
        self.assertTrue(result["meta"]["dhcp_activity_retains_existing_position"])
        self.assertEqual(result["meta"]["elevation_gate"]["tolerance_meters"], FLOOR1_ELEVATION_TOLERANCE_METERS)

    def test_floor0_and_floor2_spatial_map_configurations(self):
        connection = _Connection([])
        original_connection = api_service.get_connection
        original_locations = api_service.list_locations
        api_service.get_connection = lambda: connection
        api_service.list_locations = lambda: []
        try:
            res0 = api_service.get_floor_spatial_map(0)
            res2 = api_service.get_floor_spatial_map(2)
        finally:
            api_service.get_connection = original_connection
            api_service.list_locations = original_locations

        self.assertEqual(res0["floor"], 0)
        self.assertEqual(res0["geometry"]["rooms"], [])
        self.assertEqual(res0["geometry"]["tables"], [])
        self.assertEqual(res0["references"], [])

        self.assertEqual(res2["floor"], 2)
        self.assertEqual(len(res2["geometry"]["rooms"]), 2)
        self.assertEqual(res2["geometry"]["tables"], [])
        self.assertEqual(res2["references"], [])


if __name__ == "__main__":
    unittest.main()
