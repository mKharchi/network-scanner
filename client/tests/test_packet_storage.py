"""Unit tests for packet_storage module."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add client/app to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from packet_storage import DailyPacketStorage


class TestDailyPacketStorage(unittest.TestCase):
    """Test buffered daily JSON storage and crash safety."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_packet_storage_")
        self.storage_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_and_explicit_flush(self):
        storage = DailyPacketStorage(
            storage_dir=self.storage_dir,
            observer_client_id="client-test-1",
            flush_threshold=100,
        )

        obs = {
            "timestamp": "2026-09-02T10:00:00.000Z",
            "protocol": "TCP",
            "src_ip": "192.168.1.10",
            "dst_ip": "142.250.185.14",
            "src_port": 50000,
            "dst_port": 443,
        }
        storage.record_observation(obs)

        # Before flush, file not yet written (threshold is 100)
        file_path = self.storage_dir / "2026-09-02.json"
        self.assertFalse(file_path.exists())

        flushed = storage.flush()
        self.assertEqual(flushed, 1)
        self.assertTrue(file_path.exists())

        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["date"], "2026-09-02")
        self.assertEqual(data["observer_client_id"], "client-test-1")
        self.assertEqual(data["packet_count"], 1)
        self.assertEqual(len(data["packets"]), 1)
        self.assertEqual(data["packets"][0]["protocol"], "TCP")

        # Check stats
        stats = storage.stats
        self.assertEqual(stats["total_observed"], 1)
        self.assertEqual(stats["total_stored"], 1)
        self.assertEqual(stats["tcp_count"], 1)

    def test_automatic_flush_on_threshold(self):
        storage = DailyPacketStorage(
            storage_dir=self.storage_dir,
            observer_client_id="client-test-1",
            flush_threshold=3,
        )

        for i in range(3):
            storage.record_observation({
                "timestamp": "2026-09-02T10:00:00.000Z",
                "protocol": "UDP",
                "seq": i,
            })

        # Threshold of 3 reached, auto-flush should have occurred
        file_path = self.storage_dir / "2026-09-02.json"
        self.assertTrue(file_path.exists())

        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["packet_count"], 3)
        self.assertEqual(len(data["packets"]), 3)

    def test_append_across_restart(self):
        # Session 1: record and flush
        storage1 = DailyPacketStorage(
            storage_dir=self.storage_dir,
            observer_client_id="client-test-1",
        )
        storage1.record_observation({
            "timestamp": "2026-09-02T10:00:00.000Z",
            "protocol": "TCP",
        })
        storage1.close()

        # Session 2: re-open on same directory
        storage2 = DailyPacketStorage(
            storage_dir=self.storage_dir,
            observer_client_id="client-test-1",
        )
        storage2.record_observation({
            "timestamp": "2026-09-02T10:05:00.000Z",
            "protocol": "DHCP",
        })
        storage2.close()

        file_path = self.storage_dir / "2026-09-02.json"
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["packet_count"], 2)
        self.assertEqual(len(data["packets"]), 2)
        self.assertEqual(data["packets"][0]["protocol"], "TCP")
        self.assertEqual(data["packets"][1]["protocol"], "DHCP")

    def test_date_rotation(self):
        storage = DailyPacketStorage(
            storage_dir=self.storage_dir,
            observer_client_id="client-test-1",
            flush_threshold=100,
        )

        # Day 1 observation
        storage.record_observation({
            "timestamp": "2026-09-02T23:59:59.000Z",
            "protocol": "TCP",
        })

        # Day 2 observation (triggers rotation flush for day 1)
        storage.record_observation({
            "timestamp": "2026-09-03T00:00:01.000Z",
            "protocol": "UDP",
        })
        storage.close()

        file_day1 = self.storage_dir / "2026-09-02.json"
        file_day2 = self.storage_dir / "2026-09-03.json"

        self.assertTrue(file_day1.exists())
        self.assertTrue(file_day2.exists())

        with file_day1.open("r", encoding="utf-8") as f:
            d1 = json.load(f)
        with file_day2.open("r", encoding="utf-8") as f:
            d2 = json.load(f)

        self.assertEqual(d1["packet_count"], 1)
        self.assertEqual(d1["packets"][0]["protocol"], "TCP")

        self.assertEqual(d2["packet_count"], 1)
        self.assertEqual(d2["packets"][0]["protocol"], "UDP")


if __name__ == "__main__":
    unittest.main()
