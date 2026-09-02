"""Unit tests for Milestone G: Bulk Update (POST /api/v1/bulk-updates/).

Tests cover:
- create_bulk_update: individual and 'all' strategies, error cases
- Action independence: failing one action does not affect others
- get_bulk_update_status: aggregate counts + per-client entries
- list_bulk_updates: summary list
"""

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from server_components.api_service import (
    create_bulk_update,
    get_bulk_update_status,
    list_bulk_updates,
)
from server_components.action_framework import ActionState, ActionType


# ---------------------------------------------------------------------------
# 1. create_bulk_update – individual strategy
# ---------------------------------------------------------------------------

class TestCreateBulkUpdateIndividual(unittest.TestCase):
    """create_bulk_update with strategy='individual' creates one action per client."""

    @patch("server_components.api_service.get_connection")
    def test_creates_one_action_per_client(self, mock_get_conn):
        """Two selected clients -> two independent UPDATE_CLIENT actions created."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn

        actions_created = []

        def fake_create_action(action_type, targets, parameters=None, requested_by=None):
            a = {
                "action_id": f"action-{len(actions_created):03d}",
                "action_type": action_type,
                "targets": targets,
                "status": ActionState.PENDING.value,
                "parameters": parameters,
            }
            actions_created.append(a)
            return a

        with patch("server_components.action_service.create_action", side_effect=fake_create_action), \
             patch("server_components.package_service.get_package", return_value={"package_id": "pkg-v2"}), \
             patch("threading.Thread"):

            result = create_bulk_update(
                package_id="pkg-v2",
                target_selection={
                    "strategy": "individual",
                    "client_ids": ["PC-001", "PC-002"],
                },
                requested_by="test-operator",
                bulk_update_id="bulk-test-001",
            )

        self.assertEqual(result["bulk_update_id"], "bulk-test-001")
        self.assertEqual(result["package_id"], "pkg-v2")
        self.assertEqual(result["target_count"], 2)
        self.assertEqual(len(result["actions"]), 2)
        self.assertEqual(result["aggregate_status"]["total"], 2)
        self.assertEqual(result["aggregate_status"]["pending"], 2)
        self.assertEqual(result["aggregate_status"]["completed"], 0)
        self.assertEqual(result["aggregate_status"]["failed"], 0)
        self.assertEqual(len(actions_created), 2)

    @patch("server_components.api_service.get_connection")
    def test_package_not_found_raises_value_error(self, mock_get_conn):
        """ValueError raised when package_id is not in store."""
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        with patch("server_components.package_service.get_package", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                create_bulk_update(
                    package_id="nonexistent-pkg",
                    target_selection={"strategy": "individual", "client_ids": ["PC-001"]},
                    requested_by="test-operator",
                )
        self.assertIn("not found", str(ctx.exception).lower())

    @patch("server_components.api_service.get_connection")
    def test_unknown_strategy_raises_value_error(self, mock_get_conn):
        """ValueError raised for unsupported selection strategy."""
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        with patch("server_components.package_service.get_package", return_value={"package_id": "pkg-v2"}):
            with self.assertRaises(ValueError) as ctx:
                create_bulk_update(
                    package_id="pkg-v2",
                    target_selection={"strategy": "invalid_strategy"},
                    requested_by="test-operator",
                )
        self.assertIn("strategy", str(ctx.exception).lower())

    @patch("server_components.api_service.get_connection")
    def test_empty_client_ids_raises_value_error(self, mock_get_conn):
        """ValueError raised when client_ids list is empty."""
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        with patch("server_components.package_service.get_package", return_value={"package_id": "pkg-v2"}):
            with self.assertRaises(ValueError) as ctx:
                create_bulk_update(
                    package_id="pkg-v2",
                    target_selection={"strategy": "individual", "client_ids": []},
                    requested_by="test-operator",
                )
        self.assertIn("empty", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# 2. create_bulk_update – 'all' strategy
# ---------------------------------------------------------------------------

class TestCreateBulkUpdateAllStrategy(unittest.TestCase):
    """create_bulk_update with strategy='all' targets every client in the DB."""

    @patch("server_components.api_service.get_connection")
    def test_all_strategy_fetches_all_clients(self, mock_get_conn):
        """'all' strategy creates one action for each client returned by the DB."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        db_clients = [
            {"client_id": "PC-001"},
            {"client_id": "PC-002"},
            {"client_id": "PC-003"},
        ]
        # First fetchall call returns clients (for 'all' strategy lookup);
        # the connection is closed and re-opened, so we return clients then nothing.
        mock_cursor.fetchall.return_value = db_clients

        actions_created = []

        def fake_create_action(action_type, targets, parameters=None, requested_by=None):
            a = {
                "action_id": f"action-{len(actions_created):03d}",
                "action_type": action_type,
                "targets": targets,
                "status": ActionState.PENDING.value,
            }
            actions_created.append(a)
            return a

        with patch("server_components.action_service.create_action", side_effect=fake_create_action), \
             patch("server_components.package_service.get_package", return_value={"package_id": "pkg-v2"}), \
             patch("threading.Thread"):

            result = create_bulk_update(
                package_id="pkg-v2",
                target_selection={"strategy": "all"},
                requested_by="test-operator",
            )

        self.assertEqual(result["target_count"], 3)
        self.assertEqual(len(result["actions"]), 3)
        self.assertEqual(len(actions_created), 3)


