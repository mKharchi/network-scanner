import sys
import types
import unittest
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
    calculate_rogue_assessment,
    calculate_rssi_distance,
    calculate_rssi_weight,
    find_closest_location,
    is_locally_administered_mac,
    triangulate_position,
)


class SpatialEngineMathTests(unittest.TestCase):
    def test_locally_administered_mac_detection(self):
        # Locally administered bit set (bit 1 of first byte)
        self.assertTrue(is_locally_administered_mac("02:00:00:00:00:00"))
        self.assertTrue(is_locally_administered_mac("16:22:33:44:55:66"))
        self.assertTrue(is_locally_administered_mac("DA:A1:19:00:00:01"))
        self.assertTrue(is_locally_administered_mac("EE:FF:11:22:33:44"))

        # Globally unique (standard OUI)
        self.assertFalse(is_locally_administered_mac("00:1A:2B:3C:4D:5E"))
        self.assertFalse(is_locally_administered_mac("50:D2:F5:11:22:33"))
        self.assertFalse(is_locally_administered_mac("EC:71:DB:AA:BB:CC"))
        self.assertFalse(is_locally_administered_mac(None))
        self.assertFalse(is_locally_administered_mac("invalid"))

    def test_rssi_distance_and_weighting(self):
        # Signal at 1 meter (-40 dBm)
        d_close = calculate_rssi_distance(-40.0, a=-40.0, n=2.5)
        self.assertAlmostEqual(d_close, 1.0, places=2)

        # Weaker signal (-65 dBm) -> further away
        d_far = calculate_rssi_distance(-65.0, a=-40.0, n=2.5)
        self.assertGreater(d_far, d_close)

        w_close = calculate_rssi_weight(-40.0, a=-40.0, n=2.5)
        w_far = calculate_rssi_weight(-65.0, a=-40.0, n=2.5)
        self.assertGreater(w_close, w_far)

    def test_triangulate_position_empty(self):
        res = triangulate_position([])
        self.assertEqual(res["method"], "NONE")
        self.assertEqual(res["confidence"], 0.0)
        self.assertIsNone(res["x"])

    def test_triangulate_position_single_sensor(self):
        sensor_readings = [{
            "sensor_id": "sensor-1",
            "x": 10.0,
            "y": 20.0,
            "z": 3.0,
            "rssi": -48,
        }]
        res = triangulate_position(sensor_readings)
        self.assertEqual(res["x"], 10.0)
        self.assertEqual(res["y"], 20.0)
        self.assertEqual(res["z"], 3.0)
        self.assertEqual(res["method"], "NEAREST_SENSOR")
        self.assertGreaterEqual(res["confidence"], 0.70)
        self.assertEqual(res["supporting_sensors"], ["sensor-1"])

    def test_triangulate_position_switch_port(self):
        sensor_readings = [
            {"sensor_id": "sensor-1", "x": 10.0, "y": 20.0, "z": 3.0, "rssi": -80},
            {"sensor_id": "switch-1", "x": 15.0, "y": 15.0, "z": 3.0, "switch_port": "Gi0/12"},
        ]
        res = triangulate_position(sensor_readings)
        self.assertEqual(res["x"], 15.0)
        self.assertEqual(res["y"], 15.0)
        self.assertEqual(res["method"], "SWITCH_PORT")
        self.assertEqual(res["confidence"], 0.95)

    def test_triangulate_multilateration_moves_towards_stronger_sensor(self):
        # Sensor A at (0, 0), Sensor B at (10, 0), Sensor C at (5, 10)
        # Device is much closer to Sensor A (-42 dBm) than B (-75 dBm) or C (-75 dBm)
        sensor_readings = [
            {"sensor_id": "A", "x": 0.0, "y": 0.0, "z": 0.0, "rssi": -42},
            {"sensor_id": "B", "x": 10.0, "y": 0.0, "z": 0.0, "rssi": -75},
            {"sensor_id": "C", "x": 5.0, "y": 10.0, "z": 0.0, "rssi": -75},
        ]
        res = triangulate_position(sensor_readings)
        self.assertEqual(res["method"], "MULTI_SENSOR_SMOOTHED")
        self.assertGreaterEqual(res["confidence"], 0.85)
        # Position should be weighted closely to Sensor A (x < 3.0, y < 3.0)
        self.assertLess(res["x"], 3.0)
        self.assertLess(res["y"], 3.0)

    def test_find_closest_location(self):
        locations = [
            {"id": 1, "label": "Seat-1", "location_type": "pc_position", "floor": 1, "x": 10.0, "y": 10.0, "z": 3.0},
            {"id": 2, "label": "Seat-2", "location_type": "pc_position", "floor": 1, "x": 20.0, "y": 20.0, "z": 3.0},
            {"id": 3, "label": "Floor-2-Room-1", "location_type": "formation_room", "floor": 2, "x": 10.0, "y": 10.0, "z": 6.0},
        ]

        closest_fl1 = find_closest_location(10.5, 9.8, 3.0, locations, preferred_floor=1)
        self.assertIsNotNone(closest_fl1)
        self.assertEqual(closest_fl1["id"], 1)

        closest_fl2 = find_closest_location(10.2, 10.1, 6.0, locations, preferred_floor=2)
        self.assertIsNotNone(closest_fl2)
        self.assertEqual(closest_fl2["id"], 3)


class RogueDeviceScoringTests(unittest.TestCase):
    def test_managed_client_has_zero_rogue_score(self):
        device = {"mac_address": "00:11:22:33:44:55", "vendor": "Dell"}
        res = calculate_rogue_assessment(
            device=device,
            location_estimate={"x": 10.0, "y": 10.0, "z": 3.0, "confidence": 0.9},
            location_details={"label": "F1-Seat-1", "is_restricted": False},
            observations=[],
            is_managed_client=True,
        )
        self.assertEqual(res["rogue_score"], 0)
        self.assertFalse(res["is_rogue"])
        self.assertEqual(res["classification"], "MANAGED")
        self.assertEqual(res["risk_level"], "LOW")

    def test_unmanaged_device_scoring_and_restricted_zone(self):
        device = {
            "mac_address": "02:AB:CD:11:22:33",  # Randomized MAC
            "vendor": "Unknown",
            "first_seen": "2026-08-26T10:00:00Z",
            "last_seen": "2026-08-26T10:15:00Z",  # 15 minutes persistent
        }
        observations = [
            {"source_client_id": 1},
            {"source_client_id": 2},
        ]
        # In a restricted formation room
        location_details = {
            "label": "F1-Room-1",
            "zone_name": "Formation Room 1",
            "is_restricted": True,
            "zone_type": "formation_room",
        }

        res = calculate_rogue_assessment(
            device=device,
            location_estimate={"x": 5.0, "y": 5.0, "z": 3.0, "confidence": 0.85},
            location_details=location_details,
            observations=observations,
            is_managed_client=False,
        )

        self.assertTrue(res["is_rogue"])
        self.assertGreaterEqual(res["rogue_score"], 80)
        self.assertEqual(res["risk_level"], "CRITICAL")
        self.assertEqual(res["classification"], "CONFIRMED_ROGUE")

        # Verify reasons are clear and explainable
        reasons_text = " ".join(res["reasons"])
        self.assertIn("randomized", reasons_text.lower())
        self.assertIn("restricted", reasons_text.lower())
        self.assertIn("persistent", reasons_text.lower())


if __name__ == "__main__":
    unittest.main()
