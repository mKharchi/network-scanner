"""Unit tests for the network-interface identity used during registration."""

import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

import client_lib  # noqa: E402


class ClientIdentityTests(unittest.TestCase):
    def test_get_mac_uses_interface_that_owns_active_ip(self):
        link_family = getattr(client_lib.psutil, "AF_LINK", socket.AF_PACKET)
        interfaces = {
            "virtual-adapter": [
                SimpleNamespace(family=socket.AF_INET, address="10.0.0.5"),
                SimpleNamespace(family=link_family, address="00:11:22:33:44:55"),
            ],
            "wifi": [
                SimpleNamespace(family=socket.AF_INET, address="172.16.0.102"),
                SimpleNamespace(family=link_family, address="e4-fd-45-ba-8b-96"),
            ],
        }
        with patch.object(client_lib.psutil, "net_if_addrs", return_value=interfaces):
            mac_address = client_lib.get_mac("172.16.0.102")

        self.assertEqual(mac_address, "e4:fd:45:ba:8b:96")

    def test_registration_uses_the_connected_server_socket_ip(self):
        with patch.object(client_lib, "get_system_info", return_value={"ip": "172.16.0.102"}) as get_info:
            registration = client_lib.create_registration_message("172.16.0.102")

        self.assertEqual(registration["type"], "REGISTER")
        get_info.assert_called_once_with("172.16.0.102")

    def test_registration_includes_client_version_and_platform(self):
        with patch.object(client_lib, "get_system_info", return_value={"ip": "172.16.0.102"}), \
             patch.object(client_lib, "get_client_version", return_value="1.2.3"):
            registration = client_lib.create_registration_message()

        self.assertEqual(registration["data"]["client_version"], "1.2.3")
        self.assertIn("platform", registration["data"])

    def test_registration_reports_cached_location(self):
        location = {"id": 4, "label": "F1-A1-T1-P1"}
        with patch.object(client_lib, "get_system_info", return_value={"ip": "172.16.0.102"}), \
             patch.object(client_lib, "load_client_location", return_value=location):
            registration = client_lib.create_registration_message()

        self.assertEqual(registration["data"]["location"], location)

    def test_get_canonical_client_id_formats_mac_correctly(self):
        client_id = client_lib.get_canonical_client_id("E4:FD:45:BA:8B:96")
        self.assertEqual(client_id, "client-e4fd45ba8b96")

    def test_get_canonical_client_id_respects_explicit_env_var(self):
        with patch.dict("os.environ", {"CLIENT_ID": "custom-agent-99"}):
            client_id = client_lib.get_canonical_client_id("E4:FD:45:BA:8B:96")
            self.assertEqual(client_id, "custom-agent-99")

    def test_get_canonical_client_id_handles_missing_mac(self):
        with patch.object(client_lib, "get_mac", side_effect=RuntimeError("no mac")):
            with patch.dict("os.environ", {}, clear=True):
                client_id = client_lib.get_canonical_client_id(None)
                self.assertEqual(client_id, "unknown-client")


if __name__ == "__main__":
    unittest.main()
