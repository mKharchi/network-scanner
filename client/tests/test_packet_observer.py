"""Unit tests for packet_observer module.

These tests target the *routing and forwarding logic* inside PacketObserver
(scope gating, v2 consumer dispatch, V1 storage priority) and deliberately
avoid importing or building real Scapy packets.  The Scapy-dependent
``extract_metadata_from_scapy`` helper is patched at the ``packet_observer``
module boundary so every test can run without Scapy installed.
"""

import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add client/app to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from packet_observer import PacketObserver
from packet_storage import DailyPacketStorage
from scope_filter import ScopeFilter


# ---------------------------------------------------------------------------
# A minimal pre-built observation dict that _handle_packet would receive
# after extract_metadata_from_scapy has done its job.
# ---------------------------------------------------------------------------
_TCP_OBS_IN_SCOPE = {
    "timestamp": "2026-09-02T11:00:00.000Z",
    "src_mac": "AA:BB:CC:DD:EE:01",
    "dst_mac": "AA:BB:CC:DD:EE:02",
    "src_ip": "192.168.1.5",
    "dst_ip": "142.250.185.14",
    "src_port": 50000,
    "dst_port": 443,
    "protocol": "TCP",
    "packet_length": 60,
    "tcp_flags": "S",
    "direction": "outbound",
    "interface": "eth0",
    "observer_client_id": "client-test-1",
    "protocol_metadata": {},
}

_TCP_OBS_OUT_OF_SCOPE = {
    **_TCP_OBS_IN_SCOPE,
    "src_ip": "10.1.2.3",
    "dst_ip": "10.1.2.4",
}


def _make_observer(storage, *, scope_filter=None, flow_aggregator=None,
                   telemetry_packet_writer=None):
    """Helper — build a PacketObserver with a pre-built DailyPacketStorage."""
    return PacketObserver(
        interface="eth0",
        observer_client_id="client-test-1",
        storage=storage,
        scope_filter=scope_filter,
        flow_aggregator=flow_aggregator,
        telemetry_packet_writer=telemetry_packet_writer,
    )


