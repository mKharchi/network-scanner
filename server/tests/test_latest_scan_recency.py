import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

if "mysql.connector" not in sys.modules:
    try:
        import mysql.connector  # noqa: F401
    except ModuleNotFoundError:
        mysql_module = types.ModuleType("mysql")
        mysql_module.connector = types.ModuleType("mysql.connector")
        sys.modules["mysql"] = mysql_module
        sys.modules["mysql.connector"] = mysql_module.connector

from server_components.api_service import _parse_scan_file  # noqa: E402


class LatestScanRecencyTests(unittest.TestCase):
    def test_parse_scan_file_filters_stale_devices(self):
        now = datetime.now(timezone.utc)
        payload = {
            "completed_at": now.isoformat(),
            "devices": [
                {
                    "mac_address": "AA:BB:CC:DD:EE:01",
                    "ip_address": "192.168.1.10",
                    "hostname": "fresh-host",
                    "last_observed_at": (now - timedelta(minutes=2)).isoformat(),
                },
                {
                    "mac_address": "AA:BB:CC:DD:EE:02",
                    "ip_address": "192.168.1.11",
                    "hostname": "stale-host",
                    "last_observed_at": (now - timedelta(hours=6)).isoformat(),
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            scan_path = Path(handle.name)

        try:
            with patch("server_components.api_service.classify_devices", side_effect=lambda devices: devices):
                parsed = _parse_scan_file(scan_path)
        finally:
            scan_path.unlink(missing_ok=True)

        self.assertIsNotNone(parsed)
        scan = parsed["scan"]
        self.assertEqual(scan["devices_found"], 1)
        self.assertEqual(scan["devices_total_in_snapshot"], 2)
        self.assertEqual(len(scan["devices"]), 1)
        self.assertEqual(scan["devices"][0]["hostname"], "fresh-host")


if __name__ == "__main__":
    unittest.main()