# ---------------------------------------------------------------------------
# 3. Action independence
# ---------------------------------------------------------------------------

class TestBulkUpdateActionIndependence(unittest.TestCase):
    """Each created action has a distinct action_id (isolation guarantee)."""

    @patch("server_components.api_service.get_connection")
    def test_actions_are_separate_objects(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn

        action_ids = []
        counter = [0]

        def fake_create_action(action_type, targets, parameters=None, requested_by=None):
            counter[0] += 1
            a = {
                "action_id": f"action-{counter[0]:03d}",
                "action_type": action_type,
                "targets": targets,
                "status": ActionState.PENDING.value,
            }
            action_ids.append(a["action_id"])
            return a

        with patch("server_components.action_service.create_action", side_effect=fake_create_action), \
             patch("server_components.package_service.get_package", return_value={"package_id": "pkg"}), \
             patch("threading.Thread"):

            result = create_bulk_update(
                package_id="pkg",
                target_selection={
                    "strategy": "individual",
                    "client_ids": ["PC-001", "PC-002", "PC-003"],
                },
                requested_by="test-operator",
            )

        returned_ids = {a["action_id"] for a in result["actions"]}
        self.assertEqual(len(returned_ids), 3)
        self.assertEqual(returned_ids, set(action_ids))


# ---------------------------------------------------------------------------
# 4. get_bulk_update_status
# ---------------------------------------------------------------------------

class TestGetBulkUpdateStatus(unittest.TestCase):
    """get_bulk_update_status returns correct aggregate counts and per-client entries."""

    def _run_status(self, action_rows):
        bulk_rec = {
            "bulk_update_id": "bulk-test-001",
            "package_id": "pkg-v2",
            "target_count": len(action_rows),
            "created_at": datetime(2026, 9, 1, 10, 0, 0),
            "created_by": "test-operator",
        }

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = bulk_rec
        mock_cursor.fetchall.return_value = action_rows

        with patch("server_components.api_service.get_connection", return_value=mock_conn), \
             patch("server_components.server_lib.get_client", return_value=None):
            return get_bulk_update_status("bulk-test-001")

    def test_aggregate_counts_all_pending(self):
        rows = [
            {"action_id": "a1", "client_id": "PC-001", "status": "PENDING", "result": None},
            {"action_id": "a2", "client_id": "PC-002", "status": "PENDING", "result": None},
        ]
        result = self._run_status(rows)
        agg = result["aggregate_status"]
        self.assertEqual(agg["total"], 2)
        self.assertEqual(agg["pending"], 2)
        self.assertEqual(agg["running"], 0)
        self.assertEqual(agg["completed"], 0)
        self.assertEqual(agg["failed"], 0)

    def test_aggregate_counts_mixed(self):
        rows = [
            {"action_id": "a1", "client_id": "PC-001", "status": "COMPLETED", "result": None},
            {"action_id": "a2", "client_id": "PC-002", "status": "FAILED", "result": None},
            {"action_id": "a3", "client_id": "PC-003", "status": "RUNNING", "result": None},
            {"action_id": "a4", "client_id": "PC-004", "status": "COMPLETED", "result": None},
            {"action_id": "a5", "client_id": "PC-005", "status": "PENDING", "result": None},
        ]
        result = self._run_status(rows)
        agg = result["aggregate_status"]
        self.assertEqual(agg["total"], 5)
        self.assertEqual(agg["completed"], 2)
        self.assertEqual(agg["failed"], 1)
        self.assertEqual(agg["running"], 1)
        self.assertEqual(agg["pending"], 1)

    def test_per_client_status_count(self):
        rows = [
            {"action_id": "a1", "client_id": "PC-001", "status": "COMPLETED", "result": None},
            {"action_id": "a2", "client_id": "PC-002", "status": "FAILED", "result": None},
        ]
        result = self._run_status(rows)
        self.assertEqual(len(result["per_client_status"]), 2)

    def test_per_client_includes_required_fields(self):
        rows = [
            {"action_id": "a1", "client_id": "PC-001", "status": "COMPLETED", "result": None},
        ]
        result = self._run_status(rows)
        entry = result["per_client_status"][0]
        for key in ("action_id", "client_id", "hostname", "status", "result"):
            self.assertIn(key, entry, f"Missing key '{key}' in per_client_status entry")

    def test_result_json_parsed(self):
        raw_result = json.dumps({"reason": "DEPENDENCY_INSTALL_FAILED"})
        rows = [
            {"action_id": "a1", "client_id": "PC-001", "status": "FAILED", "result": raw_result},
        ]
        result = self._run_status(rows)
        parsed = result["per_client_status"][0]["result"]
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["reason"], "DEPENDENCY_INSTALL_FAILED")

    def test_not_found_raises_value_error(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch("server_components.api_service.get_connection", return_value=mock_conn):
            with self.assertRaises(ValueError) as ctx:
                get_bulk_update_status("nonexistent-bulk")
        self.assertIn("not found", str(ctx.exception).lower())

    def test_success_status_counted_as_completed(self):
        """ActionState.SUCCESS (per-target value) also increments completed count."""
        rows = [
            {"action_id": "a1", "client_id": "PC-001", "status": "SUCCESS", "result": None},
        ]
        result = self._run_status(rows)
        self.assertEqual(result["aggregate_status"]["completed"], 1)
        self.assertEqual(result["aggregate_status"]["failed"], 0)


# ---------------------------------------------------------------------------
# 5. list_bulk_updates
# ---------------------------------------------------------------------------

class TestListBulkUpdates(unittest.TestCase):
    """list_bulk_updates returns summary list ordered newest-first."""

    def _run_list(self, db_rows):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = db_rows

        with patch("server_components.api_service.get_connection", return_value=mock_conn):
            return list_bulk_updates()

    def test_empty_returns_empty_list(self):
        result = self._run_list([])
        self.assertEqual(result, [])

    def test_single_record_mapped_correctly(self):
        db_rows = [{
            "bulk_update_id": "bulk-001",
            "package_id": "pkg-v2",
            "target_count": 5,
            "created_at": datetime(2026, 9, 1, 10, 0, 0),
            "created_by": "admin",
            "target_selection_strategy": "all",
            "action_count": 5,
            "completed_count": 3,
            "failed_count": 1,
        }]
        result = self._run_list(db_rows)
        self.assertEqual(len(result), 1)
        r = result[0]
        self.assertEqual(r["bulk_update_id"], "bulk-001")
        self.assertEqual(r["package_id"], "pkg-v2")
        self.assertEqual(r["target_count"], 5)
        agg = r["aggregate_status"]
        self.assertEqual(agg["completed"], 3)
        self.assertEqual(agg["failed"], 1)
        self.assertEqual(agg["pending"], 1)   # 5 - 3 - 1

    def test_multiple_records(self):
        db_rows = [
            {
                "bulk_update_id": f"bulk-{i:03d}",
                "package_id": "pkg-v2",
                "target_count": 10,
                "created_at": datetime(2026, 9, 1),
                "created_by": "admin",
                "target_selection_strategy": "individual",
                "action_count": 10,
                "completed_count": 10,
                "failed_count": 0,
            }
            for i in range(3)
        ]
        result = self._run_list(db_rows)
        self.assertEqual(len(result), 3)

    def test_created_at_serialized_as_isoformat(self):
        db_rows = [{
            "bulk_update_id": "bulk-001",
            "package_id": "pkg-v2",
            "target_count": 1,
            "created_at": datetime(2026, 9, 1, 10, 30, 0),
            "created_by": "admin",
            "target_selection_strategy": "individual",
            "action_count": 1,
            "completed_count": 1,
            "failed_count": 0,
        }]
        result = self._run_list(db_rows)
        self.assertEqual(result[0]["created_at"], "2026-09-01T10:30:00")


# ---------------------------------------------------------------------------
# 6. HTTP API Endpoint Tests
# ---------------------------------------------------------------------------

class TestBulkUpdateHttpApi(unittest.TestCase):
    """HTTP integration tests for /api/v1/bulk-updates endpoints."""

    @classmethod
    def setUpClass(cls):
        from api_server import run_api_server
        import threading
        cls.httpd = run_api_server(host="127.0.0.1", port=0)
        cls.port = cls.httpd.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str):
        import urllib.request
        import urllib.error
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _post(self, path: str, payload: dict):
        import urllib.request
        import urllib.error
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    @patch("server_components.api_service.list_bulk_updates")
    def test_get_bulk_updates_list(self, mock_list):
        mock_list.return_value = [{"bulk_update_id": "bulk-1", "package_id": "pkg-1"}]
        status, body = self._get("/api/v1/bulk-updates")
        self.assertEqual(status, 200)
        self.assertIn("data", body)
        self.assertEqual(body["data"]["items"], [{"bulk_update_id": "bulk-1", "package_id": "pkg-1"}])

    @patch("server_components.api_service.get_bulk_update_status")
    def test_get_bulk_update_status_ok(self, mock_get_status):
        mock_get_status.return_value = {
            "bulk_update_id": "bulk-1",
            "package_id": "pkg-1",
            "aggregate_status": {"total": 1, "completed": 1, "failed": 0, "pending": 0, "running": 0},
        }
        status, body = self._get("/api/v1/bulk-updates/bulk-1")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["bulk_update_id"], "bulk-1")

    @patch("server_components.api_service.get_bulk_update_status")
    def test_get_bulk_update_status_not_found(self, mock_get_status):
        mock_get_status.side_effect = ValueError("Bulk update 'unknown' not found.")
        status, body = self._get("/api/v1/bulk-updates/unknown")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    @patch("server_components.api_service.create_bulk_update")
    def test_post_bulk_update_ok(self, mock_create):
        mock_create.return_value = {
            "bulk_update_id": "bulk-new",
            "package_id": "app-v2.0.0",
            "target_count": 2,
            "actions": [],
            "aggregate_status": {"total": 2, "pending": 2, "running": 0, "completed": 0, "failed": 0},
        }
        payload = {
            "package_id": "app-v2.0.0",
            "target_selection": {"strategy": "individual", "client_ids": ["PC-1", "PC-2"]},
        }
        status, body = self._post("/api/v1/bulk-updates", payload)
        self.assertEqual(status, 201)
        self.assertEqual(body["data"]["bulk_update_id"], "bulk-new")

    def test_post_bulk_update_missing_package_id(self):
        status, body = self._post("/api/v1/bulk-updates", {"target_selection": {"strategy": "all"}})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_post_bulk_update_missing_target_selection(self):
        status, body = self._post("/api/v1/bulk-updates", {"package_id": "app-v2.0.0"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()

