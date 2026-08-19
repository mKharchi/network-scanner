"""Unit tests for asynchronous client-side active network scans."""

import sys
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


class ClientBackgroundScanTests(unittest.TestCase):
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
