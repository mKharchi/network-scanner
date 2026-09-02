"""Unit tests for packet_observer module."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add client/app to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from packet_observer import PacketObserver
from packet_storage import DailyPacketStorage


class TestPacketObserver(unittest.TestCase):
    """Test packet observer lifecycle, packet forwarding, and error boundaries."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_packet_obs_")
        self.storage_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_start_and_stop_lifecycle(self):
        storage = DailyPacketStorage(storage_dir=self.storage_dir)

        with patch("scapy.all.sniff") as mock_sniff:
            # Let sniff just sleep briefly when called
            mock_sniff.side_effect = lambda **kw: None

            observer = PacketObserver(
                interface="eth0",
                observer_client_id="client-test-1",
                storage=storage,
            )

            self.assertFalse(observer.is_running)
            observer.start()
            self.assertTrue(observer.is_running)

            observer.stop()
            self.assertFalse(observer.is_running)

    def test_handle_packet_forwards_to_storage(self):
        storage = DailyPacketStorage(storage_dir=self.storage_dir, flush_threshold=1)
        observer = PacketObserver(
            interface="eth0",
            observer_client_id="client-test-1",
            storage=storage,
        )

        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP, TCP

        packet = (
            Ether(src="aa:bb:cc:dd:ee:01", dst="aa:bb:cc:dd:ee:02")
            / IP(src="192.168.1.5", dst="142.250.185.14")
            / TCP(sport=50000, dport=443, flags="S")
        )

        observer._handle_packet(packet)

        # Storage should have received and flushed the packet
        stats = storage.stats
        self.assertEqual(stats["total_observed"], 1)
        self.assertEqual(stats["tcp_count"], 1)

    def test_permission_denied_handled_gracefully(self):
        storage = DailyPacketStorage(storage_dir=self.storage_dir)

        with patch("scapy.all.sniff") as mock_sniff:
            mock_sniff.side_effect = PermissionError("Operation not permitted")

            observer = PacketObserver(
                interface="eth0",
                observer_client_id="client-test-1",
                storage=storage,
            )

            # Starting should not raise exception
            observer.start()
            # Wait for thread to exit due to permission error
            observer.stop()
            self.assertFalse(observer.is_running)


if __name__ == "__main__":
    unittest.main()
