"""Unit tests for telemetry_packet_writer module (v2 production-loop integration)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from telemetry_packet_writer import TelemetryPacketWriter
from telemetry_storage import get_protocol_packet_path, read_json


class TestTelemetryPacketWriter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_telemetry_packet_writer_")
        self.root = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _writer(self, **kwargs):
        return TelemetryPacketWriter(
            date_provider=lambda: "2026-09-02",
            root=self.root,
            flush_threshold=1000,
            flush_interval_seconds=1000,
            **kwargs,
        )

    def test_record_buffers_until_flush(self):
        writer = self._writer()
        writer.record({"protocol": "TCP", "packet_length": 60})
        path = get_protocol_packet_path("2026-09-02", "tcp", root=self.root)
        self.assertFalse(path.exists())
        flushed = writer.flush()
        self.assertEqual(flushed, 1)
        self.assertTrue(path.exists())
        records = read_json(path, default=[])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["protocol"], "TCP")

    def test_record_groups_by_protocol(self):
        writer = self._writer()
        writer.record({"protocol": "TCP"})
        writer.record({"protocol": "UDP"})
        writer.record({"protocol": "TCP"})
        writer.flush()
        tcp_path = get_protocol_packet_path("2026-09-02", "tcp", root=self.root)
        udp_path = get_protocol_packet_path("2026-09-02", "udp", root=self.root)
        self.assertEqual(len(read_json(tcp_path, default=[])), 2)
        self.assertEqual(len(read_json(udp_path, default=[])), 1)

    def test_missing_protocol_defaults_to_unknown(self):
        writer = self._writer()
        writer.record({"packet_length": 10})
        writer.flush()
        path = get_protocol_packet_path("2026-09-02", "unknown", root=self.root)
        self.assertEqual(len(read_json(path, default=[])), 1)

    def test_non_dict_observation_ignored(self):
        writer = self._writer()
        writer.record("not-a-dict")
        writer.record(None)
        self.assertEqual(writer.flush(), 0)

    def test_flush_threshold_triggers_automatic_flush(self):
        writer = TelemetryPacketWriter(
            date_provider=lambda: "2026-09-02",
            root=self.root,
            flush_threshold=2,
            flush_interval_seconds=1000,
        )
        writer.record({"protocol": "ARP"})
        path = get_protocol_packet_path("2026-09-02", "arp", root=self.root)
        self.assertFalse(path.exists())
        writer.record({"protocol": "ARP"})
        # Threshold reached on the second record; flush should have happened.
        self.assertTrue(path.exists())
        self.assertEqual(len(read_json(path, default=[])), 2)

    def test_start_stop_flushes_pending_records(self):
        writer = self._writer()
        writer.start()
        writer.record({"protocol": "DHCP"})
        writer.stop()
        path = get_protocol_packet_path("2026-09-02", "dhcp", root=self.root)
        self.assertTrue(path.exists())
        self.assertEqual(len(read_json(path, default=[])), 1)


if __name__ == "__main__":
    unittest.main()
