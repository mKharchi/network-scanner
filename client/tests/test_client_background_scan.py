"""Unit tests for asynchronous client-side active network scans."""

import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

dotenv_module = types.ModuleType("dotenv")
dotenv_module.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_module)

import client as client_module  # noqa: E402
import neighbourhood as neighbourhood_module  # noqa: E402


class ClientBackgroundScanTests(unittest.TestCase):
    def test_process_monitor_alert_is_sent_as_a_protocol_frame(self):
        alert = {"title": "Forbidden process terminated", "severity": "HIGH"}
        with patch.object(client_module, "send_alerts") as send_alerts:
            client_module.send_process_monitor_alert(object(), alert)

        send_alerts.assert_called_once_with(
            ANY,
            [{"type": "ALERT", "alert": alert}],
            "process-monitor",
        )

    def test_active_scan_commands_return_disabled_result(self):
        result = client_module.disabled_active_network_scan_result("SCAN_NETWORK")

        self.assertEqual(result["status"], "disabled")
        self.assertIn("active ARP scanning", result["message"])

    def test_daily_snapshot_uses_passive_collection_only(self):
        neighbours = [
            {
                "ip_address": "192.168.1.10",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "entry_type": "dynamic",
            }
        ]
        with patch.object(client_module, "_local_date", return_value="2026-08-20"), patch.object(
            client_module, "_snapshot_client_mac", return_value="11:22:33:44:55:66"
        ), patch.object(client_module, "_load_neighbour_snapshot_state", return_value={}), patch.object(
            client_module, "_save_neighbour_snapshot_state"
        ), patch.object(client_module, "NetworkNeighbourCollector") as collector, patch.object(
            client_module, "update_daily_neighbourhood", return_value=("/tmp/2026-08-20.json", {"observations": neighbours})
        ) as update, patch.object(
            client_module, "send_message"
        ) as send:
            collector.return_value.collect.return_value = neighbours
            completed = client_module.send_daily_network_neighbours(object())

        self.assertTrue(completed)
        collector.return_value.collect.assert_called_once_with(
            enrich=True, active_scan=False
        )
        update.assert_called_once_with(neighbours, date="2026-08-20")
        send.assert_not_called()

    def test_dhcp_observation_is_stored_locally_without_a_network_message(self):
        observation = {
            "requested_ip": "192.168.1.10",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "hostname": "desktop",
            "vendor_class": "MSFT 5.0",
            "client_id": "01:AA:BB:CC:DD:EE:FF",
            "dhcp_message_type": 3,
        }
        with patch.object(client_module, "_lookup_dhcp_vendor", return_value="Example Vendor"), patch.object(
            client_module, "update_daily_neighbourhood", return_value=("/tmp/2026-08-20.json", {"observations": []})
        ) as update, patch.object(client_module, "send_message") as send:
            stored = client_module.store_dhcp_neighbourhood_observation(observation)

        self.assertEqual(stored["source"], "dhcp")
        self.assertEqual(stored["dhcp_vendor_class"], "MSFT 5.0")
        update.assert_called_once_with([stored])
        send.assert_not_called()

    def test_dhcp_observation_is_persisted_in_the_daily_client_file(self):
        observation = {
            "requested_ip": "192.168.1.10",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "hostname": "desktop",
            "vendor_class": "MSFT 5.0",
            "client_id": "01:AA:BB:CC:DD:EE:FF",
            "dhcp_message_type": 3,
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(client_module, "_lookup_dhcp_vendor", return_value="Example Vendor"), patch.object(
                client_module,
                "update_daily_neighbourhood",
                side_effect=lambda observations: neighbourhood_module.update_daily_neighbourhood(
                    observations, date="2026-08-20", storage_dir=directory
                ),
            ):
                stored = client_module.store_dhcp_neighbourhood_observation(observation)

            payload = neighbourhood_module.load_daily_neighbourhood(
                date="2026-08-20", storage_dir=directory
            )

        self.assertEqual(len(payload["observations"]), 1)
        self.assertEqual(payload["observations"][0]["mac_address"], stored["mac_address"])
        self.assertEqual(payload["observations"][0]["source"], "dhcp")
        self.assertEqual(payload["observations"][0]["dhcp_vendor_class"], "MSFT 5.0")

    def test_normal_arp_and_dhcp_collection_never_transmit_immediately(self):
        arp_neighbours = [{
            "ip_address": "192.168.1.10",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "entry_type": "dynamic",
        }]
        dhcp_observation = {
            "requested_ip": "192.168.1.11",
            "mac_address": "12:22:33:44:55:66",
            "dhcp_message_type": 3,
        }
        with patch.object(client_module, "_local_date", return_value="2026-08-20"), patch.object(
            client_module, "_snapshot_client_mac", return_value="AA:BB:CC:DD:EE:FF"
        ), patch.object(client_module, "_load_neighbour_snapshot_state", return_value={}), patch.object(
            client_module, "_save_neighbour_snapshot_state"
        ), patch.object(client_module, "NetworkNeighbourCollector") as collector, patch.object(
            client_module,
            "update_daily_neighbourhood",
            return_value=("/tmp/2026-08-20.json", {"observations": arp_neighbours}),
        ), patch.object(client_module, "_lookup_dhcp_vendor", return_value=None), patch.object(
            client_module, "send_message"
        ) as send:
            collector.return_value.collect.return_value = arp_neighbours
            self.assertTrue(client_module.collect_daily_network_neighbours())
            self.assertIsNotNone(
                client_module.store_dhcp_neighbourhood_observation(dhcp_observation)
            )

        send.assert_not_called()

    def test_registration_sync_sends_stored_neighbourhood_without_collecting(self):
        neighbours = [
            {
                "ip_address": "192.168.1.10",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "entry_type": "dynamic",
                "source": "arp",
                "sources": ["arp"],
                "observed_at": "2026-08-20T10:00:00+00:00",
            }
        ]
        sent = []
        with patch.object(client_module, "_local_date", return_value="2026-08-20"), patch.object(
            client_module, "load_daily_neighbourhood", return_value={"date": "2026-08-20", "observations": neighbours}
        ) as load, patch.object(
            client_module, "get_daily_neighbourhood_path", return_value=Path(__file__)
        ), patch.object(
            client_module, "NetworkNeighbourCollector"
        ) as collector, patch.object(
            client_module, "send_message", side_effect=lambda _socket, message: sent.append(message)
        ):
            completed = client_module.send_stored_daily_neighbourhood(object())

        self.assertTrue(completed)
        load.assert_called_once_with(date="2026-08-20")
        collector.assert_not_called()
        self.assertEqual(sent[0]["data"]["observation_source"], "DAILY_NEIGHBOUR_SNAPSHOT")
        self.assertEqual(sent[0]["data"]["neighbours"], neighbours)

    def test_deleted_daily_file_ignores_stale_snapshot_marker(self):
        snapshot_path = Path("/tmp/missing-neighbourhood/2026-08-20.json")
        neighbours = [{
            "ip_address": "192.168.1.10",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "entry_type": "dynamic",
        }]
        with patch.object(client_module, "_local_date", return_value="2026-08-20"), patch.object(
            client_module, "_snapshot_client_mac", return_value="AA:BB:CC:DD:EE:FF"
        ), patch.object(
            client_module,
            "get_daily_neighbourhood_path",
            return_value=snapshot_path,
        ), patch.object(
            client_module,
            "_load_neighbour_snapshot_state",
            return_value={
                "last_snapshot_date": "2026-08-20",
                "client_mac": "AA:BB:CC:DD:EE:FF",
            },
        ), patch.object(client_module, "_save_neighbour_snapshot_state"), patch.object(
            client_module, "NetworkNeighbourCollector"
        ) as collector, patch.object(
            client_module,
            "update_daily_neighbourhood",
            return_value=(snapshot_path, {"observations": neighbours}),
        ):
            collector.return_value.collect.return_value = neighbours
            self.assertTrue(client_module.collect_daily_network_neighbours())

        collector.return_value.collect.assert_called_once_with(
            enrich=True, active_scan=False
        )

    def test_registration_sync_sends_an_empty_existing_snapshot(self):
        sent = []
        with patch.object(client_module, "_local_date", return_value="2026-08-20"), patch.object(
            client_module, "load_daily_neighbourhood", return_value={"date": "2026-08-20", "observations": []}
        ), patch.object(
            client_module, "get_daily_neighbourhood_path", return_value=Path(__file__)
        ), patch.object(
            client_module, "send_message", side_effect=lambda _socket, message: sent.append(message)
        ):
            completed = client_module.send_stored_daily_neighbourhood(object())

        self.assertTrue(completed)
        self.assertEqual(sent[0]["data"]["neighbours"], [])

    def test_registration_rebuilds_missing_daily_file_before_synchronizing(self):
        snapshot_path = Path("/tmp/missing-neighbourhood/2026-08-20.json")
        neighbours = [{
            "ip_address": "192.168.1.10",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "entry_type": "dynamic",
        }]
        sent = []
        with patch.object(client_module, "_local_date", return_value="2026-08-20"), patch.object(
            client_module, "get_daily_neighbourhood_path", return_value=snapshot_path
        ), patch.object(
            client_module, "collect_daily_network_neighbours", return_value=True
        ) as collect, patch.object(
            client_module,
            "load_daily_neighbourhood",
            return_value={"date": "2026-08-20", "observations": neighbours},
        ), patch.object(
            client_module,
            "send_message",
            side_effect=lambda _socket, message: sent.append(message),
        ):
            completed = client_module.send_stored_daily_neighbourhood(object())

        self.assertTrue(completed)
        collect.assert_called_once_with()
        self.assertEqual(sent[0]["data"]["neighbours"], neighbours)

    def test_server_request_sends_stored_neighbourhood_without_collecting(self):
        neighbours = [
            {
                "ip_address": "192.168.1.10",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "entry_type": "dynamic",
                "source": "dhcp",
                "sources": ["dhcp"],
                "observed_at": "2026-08-20T10:00:00+00:00",
            }
        ]
        sent = []
        with patch.object(client_module, "_local_date", return_value="2026-08-20"), patch.object(
            client_module, "load_daily_neighbourhood", return_value={"date": "2026-08-20", "observations": neighbours}
        ) as load, patch.object(
            client_module, "NetworkNeighbourCollector"
        ) as collector, patch.object(
            client_module, "send_message", side_effect=lambda _socket, message: sent.append(message)
        ):
            result = client_module.send_requested_network_neighbourhood(object())

        self.assertEqual(result, {"status": "ok", "observations_sent": 1})
        load.assert_called_once_with(date="2026-08-20")
        collector.assert_not_called()
        self.assertEqual(sent[0]["data"]["observation_source"], "REQUESTED_NEIGHBOURHOOD")
        self.assertEqual(sent[0]["data"]["neighbours"], neighbours)

    def test_passive_neighbourhood_request_reads_only_listener_snapshot(self):
        observations = [{
            "protocol": "ssdp",
            "observed_at": "2026-08-22T10:00:00+00:00",
            "ip_address": "172.16.0.30",
        }]
        listener = MagicMock()
        listener.snapshot.return_value = observations

        with patch.object(
            client_module, "_snapshot_client_mac", return_value="AA:BB:CC:DD:EE:FF"
        ):
            result = client_module.get_requested_passive_neighbourhood(listener)

        self.assertEqual(result["reporter"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(result["observations"], observations)
        self.assertIn("observed_at", result)
        listener.snapshot.assert_called_once_with()
        with patch.object(client_module, "_snapshot_client_mac", return_value=None):
            empty_result = client_module.get_requested_passive_neighbourhood(None)
        self.assertEqual(empty_result["reporter"], "unknown")
        self.assertEqual(empty_result["observations"], [])
        self.assertIn("observed_at", empty_result)

    def test_passive_neighbourhood_request_does_not_use_daily_neighbourhood_paths(self):
        listener = MagicMock()
        listener.snapshot.return_value = [{"protocol": "mdns", "hostname": "printer.local"}]
        with patch.object(client_module, "_snapshot_client_mac", return_value="AA:BB:CC:DD:EE:FF"), patch.object(
            client_module, "load_daily_neighbourhood", side_effect=AssertionError
        ), patch.object(
            client_module, "update_daily_neighbourhood", side_effect=AssertionError
        ), patch.object(
            client_module, "send_message", side_effect=AssertionError
        ):
            result = client_module.get_requested_passive_neighbourhood(listener)

        self.assertEqual(result["observations"], listener.snapshot.return_value)

    def test_requested_neighbourhood_command_runs_in_a_background_worker(self):
        entered = threading.Event()
        release = threading.Event()
        sent = []

        def delayed_report(_socket):
            entered.set()
            release.wait(1)
            return {"status": "ok", "observations_sent": 2}

        with patch.object(
            client_module,
            "send_requested_network_neighbourhood",
            side_effect=delayed_report,
        ), patch.object(
            client_module,
            "send_message",
            side_effect=lambda _socket, message: sent.append(message),
        ):
            worker = client_module.start_requested_neighbourhood_command(object())
            self.assertTrue(entered.wait(1))
            self.assertTrue(worker.is_alive())
            self.assertEqual(sent, [])
            release.set()
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(sent, [{
            "type": "RESPONSE",
            "command": "GET_NETWORK_NEIGHBOURHOOD",
            "data": {"status": "ok", "observations_sent": 2},
        }])

    def test_session_starts_and_stops_passive_protocol_listener_with_dhcp(self):
        class FakeSocket:
            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                pass

            def getsockname(self):
                return ("172.16.0.10", 50001)

            def close(self):
                pass

        stop_event = threading.Event()
        messages = iter([
            {"type": "REGISTERED"},
            {"type": "FORBIDDEN_PROCESSES", "data": []},
            None,
        ])

        def receive(_socket, **_kwargs):
            message = next(messages)
            if message is None:
                stop_event.set()
            return message

        with patch.object(client_module.socket, "socket", return_value=FakeSocket()), patch.object(
            client_module, "receive_message", side_effect=receive
        ), patch.object(
            client_module, "_startup_log"
        ), patch.object(
            client_module, "create_registration_message", return_value={"type": "REGISTER", "data": {}}
        ), patch.object(client_module, "send_message"), patch.object(
            client_module, "send_stored_daily_neighbourhood"
        ), patch.object(client_module, "collect_daily_network_neighbours"), patch.object(
            client_module, "background_scanner"
        ), patch("network_neighbour_collector.get_local_network", return_value={"interface": "Ethernet 2"}), patch.object(
            client_module, "DHCPListener"
        ) as dhcp_listener, patch.object(
            client_module, "PassiveProtocolListener"
        ) as passive_listener:
            client_module.start_client(stop_event)

        dhcp_listener.assert_called_once()
        self.assertEqual(dhcp_listener.call_args.kwargs["interface"], "Ethernet 2")
        dhcp_listener.return_value.start.assert_called_once_with()
        dhcp_listener.return_value.stop.assert_called_once_with()
        passive_listener.assert_called_once()
        self.assertEqual(passive_listener.call_args.kwargs["interface"], "Ethernet 2")
        self.assertTrue(callable(passive_listener.call_args.kwargs["status_callback"]))
        passive_listener.return_value.start.assert_called_once_with()
        passive_listener.return_value.stop.assert_called_once_with()

    def test_session_returns_passive_neighbourhood_response_from_listener_snapshot(self):
        class FakeSocket:
            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                pass

            def getsockname(self):
                return ("172.16.0.10", 50001)

            def close(self):
                pass

        stop_event = threading.Event()
        messages = iter([
            {"type": "REGISTERED"},
            {"type": "FORBIDDEN_PROCESSES", "data": []},
            {"type": "COMMAND", "command": "GET_PASSIVE_NEIGHBOURHOOD"},
            None,
        ])
        sent = []

        def receive(_socket, **_kwargs):
            message = next(messages)
            if message is None:
                stop_event.set()
            return message

        observations = [{"protocol": "mdns", "hostname": "printer.local"}]
        with patch.object(client_module.socket, "socket", return_value=FakeSocket()), patch.object(
            client_module, "receive_message", side_effect=receive
        ), patch.object(
            client_module, "_startup_log"
        ), patch.object(
            client_module, "_snapshot_client_mac", return_value="AA:BB:CC:DD:EE:FF"
        ), patch.object(
            client_module, "create_registration_message", return_value={"type": "REGISTER", "data": {}}
        ), patch.object(
            client_module, "send_message", side_effect=lambda _socket, message: sent.append(message)
        ), patch.object(
            client_module, "send_stored_daily_neighbourhood"
        ), patch.object(
            client_module, "collect_daily_network_neighbours"
        ), patch.object(
            client_module, "background_scanner"
        ), patch("network_neighbour_collector.get_local_network", return_value={"interface": "Ethernet 2"}), patch.object(
            client_module, "DHCPListener"
        ), patch.object(
            client_module, "PassiveProtocolListener"
        ) as passive_listener:
            passive_listener.return_value.snapshot.return_value = observations
            client_module.start_client(stop_event)

        response = next(message for message in sent if message.get("command") == "GET_PASSIVE_NEIGHBOURHOOD")
        self.assertEqual(response["type"], "RESPONSE")
        self.assertEqual(response["data"]["reporter"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(response["data"]["observations"], observations)
        passive_listener.return_value.snapshot.assert_called_once_with()

    def test_active_scan_reports_results_as_an_async_neighbour_message(self):
        neighbours = [
            {
                "ip_address": "192.168.1.10",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "entry_type": "dynamic",
            }
        ]
        sent = []

        with patch.object(client_module, "NetworkNeighbourCollector") as collector, patch.object(
            client_module, "send_message", side_effect=lambda _socket, message: sent.append(message)
        ):
            collector.return_value.collect.return_value = neighbours
            completed = client_module.send_active_network_neighbours(
                object(), global_scan_id="global-test"
            )

        self.assertTrue(completed)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["type"], "NETWORK_NEIGHBOURS")
        self.assertEqual(
            sent[0]["data"]["observation_source"], "ACTIVE_NEIGHBOUR_SCAN"
        )
        self.assertEqual(sent[0]["data"]["neighbours"], neighbours)
        self.assertEqual(sent[0]["data"]["global_scan_id"], "global-test")
        collector.return_value.collect.assert_called_once_with(
            enrich=True, active_scan=True
        )


if __name__ == "__main__":
    unittest.main()
