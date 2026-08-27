"""Tests for location CRUD, assignment, uniqueness, and history."""

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

from server_components import api_service  # noqa: E402


SEAT = {
    "id": 4,
    "floor": 1,
    "zone_type": "training",
    "zone_name": None,
    "aisle": 1,
    "table_no": 1,
    "row_no": 1,
    "position": 1,
    "label": "F1-A1-T1-R1-P1",
}


def _connection(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class LocationAssignmentTests(unittest.TestCase):
    def test_create_location_requires_floor_zone_and_label(self):
        with self.assertRaises(ValueError):
            api_service.create_location({"floor": 1, "zone_type": "training"})

    @patch("server_components.api_service.get_location")
    @patch("server_components.api_service.get_connection")
    def test_create_location_inserts_physical_hierarchy(self, get_connection, get_location):
        cursor = MagicMock()
        cursor.lastrowid = 4
        get_connection.return_value = _connection(cursor)
        get_location.return_value = {**SEAT, "table": 1, "row": 1}

        created = api_service.create_location({
            "floor": 1,
            "zone_type": "training",
            "label": "F1-A1-T1-R1-P1",
            "aisle": 1,
            "table": 1,
            "row": 1,
            "position": 1,
        })

        sql, params = cursor.execute.call_args[0]
        self.assertIn("INSERT INTO locations", sql)
        self.assertEqual(params, (1, "training", None, 1, 1, 1, 1, "F1-A1-T1-R1-P1", "pc_position"))
        self.assertEqual(created["label"], "F1-A1-T1-R1-P1")

    @patch("server_components.api_service.get_connection")
    def test_create_location_rejects_duplicate_physical_position(self, get_connection):
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("Duplicate entry for key 'uq_location_position'")
        conn = _connection(cursor)
        get_connection.return_value = conn

        with self.assertRaises(ValueError) as raised:
            api_service.create_location({
                "floor": 1,
                "zone_type": "training",
                "label": "F1-A1-T1-R1-P1",
                "aisle": 1,
                "table": 1,
                "row": 1,
                "position": 1,
            })

        self.assertIn("already exists", str(raised.exception))
        conn.rollback.assert_called_once()

    @patch("server_components.api_service.get_connection")
    def test_assign_location_to_unassigned_client(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"id": 8, "client_id": "client-a", "location_id": None},
            SEAT,
            None,
        ]
        get_connection.return_value = _connection(cursor)

        assigned = api_service.assign_client_location("client-a", 4, assigned_by="admin")

        self.assertEqual(assigned["id"], 4)
        self.assertEqual(assigned["client_id"], "client-a")
        self.assertEqual(assigned["label"], "F1-A1-T1-R1-P1")
        self.assertEqual(assigned["assignment"]["method"], "MANUAL")
        self.assertEqual(assigned["assignment"]["status"], "ASSIGNED")
        self.assertTrue(assigned["assignment"]["verified"])
        self.assertEqual(assigned["assignment"]["source"], "administrator")
        self.assertEqual(assigned["assignment"]["assigned_by"], "admin")
        updates = [sql for sql, _params in (call.args for call in cursor.execute.call_args_list)]
        self.assertTrue(any("UPDATE clients" in sql and "location_assignment_method" in sql for sql in updates))
        self.assertTrue(any("INSERT INTO client_location_history" in sql for sql in updates))
        history_insert = next(
            params for sql, params in (call.args for call in cursor.execute.call_args_list)
            if "INSERT INTO client_location_history" in sql
        )
        self.assertEqual(history_insert[3], "MANUAL")
        self.assertEqual(history_insert[4], "ASSIGNED")
        self.assertTrue(history_insert[6])

    @patch("server_components.api_service.get_connection")
    def test_assign_location_stores_auto_confidence_and_evidence(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"id": 8, "client_id": "client-a", "location_id": None},
            SEAT,
            None,
        ]
        get_connection.return_value = _connection(cursor)

        assigned = api_service.assign_client_location(
            "client-a",
            4,
            assigned_by="localization",
            method="AUTO",
            status="ASSIGNED",
            confidence=0.91,
            verified=False,
            evidence=["sensor_match", "network_observation"],
        )

        self.assertEqual(assigned["assignment"]["method"], "AUTO")
        self.assertEqual(assigned["assignment"]["confidence"], 0.91)
        self.assertFalse(assigned["assignment"]["verified"])
        self.assertEqual(assigned["assignment"]["source"], "localization_engine")
        self.assertEqual(
            assigned["assignment"]["evidence"],
            ["sensor_match", "network_observation"],
        )
        client_update = next(
            params for sql, params in (call.args for call in cursor.execute.call_args_list)
            if "UPDATE clients" in sql and "location_assignment_method" in sql
        )
        self.assertEqual(client_update[1], "AUTO")
        self.assertEqual(client_update[2], "ASSIGNED")
        self.assertEqual(client_update[3], 0.91)
        self.assertFalse(client_update[4])

    @patch("server_components.api_service.get_connection")
    def test_change_location_closes_previous_history_row(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"id": 8, "client_id": "client-a", "location_id": 4},
            {**SEAT, "id": 5, "label": "F1-A1-T1-R1-P2", "position": 2},
            None,
        ]
        get_connection.return_value = _connection(cursor)

        assigned = api_service.assign_client_location("client-a", 5, assigned_by="admin")

        self.assertEqual(assigned["id"], 5)
        sql_statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("unassigned_at" in sql for sql in sql_statements))
        self.assertTrue(any("INSERT INTO client_location_history" in sql for sql in sql_statements))

    @patch("server_components.api_service.get_connection")
    def test_occupied_location_is_rejected_with_hostname(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"id": 9, "client_id": "client-b", "location_id": None},
            SEAT,
            {"client_id": "client-a", "hostname": "DESKTOP-ABC"},
        ]
        get_connection.return_value = _connection(cursor)

        with self.assertRaises(ValueError) as raised:
            api_service.assign_client_location("client-b", 4)

        self.assertEqual(str(raised.exception), "This physical position is already assigned to DESKTOP-ABC.")

    @patch("server_components.api_service.get_connection")
    def test_unknown_location_is_rejected(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"id": 8, "client_id": "client-a", "location_id": None},
            None,
        ]
        get_connection.return_value = _connection(cursor)

        with self.assertRaises(ValueError) as raised:
            api_service.assign_client_location("client-a", 99)

        self.assertIn("not found", str(raised.exception))

    @patch("server_components.api_service.get_connection")
    def test_stairs_cannot_be_assigned(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"id": 8, "client_id": "client-a", "location_id": None},
            {
                "id": 99,
                "label": "F1-A1-Stairs",
                "location_type": "stairs",
                "floor": 1,
                "zone_type": "training",
                "zone_name": None,
                "aisle": 1,
                "table_no": 1,
                "row_no": None,
                "position": None,
            },
        ]
        get_connection.return_value = _connection(cursor)

        with self.assertRaises(ValueError) as raised:
            api_service.assign_client_location("client-a", 99)

        self.assertIn("not an assignable PC position", str(raised.exception))

    @patch("server_components.api_service.get_connection")
    def test_get_current_location_returns_assigned_seat(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.return_value = {**SEAT, "client_id": "client-a"}
        get_connection.return_value = _connection(cursor)

        location = api_service.get_client_location("client-a")

        self.assertEqual(location["label"], "F1-A1-T1-R1-P1")
        self.assertEqual(location["table"], 1)
        self.assertEqual(location["row"], 1)
        self.assertEqual(location["column"], 1)

    @patch("server_components.api_service.get_connection")
    def test_unassigned_client_has_no_current_location(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": None, "client_id": "client-a"}
        get_connection.return_value = _connection(cursor)

        self.assertIsNone(api_service.get_client_location("client-a"))

    @patch("server_components.api_service.get_connection")
    def test_location_history_returns_assignment_window(self, get_connection):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "id": 1,
                "assigned_at": "2026-08-24T10:00:00",
                "unassigned_at": None,
                "assigned_by": "admin",
                "assignment_method": "MANUAL",
                "assignment_status": "ASSIGNED",
                "confidence": None,
                "verified": True,
                "source": "administrator",
                "evidence": None,
                "location_id": 4,
                "floor": 1,
                "zone_type": "training",
                "zone_name": None,
                "aisle": 1,
                "table_no": 1,
                "row_no": 1,
                "position": 1,
                "label": "F1-A1-T1-R1-P1",
            }
        ]
        get_connection.return_value = _connection(cursor)

        history = api_service.get_client_location_history("client-a")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["assigned_by"], "admin")
        self.assertIsNone(history[0]["unassigned_at"])
        self.assertEqual(history[0]["location"]["label"], "F1-A1-T1-R1-P1")
        self.assertEqual(history[0]["assignment"]["method"], "MANUAL")
        self.assertTrue(history[0]["assignment"]["verified"])


    @patch("server_components.api_service.list_clients")
    def test_list_unassigned_clients_adds_reason(self, list_clients):
        list_clients.return_value = [
            {
                "id": "client-a",
                "hostname": "PC-07",
                "location": None,
                "location_assignment": {
                    "method": "AUTO",
                    "status": "PENDING",
                    "failure_reason": "low_confidence",
                    "confidence": 0.42,
                },
            }
        ]

        queue = api_service.list_unassigned_clients()

        list_clients.assert_called_once_with(location_filter="unassigned", limit=100)
        self.assertEqual(queue[0]["unassigned_reason"], "low_confidence")
        self.assertEqual(queue[0]["localization_confidence"], 0.42)


