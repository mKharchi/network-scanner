"""Unit tests for flow_aggregator module (v2 Phase 2)."""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from flow_aggregator import FlowAggregator
from telemetry_storage import get_flows_path


def _obs(**overrides):
    base = {
        "timestamp": "2026-09-02T13:35:22.495Z",
        "observer_client_id": "client_07",
        "src_mac": "E4:FD:45:BA:8B:96",
        "src_ip": "172.16.2.246",
        "dst_mac": "AC:71:2E:FA:88:3F",
        "dst_ip": "43.163.42.171",
        "src_port": 61488,
        "dst_port": 443,
        "protocol": "TCP",
        "direction": "outbound",
        "packet_length": 573,
        "tcp_flags": "S",
    }
    base.update(overrides)
    return base


class TestFlowAggregator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_flow_agg_")
        self.root = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_aggregator(self, **kwargs):
        kwargs.setdefault("observer_client_id", "client_07")
        kwargs.setdefault("date_provider", lambda: "2026-09-02")
        kwargs.setdefault("root", self.root)
        return FlowAggregator(**kwargs)

    def test_single_packet_creates_active_flow(self):
        agg = self._make_aggregator()
        agg.record_packet(_obs())
        self.assertEqual(agg.active_flow_count, 1)

    def test_bidirectional_packets_merge_into_one_flow(self):
        agg = self._make_aggregator()
        agg.record_packet(_obs(direction="outbound"))
        agg.record_packet(
            _obs(
                src_mac="AC:71:2E:FA:88:3F",
                src_ip="43.163.42.171",
                dst_mac="E4:FD:45:BA:8B:96",
                dst_ip="172.16.2.246",
                src_port=443,
                dst_port=61488,
                direction="inbound",
                tcp_flags="A",
            )
        )
        self.assertEqual(agg.active_flow_count, 1)

    def test_different_flows_are_kept_separate(self):
        agg = self._make_aggregator()
        agg.record_packet(_obs(dst_port=443))
        agg.record_packet(_obs(dst_port=80, protocol="TCP"))
        self.assertEqual(agg.active_flow_count, 2)

    def test_flush_all_writes_flow_record_matching_schema(self):
        agg = self._make_aggregator()
        agg.record_packet(_obs(packet_length=500, tcp_flags="S"))
        agg.record_packet(_obs(packet_length=600, tcp_flags="A"))
        agg.record_packet(
            _obs(
                packet_length=100,
                tcp_flags="FA",
                direction="inbound",
                src_mac="AC:71:2E:FA:88:3F",
                src_ip="43.163.42.171",
                dst_mac="E4:FD:45:BA:8B:96",
                dst_ip="172.16.2.246",
                src_port=443,
                dst_port=61488,
            )
        )
        finalized = agg.flush_all()
        self.assertEqual(finalized, 1)
        self.assertEqual(agg.active_flow_count, 0)

        flows_path = get_flows_path("2026-09-02", root=self.root)
        self.assertTrue(flows_path.exists())
        records = json.loads(flows_path.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 1)
        record = records[0]

        expected_fields = {
            "flow_id", "observer_client_id", "first_seen", "last_seen",
            "src_mac", "src_ip", "dst_mac", "dst_ip", "src_port", "dst_port",
            "protocol", "application_protocol", "direction", "packet_count",
            "bytes", "duration", "avg_packet_size", "min_packet_size",
            "max_packet_size", "tcp_syn", "tcp_fin", "tcp_rst",
            "inbound_packets", "outbound_packets", "inbound_bytes",
            "outbound_bytes", "avg_inter_arrival_time",
        }
        self.assertEqual(set(record.keys()), expected_fields)
        self.assertEqual(record["packet_count"], 3)
        self.assertEqual(record["bytes"], 1200)
        self.assertEqual(record["tcp_syn"], 1)
        self.assertEqual(record["tcp_fin"], 1)
        self.assertEqual(record["inbound_packets"], 1)
        self.assertEqual(record["outbound_packets"], 2)
        self.assertEqual(record["observer_client_id"], "client_07")
        self.assertTrue(record["flow_id"].startswith("client_07-"))

    def test_idle_sweep_finalizes_expired_flows(self):
        agg = self._make_aggregator(idle_timeout_seconds=0.05, sweep_interval_seconds=0.02)
        agg.record_packet(_obs())
        self.assertEqual(agg.active_flow_count, 1)
        time.sleep(0.1)
        finalized = agg.sweep_idle_flows()
        self.assertEqual(finalized, 1)
        self.assertEqual(agg.active_flow_count, 0)

    def test_start_stop_background_sweep(self):
        agg = self._make_aggregator(idle_timeout_seconds=0.05, sweep_interval_seconds=0.02)
        agg.record_packet(_obs())
        agg.start()
        time.sleep(0.2)
        agg.stop()
        flows_path = get_flows_path("2026-09-02", root=self.root)
        self.assertTrue(flows_path.exists())

    def test_udp_flow_has_no_syn_fin_rst(self):
        agg = self._make_aggregator()
        agg.record_packet(
            _obs(protocol="UDP", tcp_flags=None, dst_port=53, application_protocol=None)
        )
        agg.flush_all()
        flows_path = get_flows_path("2026-09-02", root=self.root)
        records = json.loads(flows_path.read_text(encoding="utf-8"))
        self.assertEqual(records[0]["tcp_syn"], 0)
        self.assertEqual(records[0]["tcp_fin"], 0)
        self.assertEqual(records[0]["tcp_rst"], 0)


if __name__ == "__main__":
    unittest.main()