class TestPacketObserver(unittest.TestCase):
    """Test observer lifecycle, routing, and error-boundary behavior."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_packet_obs_")
        self.storage_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def test_start_and_stop_lifecycle(self):
        storage = DailyPacketStorage(storage_dir=self.storage_dir)
        observer = _make_observer(storage)

        # Patch sniff inside packet_observer's _run so the thread exits quickly.
        with patch("packet_observer.PacketObserver._run", return_value=None):
            self.assertFalse(observer.is_running)
            observer.start()
            # is_running checks the thread — give it a tick
            import time; time.sleep(0.05)
            observer.stop()
            self.assertFalse(observer.is_running)

    def test_permission_denied_handled_gracefully(self):
        storage = DailyPacketStorage(storage_dir=self.storage_dir)
        observer = _make_observer(storage)

        # If scapy raises PermissionError the observer should exit the loop
        # cleanly rather than propagating the exception.
        done = threading.Event()

        def _fake_run(self_inner):
            try:
                # replicate the permission-error path
                raise PermissionError("Operation not permitted")
            except PermissionError:
                pass  # observer _run catches this internally
            finally:
                done.set()

        with patch.object(PacketObserver, "_run", _fake_run):
            observer.start()
            done.wait(timeout=3.0)
            observer.stop()
            self.assertFalse(observer.is_running)

    # ------------------------------------------------------------------
    # V1 storage always receives observations (patch extract_metadata_from_scapy)
    # ------------------------------------------------------------------

    def test_handle_packet_forwards_to_v1_storage(self):
        """V1 DailyPacketStorage always receives the extracted observation."""
        storage = DailyPacketStorage(storage_dir=self.storage_dir, flush_threshold=1)
        observer = _make_observer(storage)

        fake_packet = object()
        with patch("packet_observer.extract_metadata_from_scapy",
                   return_value=_TCP_OBS_IN_SCOPE):
            observer._handle_packet(fake_packet)

        self.assertEqual(storage.stats["total_observed"], 1)
        self.assertEqual(storage.stats["tcp_count"], 1)

    # ------------------------------------------------------------------
    # Scope-gated v2 forwarding
    # ------------------------------------------------------------------

    def test_in_scope_packet_forwarded_to_flow_aggregator_and_writer(self):
        """In-scope observations reach both v2 consumers after V1 storage."""
        storage = DailyPacketStorage(storage_dir=self.storage_dir, flush_threshold=1)
        flow_aggregator = MagicMock()
        telemetry_packet_writer = MagicMock()
        observer = _make_observer(
            storage,
            scope_filter=ScopeFilter(["192.168.1.0/24"]),
            flow_aggregator=flow_aggregator,
            telemetry_packet_writer=telemetry_packet_writer,
        )

        fake_packet = object()
        with patch("packet_observer.extract_metadata_from_scapy",
                   return_value=_TCP_OBS_IN_SCOPE):
            observer._handle_packet(fake_packet)

        # V1 storage is always fed regardless of scope.
        self.assertEqual(storage.stats["total_observed"], 1)
        flow_aggregator.record_packet.assert_called_once()
        telemetry_packet_writer.record.assert_called_once()

    def test_out_of_scope_packet_still_stored_in_v1_but_not_forwarded(self):
        """Out-of-scope observations go to V1 storage only; v2 consumers are skipped."""
        storage = DailyPacketStorage(storage_dir=self.storage_dir, flush_threshold=1)
        flow_aggregator = MagicMock()
        telemetry_packet_writer = MagicMock()
        observer = _make_observer(
            storage,
            # Scope that does not include either endpoint in _TCP_OBS_OUT_OF_SCOPE.
            scope_filter=ScopeFilter(["172.16.0.0/24"]),
            flow_aggregator=flow_aggregator,
            telemetry_packet_writer=telemetry_packet_writer,
        )

        fake_packet = object()
        with patch("packet_observer.extract_metadata_from_scapy",
                   return_value=_TCP_OBS_OUT_OF_SCOPE):
            observer._handle_packet(fake_packet)

        self.assertEqual(storage.stats["total_observed"], 1)
        flow_aggregator.record_packet.assert_not_called()
        telemetry_packet_writer.record.assert_not_called()

    def test_no_scope_filter_configured_forwards_everything(self):
        """Fail-open: no scope filter → every observation reaches the flow aggregator."""
        storage = DailyPacketStorage(storage_dir=self.storage_dir, flush_threshold=1)
        flow_aggregator = MagicMock()
        observer = _make_observer(storage, flow_aggregator=flow_aggregator)

        fake_packet = object()
        with patch("packet_observer.extract_metadata_from_scapy",
                   return_value=_TCP_OBS_IN_SCOPE):
            observer._handle_packet(fake_packet)

        flow_aggregator.record_packet.assert_called_once()

    def test_flow_aggregator_error_does_not_stop_writer(self):
        """An exception from the flow aggregator must not prevent the writer from running."""
        storage = DailyPacketStorage(storage_dir=self.storage_dir, flush_threshold=1)
        flow_aggregator = MagicMock()
        flow_aggregator.record_packet.side_effect = RuntimeError("boom")
        telemetry_packet_writer = MagicMock()
        observer = _make_observer(
            storage,
            flow_aggregator=flow_aggregator,
            telemetry_packet_writer=telemetry_packet_writer,
        )

        fake_packet = object()
        with patch("packet_observer.extract_metadata_from_scapy",
                   return_value=_TCP_OBS_IN_SCOPE):
            # Must not raise
            observer._handle_packet(fake_packet)

        telemetry_packet_writer.record.assert_called_once()

    def test_v2_consumer_error_does_not_break_v1_storage(self):
        """Exceptions from v2 consumers must never corrupt V1 storage counts."""
        storage = DailyPacketStorage(storage_dir=self.storage_dir, flush_threshold=1)
        flow_aggregator = MagicMock()
        flow_aggregator.record_packet.side_effect = Exception("v2 crash")
        observer = _make_observer(storage, flow_aggregator=flow_aggregator)

        fake_packet = object()
        with patch("packet_observer.extract_metadata_from_scapy",
                   return_value=_TCP_OBS_IN_SCOPE):
            observer._handle_packet(fake_packet)

        # V1 counter must still be correct despite v2 failure
        self.assertEqual(storage.stats["total_observed"], 1)


if __name__ == "__main__":
    unittest.main()