class PhysicalNeighborLookupTests(unittest.TestCase):
    @patch("server_components.api_service.get_connection")
    def test_neighbors_exclude_empty_and_far_positions(self, get_connection):
        origin = {
            "floor": 1,
            "zone_type": "training",
            "zone_name": None,
            "aisle": 1,
            "table_no": 2,
            "row_no": 1,
            "position": 3,
        }
        same_row = {
            "client_id": "pc-left",
            "hostname": "PC-LEFT",
            "ip": "10.0.0.2",
            "mac": "AA-BB-CC-DD-EE-01",
            "location_id": 2,
            "floor": 1,
            "zone_type": "training",
            "zone_name": None,
            "aisle": 1,
            "table_no": 2,
            "row_no": 1,
            "position": 2,
            "label": "F1-A1-T2-R1-P2",
        }
        far_table = {
            **same_row,
            "client_id": "pc-far",
            "hostname": "PC-FAR",
            "mac": "AA-BB-CC-DD-EE-09",
            "table_no": 4,
            "position": 3,
            "label": "F1-A1-T4-R1-P3",
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = origin
        cursor.fetchall.return_value = [same_row, far_table]
        get_connection.return_value = _connection(cursor)

        neighbors = api_service.get_physical_neighbors("pc-origin")

        self.assertEqual([item["client_id"] for item in neighbors], ["pc-left"])
        self.assertEqual(neighbors[0]["relationship"], "same_row")
        self.assertEqual(neighbors[0]["distance"], 1)


if __name__ == "__main__":
    unittest.main()
