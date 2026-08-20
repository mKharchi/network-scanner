"""Unit tests for asynchronous client-side active network scans."""

import sys
import tempfile
import socket
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

dotenv_module = types.ModuleType("dotenv")
dotenv_module.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_module)

import client as client_module  # noqa: E402
import neighbourhood as neighbourhood_module  # noqa: E402


class ClientBackgroundScanTests(unittest.TestCase):
    def test_active_scan_commands_return_disabled_result(self):
        result = client_module.disabled_active_network_scan_result("SCAN_NETWORK")

        self.assertEqual(result["status"], "disabled")
        self.assertIn("active ARP scanning", result["message"])

    def test_receive_message_honours_shutdown_before_reading(self):
        reader, writer = socket.socketpair()
        stop_event = threading.Event()
        stop_event.set()
        try:
            self.assertIsNone(
                client_module.receive_message(reader, stop_event=stop_event)
            )
        finally:
            reader.close()
            writer.close()

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
