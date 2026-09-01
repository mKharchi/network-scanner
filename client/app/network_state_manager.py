"""Reversible Windows network isolation with durable local recovery state."""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


CLIENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = CLIENT_ROOT / "storage" / "device_isolation" / "state.json"
DEFAULT_STATUS_PATH = CLIENT_ROOT / "storage" / "device_isolation" / "status.json"
DEFAULT_AUDIT_PATH = CLIENT_ROOT / "storage" / "device_isolation" / "audit.jsonl"
STATIC_ISOLATION_ADDRESS = "192.0.2.2"
STATIC_ISOLATION_PREFIX_LENGTH = 32
_STATE_LOCK = threading.RLock()


class DeviceIsolationState:
    """Lifecycle states reserved for the separate device-isolation feature."""

    NORMAL = "NORMAL"
    ISOLATING = "ISOLATING"
    ISOLATED = "ISOLATED"
    RESTORING = "RESTORING"
    RESTORED = "RESTORED"
    ISOLATION_FAILED = "ISOLATION_FAILED"

    ALL = {
        NORMAL,
        ISOLATING,
        ISOLATED,
        RESTORING,
        RESTORED,
        ISOLATION_FAILED,
    }


class NetworkStateManager:
    """Capture, isolate, and restore Windows networking through one boundary."""

    def __init__(
        self,
        *,
        state_path: Path | str = DEFAULT_STATE_PATH,
        status_path: Path | str | None = None,
        audit_path: Path | str | None = None,
        command_runner: Optional[Callable[[list[str]], tuple[int, str]]] = None,
    ):
        self.state_path = Path(state_path)
        self.status_path = (
            Path(status_path)
            if status_path is not None
            else self.state_path.with_name("status.json")
        )
        self.audit_path = (
            Path(audit_path)
            if audit_path is not None
            else self.state_path.with_name("audit.jsonl")
        )
        self._command_runner = command_runner or self._run_command

    @staticmethod
    def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".device_isolation_", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2, ensure_ascii=False)
                file.write("\n")
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    @staticmethod
    def _run_command(command: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except OSError as error:
            return -1, str(error)
        except subprocess.TimeoutExpired:
            return -1, "Network state query timed out."
        return result.returncode, (result.stdout or result.stderr).strip()

    @staticmethod
    def _windows_state_query() -> list[str]:
        """Return one JSON object for the interface owning the IPv4 default route."""
        script = r'''
$route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
    Sort-Object RouteMetric, InterfaceMetric |
    Select-Object -First 1
if (-not $route) { throw 'No active IPv4 default route was found.' }
$configuration = Get-NetIPConfiguration -InterfaceIndex $route.InterfaceIndex
$interface = Get-NetIPInterface -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4
$adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex
$dhcp = Get-CimInstance Win32_NetworkAdapterConfiguration |
    Where-Object { $_.InterfaceIndex -eq $route.InterfaceIndex } |
    Select-Object -First 1
[pscustomobject]@{
    interface_index = [int]$route.InterfaceIndex
    interface_name = [string]$adapter.Name
    interface_alias = [string]$configuration.InterfaceAlias
    mac_address = [string]$adapter.MacAddress
    dhcp_enabled = [bool]$dhcp.DHCPEnabled
    dhcp_server = [string]$dhcp.DHCPServer
    ipv4_addresses = @($configuration.IPv4Address | ForEach-Object {
        [pscustomobject]@{ address = [string]$_.IPAddress; prefix_length = [int]$_.PrefixLength }
    })
    default_gateway = [string]$route.NextHop
    dns_servers = @($configuration.DNSServer.ServerAddresses)
    ipv4_connection_state = [string]$interface.ConnectionState
    ipv6_enabled = [bool](($adapter | Get-NetAdapterBinding -ComponentID ms_tcpip6).Enabled)
} | ConvertTo-Json -Compress -Depth 4
'''.strip()
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ]

    @staticmethod
    def _normalise_state(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Network state query did not return an object.")

        index = payload.get("interface_index")
        if not isinstance(index, int) or index < 1:
            raise ValueError("Network state is missing a valid interface index.")

        interface_name = payload.get("interface_name") or payload.get("interface_alias")
        if not isinstance(interface_name, str) or not interface_name.strip():
            raise ValueError("Network state is missing an interface name.")

        addresses = payload.get("ipv4_addresses")
        if not isinstance(addresses, list) or not addresses:
            raise ValueError("Network state is missing an IPv4 address.")
        normalised_addresses = []
        for entry in addresses:
            if not isinstance(entry, dict):
                continue
            try:
                address = ipaddress.IPv4Address(str(entry.get("address")))
            except ipaddress.AddressValueError:
                continue
            prefix = entry.get("prefix_length")
            if not isinstance(prefix, int) or not 0 <= prefix <= 32:
                continue
            normalised_addresses.append({"address": str(address), "prefix_length": prefix})
        if not normalised_addresses:
            raise ValueError("Network state has no valid IPv4 addresses.")

        gateway = payload.get("default_gateway")
        try:
            gateway = str(ipaddress.IPv4Address(str(gateway)))
        except ipaddress.AddressValueError:
            gateway = None

        dns_servers = []
        for server in payload.get("dns_servers", []):
            try:
                dns_servers.append(str(ipaddress.ip_address(str(server))))
            except ValueError:
                continue

        mac = payload.get("mac_address")
        if isinstance(mac, str):
            mac = mac.replace("-", ":").upper()
        else:
            mac = None

        return {
            "interface_index": index,
            "interface_name": interface_name.strip(),
            "interface_alias": payload.get("interface_alias"),
            "mac_address": mac,
            "dhcp_enabled": bool(payload.get("dhcp_enabled")),
            "dhcp_server": payload.get("dhcp_server") or None,
            "ipv4_addresses": normalised_addresses,
            "default_gateway": gateway,
            "dns_servers": dns_servers,
            "ipv4_connection_state": payload.get("ipv4_connection_state") or None,
            "ipv6_enabled": bool(payload.get("ipv6_enabled")),
        }

    def get_interface_state(self) -> dict[str, Any]:
        """Read and validate active Windows IPv4 interface state.

        The returned state is saved before applying static-IP isolation so an
        administrator at the device can restore its original configuration.
        """
        if platform.system() != "Windows":
            raise RuntimeError("Device isolation state capture is supported on Windows only.")
        code, output = self._command_runner(self._windows_state_query())
        if code != 0:
            raise RuntimeError(f"Could not inspect Windows network state: {output}")
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Windows network state was not valid JSON: {error}") from error
        return self._normalise_state(payload)

    def save_current_configuration(self, *, reason: Optional[str] = None) -> dict[str, Any]:
        """Atomically save recovery data before any future isolation operation."""
        state = self.get_interface_state()
        record = {
            "version": 1,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "state": state,
        }
        with _STATE_LOCK:
            self._write_json_atomically(self.state_path, record)
            self.record_lifecycle_state(
                DeviceIsolationState.NORMAL,
                reason=reason,
                details={
                    "interface": state["interface_name"],
                    "ipv4_addresses": state["ipv4_addresses"],
                    "default_gateway": state["default_gateway"],
                    "dhcp_enabled": state["dhcp_enabled"],
                },
            )
        return record

    @staticmethod
    def _powershell_command(script: str) -> list[str]:
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]

    @staticmethod
    def _require_windows() -> None:
        if platform.system() != "Windows":
            raise RuntimeError("Device isolation is supported on Windows only.")

    @staticmethod
    def _isolation_script(interface_index: int) -> str:
        """Return the fixed, no-gateway static-IP isolation operation."""
        return f"""
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
    throw 'Device isolation requires local Administrator privileges.'
}}
$index = {interface_index}
Get-NetAdapter -InterfaceIndex $index | Disable-NetAdapterBinding -ComponentID ms_tcpip6 -Confirm:$false
Set-NetIPInterface -InterfaceIndex $index -AddressFamily IPv4 -Dhcp Disabled
$alias = (Get-NetAdapter -InterfaceIndex $index).Name
& netsh interface ipv4 set dnsservers "name=$alias" source=static address=none validate=no
if ($LASTEXITCODE -ne 0) {{ throw 'Could not clear DNS servers for static isolation.' }}
Get-NetIPAddress -InterfaceIndex $index -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Remove-NetIPAddress -Confirm:$false -ErrorAction Stop
Get-NetRoute -InterfaceIndex $index -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress -InterfaceIndex $index -IPAddress {STATIC_ISOLATION_ADDRESS} -PrefixLength {STATIC_ISOLATION_PREFIX_LENGTH}
""".strip()

    @staticmethod
    def _restore_script(state: dict[str, Any]) -> str:
        """Return a local-admin restore operation based only on saved state."""
        index = state["interface_index"]
        ipv4_commands = "\n".join(
            "New-NetIPAddress -InterfaceIndex $index -IPAddress "
            f"{entry['address']} -PrefixLength {entry['prefix_length']}"
            for entry in state["ipv4_addresses"]
        )
        gateway_command = ""
        if state["default_gateway"]:
            gateway_command = (
                "New-NetRoute -InterfaceIndex $index -AddressFamily IPv4 "
                "-DestinationPrefix '0.0.0.0/0' "
                f"-NextHop {state['default_gateway']}"
            )
        dns_servers = ", ".join(f"'{server}'" for server in state["dns_servers"])
        dns_command = (
            "Set-DnsClientServerAddress -InterfaceIndex $index "
            f"-ServerAddresses @({dns_servers})"
            if dns_servers
            else "Set-DnsClientServerAddress -InterfaceIndex $index -ResetServerAddresses"
        )
        dhcp_command = (
            "Set-NetIPInterface -InterfaceIndex $index -AddressFamily IPv4 -Dhcp Enabled; "
            "Set-DnsClientServerAddress -InterfaceIndex $index -ResetServerAddresses; "
            "ipconfig /renew"
            if state["dhcp_enabled"]
            else "Set-NetIPInterface -InterfaceIndex $index -AddressFamily IPv4 -Dhcp Disabled; "
            + ipv4_commands
            + ("; " + gateway_command if gateway_command else "")
            + "; "
            + dns_command
        )
        ipv6_command = (
            "Get-NetAdapter -InterfaceIndex $index | Enable-NetAdapterBinding -ComponentID ms_tcpip6 -Confirm:$false"
            if state["ipv6_enabled"]
            else "Get-NetAdapter -InterfaceIndex $index | Disable-NetAdapterBinding -ComponentID ms_tcpip6 -Confirm:$false"
        )
        return f"""
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
    throw 'Network restoration requires local Administrator privileges.'
}}
$index = {index}
Get-NetIPAddress -InterfaceIndex $index -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute -InterfaceIndex $index -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
{ipv6_command}
{dhcp_command}
""".strip()

    def isolate_static_ip(self, *, reason: Optional[str] = None, enabled: bool = False) -> dict[str, Any]:
        """Apply the approved controlled-test profile after persisting recovery state.

        This removes normal IPv4 routing and disables IPv6 on one adapter. It
        may immediately disconnect the server, so callers must opt in with
        ``enabled=True`` and rely on local administrator restoration.
        """
        if not enabled:
            raise RuntimeError("Static device isolation requires explicit enabled=True opt-in.")
        self._require_windows()
        record = self.save_current_configuration(reason=reason)
        state = record["state"]
        self.record_lifecycle_state(
            DeviceIsolationState.ISOLATING,
            reason=reason,
            details={"method": "STATIC_IP_NO_GATEWAY", "address": STATIC_ISOLATION_ADDRESS},
        )
        code, output = self._command_runner(
            self._powershell_command(self._isolation_script(state["interface_index"]))
        )
        if code != 0:
            self.record_lifecycle_state(
                DeviceIsolationState.ISOLATION_FAILED,
                reason=reason,
                details={"error": output, "recovery_state_saved": True},
            )
            return {"status": "error", "message": output, "recovery_state_saved": True}
        self.record_lifecycle_state(
            DeviceIsolationState.ISOLATED,
            reason=reason,
            details={"method": "STATIC_IP_NO_GATEWAY", "address": STATIC_ISOLATION_ADDRESS},
        )
        return {"status": "ok", "state": DeviceIsolationState.ISOLATED}

    def restore_network(self, *, reason: Optional[str] = None) -> dict[str, Any]:
        """Restore a locally saved configuration through an administrator session."""
        self._require_windows()
        record = self.load_saved_configuration()
        if record is None:
            return {"status": "error", "message": "No saved device-isolation state exists."}
        self.record_lifecycle_state(DeviceIsolationState.RESTORING, reason=reason)
        code, output = self._command_runner(
            self._powershell_command(self._restore_script(record["state"]))
        )
        if code != 0:
            self.record_lifecycle_state(
                DeviceIsolationState.ISOLATED, reason=reason, details={"restore_error": output}
            )
            return {"status": "error", "message": output}
        self.record_lifecycle_state(DeviceIsolationState.RESTORED, reason=reason)
        return {"status": "ok", "state": DeviceIsolationState.RESTORED}

    def load_saved_configuration(self) -> Optional[dict[str, Any]]:
        """Return the saved recovery record, or ``None`` if none exists."""
        with _STATE_LOCK:
            if not self.state_path.is_file():
                return None
            with self.state_path.open("r", encoding="utf-8") as file:
                record = json.load(file)
        if not isinstance(record, dict) or record.get("version") != 1:
            raise ValueError("Saved device-isolation state has an invalid format.")
        record["state"] = self._normalise_state(record.get("state"))
        return record

    def record_lifecycle_state(
        self,
        state: str,
        *,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Persist one state transition and append an administrator audit event.

        This method only records intent and outcome; it does not itself invoke
        networking commands.
        """
        if state not in DeviceIsolationState.ALL:
            raise ValueError(f"Unsupported device-isolation state: {state!r}")
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "reason": reason,
            "details": details or {},
        }
        with _STATE_LOCK:
            self._write_json_atomically(self.status_path, event)
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(json.dumps(event, ensure_ascii=False) + "\n")
            try:
                os.chmod(self.audit_path, 0o600)
            except OSError:
                pass
        return event

    def get_lifecycle_state(self) -> Optional[dict[str, Any]]:
        """Return the latest persisted lifecycle state, if one exists."""
        with _STATE_LOCK:
            if not self.status_path.is_file():
                return None
            with self.status_path.open("r", encoding="utf-8") as file:
                status = json.load(file)
        if not isinstance(status, dict) or status.get("state") not in DeviceIsolationState.ALL:
            raise ValueError("Saved device-isolation lifecycle state has an invalid format.")
        return status
