"""Unit tests for workstation health classification."""

import sys
import unittest
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.client_health import (  # noqa: E402
    classify_station_health,
    extract_health_metrics,
    record_client_health,
)


class ClientHealthTests(unittest.TestCase):
    def test_empty_and_isolated_and_offline_win_over_metrics(self):
        self.assertEqual(classify_station_health(client_id=None, connection_state="ONLINE", cpu_percent=99), "empty")
        self.assertEqual(
            classify_station_health(client_id="pc-1", connection_state="ISOLATED", cpu_percent=10),
            "isolated",
        )
        self.assertEqual(
            classify_station_health(client_id="pc-1", connection_state="OFFLINE", cpu_percent=99),
            "offline",
        )

    def test_online_metrics_and_alerts(self):
        self.assertEqual(
            classify_station_health(client_id="pc-1", connection_state="ONLINE", cpu_percent=12, memory_percent=20),
            "healthy",
        )
        self.assertEqual(
            classify_station_health(client_id="pc-1", connection_state="ONLINE", cpu_percent=85),
            "warning",
        )
        self.assertEqual(
            classify_station_health(client_id="pc-1", connection_state="ONLINE", disk_percent=93),
            "critical",
        )
        self.assertEqual(
            classify_station_health(client_id="pc-1", connection_state="ONLINE", cpu_percent=10, open_alert_severity="MEDIUM"),
            "warning",
        )
        self.assertEqual(
            classify_station_health(client_id="pc-1", connection_state="ONLINE", cpu_percent=10, open_alert_severity="HIGH"),
            "critical",
        )

    def test_extract_health_metrics_from_nested_payload(self):
        metrics = extract_health_metrics({"status": "ok", "health": {"cpu_percent": 12.5, "memory_percent": 34.0, "disk_percent": 45.0}})
        self.assertEqual(metrics["cpu_percent"], 12.5)
        self.assertEqual(metrics["memory_percent"], 34.0)
        self.assertEqual(metrics["disk_percent"], 45.0)

    def test_record_client_health_persists_extracted_metrics(self):
        from unittest.mock import MagicMock, patch

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 1

        with patch("database.get_connection", return_value=mock_conn):
            stored = record_client_health(
                "pc-1",
                {"status": "ok", "health": {"cpu_percent": 12.5, "memory_percent": 34.0, "disk_percent": 45.0}},
            )

        self.assertTrue(stored)
        args = mock_cursor.execute.call_args[0]
        self.assertIn("health_cpu_percent", args[0])
        self.assertEqual(args[1][:3], (12.5, 34.0, 45.0))
        self.assertEqual(args[1][3], "pc-1")


if __name__ == "__main__":
    unittest.main()
