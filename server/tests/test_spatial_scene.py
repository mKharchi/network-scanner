import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components.spatial_engine import (
    get_spatial_replay,
    get_spatial_scene,
    get_spatial_threats,
    get_spatial_topology,
)


class SpatialDigitalTwinSceneTests(unittest.TestCase):
    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor

    def test_get_spatial_scene_generates_valid_schema(self):
        loc_desc = [("id",), ("name",), ("label",), ("location_type",), ("floor",), ("parent_id",), ("x",), ("y",), ("z",), ("width",), ("length",), ("height",), ("is_restricted",), ("zone_type",), ("aisle",), ("table_no",), ("position",)]
        loc_rows = [
            (1, "Training Room 1", "Room-01", "room", 1, None, 10.0, 15.0, 0.0, 12.0, 10.0, 3.0, 0, "training", None, None, None),
            (2, "Restricted Server Zone", "Server-Zone", "zone", 1, 1, 5.0, 5.0, 0.0, 4.0, 4.0, 2.5, 1, "server_room", None, None, None),
        ]

        sensor_desc = [("id",), ("name",), ("sensor_type",), ("location_id",), ("client_id",), ("x",), ("y",), ("z",), ("capabilities",), ("is_active",), ("loc_label",), ("loc_floor",)]
        sensor_rows = [
            ("sensor-1", "Room-1 Sensor", "managed_client", 1, 101, 10.0, 15.0, 2.5, '["arp", "dhcp", "rssi"]', 1, "Room-01", 1),
        ]

        client_desc = [("id",), ("mac",), ("ip",), ("hostname",), ("os_name",), ("os_version",), ("status",), ("is_quarantined",), ("location_id",), ("agent_role",), ("loc_label",), ("loc_x",), ("loc_y",), ("loc_z",), ("loc_floor",), ("loc_restricted",)]
        client_rows = [
            (101, "AA:BB:CC:DD:EE:01", "192.168.1.101", "PC-WORKSTATION-01", "Windows", "11", "online", 0, 1, "agent", "Room-01", 10.0, 15.0, 0.8, 1, 0),
        ]

        dev_desc = [("id",), ("mac_address",), ("ip_address",), ("hostname",), ("vendor",), ("first_seen",), ("last_seen",), ("location_id",), ("est_x",), ("est_y",), ("est_z",), ("est_conf",), ("est_method",), ("supporting_sensor_ids",), ("loc_label",), ("loc_floor",), ("loc_restricted",), ("rogue_score",), ("is_rogue",), ("rogue_class",), ("risk_level",), ("rogue_reasons",)]
        dev_rows = [
            (201, "02:AA:BB:CC:DD:99", "192.168.1.200", "UNKNOWN-DEVICE", "Randomized MAC", datetime(2026, 8, 20, 10, 0, 0), datetime(2026, 8, 20, 10, 15, 0), 2, 5.2, 5.1, 0.8, 0.92, "RSSI_MULTILATERATION", '["sensor-1"]', "Server-Zone", 1, 1, 85, 1, "CONFIRMED_ROGUE", "CRITICAL", '["Restricted zone presence", "Randomized MAC"]'),
        ]

        obs_desc = [("device_id",), ("source_client_id",), ("rssi",), ("switch_port",), ("client_id",)]
        obs_rows = [
            (201, 101, -55, None, 101),
        ]

        def fetchall_side_effect():
            call_count = self.mock_cursor.execute.call_count
            if call_count == 1:
                self.mock_cursor.description = loc_desc
                return loc_rows
            elif call_count == 2:
                self.mock_cursor.description = sensor_desc
                return sensor_rows
            elif call_count == 3:
                self.mock_cursor.description = client_desc
                return client_rows
            elif call_count == 4:
                self.mock_cursor.description = dev_desc
                return dev_rows
            elif call_count == 5:
                self.mock_cursor.description = obs_desc
                return obs_rows
            return []

        self.mock_cursor.fetchall.side_effect = fetchall_side_effect

        scene = get_spatial_scene(conn=self.mock_conn)

        self.assertEqual(scene["version"], 1)
        self.assertIn("timestamp", scene)
        self.assertEqual(len(scene["locations"]), 2)
        self.assertTrue(any(l["name"] == "Training Room 1" for l in scene["locations"]))
        self.assertTrue(any(l["is_restricted"] for l in scene["locations"]))

        self.assertGreaterEqual(len(scene["nodes"]), 5)
        rogue_node = next(n for n in scene["nodes"] if n["id"] == "dev-201")
        self.assertTrue(rogue_node["is_rogue"])
        self.assertEqual(rogue_node["status"], "rogue")
        self.assertEqual(rogue_node["risk"], "critical")
        self.assertAlmostEqual(rogue_node["position"]["x"], 5.2, places=1)

        self.assertEqual(len(scene["threats"]), 1)
        self.assertEqual(scene["threats"][0]["device_id"], 201)
        self.assertEqual(scene["threats"][0]["severity"], "critical")

        self.assertGreaterEqual(len(scene["edges"]), 3)
        wireless_edge = next((e for e in scene["edges"] if e["type"] == "wireless"), None)
        self.assertIsNotNone(wireless_edge)

    def test_get_spatial_topology(self):
        with patch("server_components.spatial_engine.get_spatial_scene") as mock_scene:
            mock_scene.return_value = {
                "nodes": [{"id": "n1"}, {"id": "n2"}],
                "edges": [
                    {"id": "e1", "type": "physical", "risk": "low"},
                    {"id": "e2", "type": "wireless", "risk": "high"},
                ],
            }
            topo = get_spatial_topology(conn=self.mock_conn)
            self.assertEqual(len(topo["nodes"]), 2)
            self.assertEqual(topo["summary"]["physical_links"], 1)
            self.assertEqual(topo["summary"]["wireless_links"], 1)
            self.assertEqual(topo["summary"]["threat_links"], 1)

    def test_get_spatial_threats(self):
        with patch("server_components.spatial_engine.get_spatial_scene") as mock_scene:
            mock_scene.return_value = {
                "threats": [
                    {"id": "threat-1", "device_id": 42, "score": 85, "severity": "critical"}
                ]
            }
            threats = get_spatial_threats(conn=self.mock_conn)
            self.assertEqual(len(threats), 1)
            self.assertEqual(threats[0]["device_id"], 42)

    def test_get_spatial_replay(self):
        with patch("server_components.spatial_engine.list_spatial_events") as mock_events, \
             patch("server_components.spatial_engine.get_spatial_scene") as mock_scene:
            mock_events.return_value = [
                {
                    "id": 1,
                    "device_id": 201,
                    "hostname": "UNKNOWN-DEV",
                    "mac_address": "02:AA:BB:CC:DD:99",
                    "reason": "RSSI trilateration zone shift",
                    "previous_location": {"label": "Room-01", "x": 10.0, "y": 15.0, "z": 0.8},
                    "new_location": {"label": "Server-Zone", "x": 5.0, "y": 5.0, "z": 0.8},
                    "timestamp": "2026-08-20T10:05:00+00:00",
                }
            ]
            mock_scene.return_value = {
                "nodes": [
                    {"id": "dev-201", "position": {"x": 5.0, "y": 5.0, "z": 0.8}}
                ]
            }

            replay = get_spatial_replay(conn=self.mock_conn)
            self.assertEqual(replay["total_frames"], 1)
            self.assertEqual(replay["frames"][0]["trigger_event"]["device_id"], 201)
            self.assertEqual(replay["frames"][0]["trigger_event"]["to_location"], "Server-Zone")


if __name__ == "__main__":
    unittest.main()
