"""Tests for non-destructive device-isolation network-state capture."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from network_state_manager import DeviceIsolationState, NetworkStateManager  # noqa: E402


WINDOWS_STATE = {
    "interface_index": 4,
    "interface_name": "Wi-Fi 2",
    "interface_alias": "Wi-Fi 2",
    "mac_address": "E4-FD-45-BA-8B-96",
    "dhcp_enabled": True,
    "dhcp_server": "172.16.0.1",
    "ipv4_addresses": [{"address": "172.16.0.102", "prefix_length": 16}],
    "default_gateway": "172.16.0.1",
    "dns_servers": ["172.16.0.1", "1.1.1.1"],
    "ipv4_connection_state": "Connected",
    "ipv6_enabled": True,
}


class NetworkStateManagerTests(unittest.TestCase):
    def test_captures_the_active_windows_interface_state(self):
        manager = NetworkStateManager(
            command_runner=lambda _command: (0, json.dumps(WINDOWS_STATE))
        )
        with patch("network_state_manager.platform.system", return_value="Windows"):
            state = manager.get_interface_state()

        self.assertEqual(state["interface_index"], 4)
        self.assertEqual(state["interface_name"], "Wi-Fi 2")
        self.assertEqual(state["mac_address"], "E4:FD:45:BA:8B:96")
        self.assertTrue(state["dhcp_enabled"])
        self.assertEqual(state["ipv4_addresses"][0]["prefix_length"], 16)
        self.assertEqual(state["dns_servers"], ["172.16.0.1", "1.1.1.1"])

    def test_persists_and_loads_a_recovery_record_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "device_isolation" / "state.json"
            manager = NetworkStateManager(
                state_path=state_path,
                command_runner=lambda _command: (0, json.dumps(WINDOWS_STATE)),
            )
            with patch("network_state_manager.platform.system", return_value="Windows"):
                saved = manager.save_current_configuration(reason="Controlled test")
            loaded = manager.load_saved_configuration()
            lifecycle = manager.get_lifecycle_state()
            with manager.audit_path.open("r", encoding="utf-8") as audit_file:
                audit_events = [json.loads(line) for line in audit_file]

        self.assertEqual(saved["reason"], "Controlled test")
        self.assertEqual(loaded["state"]["default_gateway"], "172.16.0.1")
        self.assertEqual(loaded["state"]["dhcp_server"], "172.16.0.1")
        self.assertEqual(lifecycle["state"], DeviceIsolationState.NORMAL)
        self.assertEqual(audit_events[0]["details"]["interface"], "Wi-Fi 2")

    def test_records_durable_lifecycle_transitions_without_network_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = NetworkStateManager(state_path=Path(directory) / "state.json")
            started = manager.record_lifecycle_state(
                DeviceIsolationState.ISOLATING, reason="Controlled test"
            )
            completed = manager.record_lifecycle_state(DeviceIsolationState.ISOLATION_FAILED)

            lifecycle = manager.get_lifecycle_state()
            with manager.audit_path.open("r", encoding="utf-8") as audit_file:
                audit_events = [json.loads(line) for line in audit_file]

        self.assertEqual(started["state"], DeviceIsolationState.ISOLATING)
        self.assertEqual(completed["state"], DeviceIsolationState.ISOLATION_FAILED)
        self.assertEqual(lifecycle["state"], DeviceIsolationState.ISOLATION_FAILED)
        self.assertEqual([event["state"] for event in audit_events], [
            DeviceIsolationState.ISOLATING,
            DeviceIsolationState.ISOLATION_FAILED,
        ])

    def test_rejects_unknown_lifecycle_states(self):
        manager = NetworkStateManager()
        with self.assertRaisesRegex(ValueError, "Unsupported device-isolation state"):
            manager.record_lifecycle_state("DISCONNECTED")

    def test_static_profile_requires_explicit_opt_in(self):
        manager = NetworkStateManager()
        with self.assertRaisesRegex(RuntimeError, "explicit enabled=True"):
            manager.isolate_static_ip()

    def test_static_profile_saves_recovery_state_before_the_network_operation(self):
        calls = []

        def runner(command):
            calls.append(command)
            if command[0] == "powershell.exe" and "Get-NetRoute" in command[-1]:
                return 0, json.dumps(WINDOWS_STATE)
            return 0, "ok"

        with tempfile.TemporaryDirectory() as directory, patch(
            "network_state_manager.platform.system", return_value="Windows"
        ):
            manager = NetworkStateManager(
                state_path=Path(directory) / "state.json", command_runner=runner
            )
            result = manager.isolate_static_ip(reason="Controlled test", enabled=True)

            saved = manager.load_saved_configuration()
            lifecycle = manager.get_lifecycle_state()

        self.assertEqual(result["state"], DeviceIsolationState.ISOLATED)
        self.assertEqual(saved["state"]["default_gateway"], "172.16.0.1")
        self.assertEqual(lifecycle["state"], DeviceIsolationState.ISOLATED)
        self.assertIn("192.0.2.2", calls[-1][-1])
        self.assertIn("PrefixLength 32", calls[-1][-1])
        self.assertIn("Disable-NetAdapterBinding", calls[-1][-1])
        self.assertIn("address=none", calls[-1][-1])

    def test_restore_uses_the_saved_network_configuration(self):
        calls = []

        def runner(command):
            calls.append(command)
            if "Get-NetRoute" in command[-1]:
                return 0, json.dumps(WINDOWS_STATE)
            return 0, "ok"

        with tempfile.TemporaryDirectory() as directory, patch(
            "network_state_manager.platform.system", return_value="Windows"
        ):
            manager = NetworkStateManager(
                state_path=Path(directory) / "state.json", command_runner=runner
            )
            manager.save_current_configuration(reason="Controlled test")
            result = manager.restore_network(reason="Local admin recovery")

        self.assertEqual(result["state"], DeviceIsolationState.RESTORED)
        self.assertIn("Dhcp Enabled", calls[-1][-1])
        self.assertIn("Enable-NetAdapterBinding", calls[-1][-1])

    def test_rejects_an_invalid_network_state_before_persisting(self):
        invalid = dict(WINDOWS_STATE, ipv4_addresses=[])
        manager = NetworkStateManager(
            command_runner=lambda _command: (0, json.dumps(invalid))
        )
        with patch("network_state_manager.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(ValueError, "IPv4 address"):
                manager.get_interface_state()

    def test_does_not_run_on_non_windows_platforms(self):
        manager = NetworkStateManager(command_runner=lambda _command: self.fail("runner called"))
        with patch("network_state_manager.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(RuntimeError, "Windows only"):
                manager.get_interface_state()


if __name__ == "__main__":
    unittest.main()
