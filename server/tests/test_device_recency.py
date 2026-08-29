import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.device_recency import (  # noqa: E402
    active_cutoff,
    filter_active_devices,
    is_client_record_active,
    is_device_record_active,
    is_timestamp_active,
)


class DeviceRecencyTests(unittest.TestCase):
    def test_is_timestamp_active_respects_cutoff(self):
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        cutoff = active_cutoff(now=now, max_age_seconds=1800)
        recent = now - timedelta(minutes=10)
        stale = now - timedelta(hours=5)
        self.assertTrue(is_timestamp_active(recent, cutoff=cutoff))
        self.assertFalse(is_timestamp_active(stale, cutoff=cutoff))

    def test_filter_active_devices_returns_only_recent_rows(self):
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        devices = [
            {"mac_address": "AA:BB:CC:DD:EE:01", "last_observed_at": (now - timedelta(minutes=5)).isoformat()},
            {"mac_address": "AA:BB:CC:DD:EE:02", "last_observed_at": (now - timedelta(hours=6)).isoformat()},
        ]
        active, cutoff, window = filter_active_devices(devices, max_age_seconds=1800, now=now)
        self.assertEqual(window, 1800)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["mac_address"], "AA:BB:CC:DD:EE:01")
        self.assertLess(cutoff, now)

    def test_is_client_record_active_uses_device_or_health_timestamps(self):
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        cutoff = active_cutoff(now=now, max_age_seconds=1800)
        self.assertTrue(
            is_client_record_active(
                {"device_last_seen": now - timedelta(minutes=2)},
                cutoff=cutoff,
            )
        )
        self.assertTrue(
            is_client_record_active(
                {"health_updated_at": now - timedelta(minutes=15)},
                cutoff=cutoff,
            )
        )
        self.assertFalse(
            is_client_record_active(
                {"updated_at": now - timedelta(days=2)},
                cutoff=cutoff,
            )
        )

    def test_is_device_record_active_checks_last_seen(self):
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        cutoff = active_cutoff(now=now, max_age_seconds=900)
        self.assertTrue(
            is_device_record_active(
                {"last_seen": now - timedelta(minutes=1)},
                cutoff=cutoff,
            )
        )
        self.assertFalse(
            is_device_record_active(
                {"last_seen": now - timedelta(hours=2)},
                cutoff=cutoff,
            )
        )


if __name__ == "__main__":
    unittest.main()
