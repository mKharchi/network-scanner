"""Subnet scope filtering for the distributed-capture phase (v2 §6).

Each client can be assigned one or more CIDR ranges by the server at connect
time. The filter rule is:

    keep = (src_ip IN observation_scope) OR (dst_ip IN observation_scope)

This must be applied right after protocol classification, before writing to
per-protocol packet files and before flow aggregation (v2 §6).

Fail-open behavior: until the server assigns a scope (e.g. on first ever
connect, or for single-client dev/test setups that never call
``save_scope_config``), the filter keeps everything — this preserves the V1
single-client behavior instead of silently dropping all telemetry.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("scope_filter")

CLIENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCOPE_CONFIG_PATH = CLIENT_ROOT / "storage" / "scope_config.json"

_WRITE_LOCK = threading.RLock()


def _parse_cidr_list(raw_values: Any) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a list of CIDR strings, silently skipping invalid entries."""
    networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    if not isinstance(raw_values, list):
        return networks
    for value in raw_values:
        if not isinstance(value, str):
            continue
        try:
            networks.append(ipaddress.ip_network(value.strip(), strict=False))
        except ValueError:
            LOG.warning("[SCOPE_FILTER] Ignoring invalid CIDR: %r", value)
    return networks


def save_scope_config(
    observation_scope: List[str], *, path: Path | str = DEFAULT_SCOPE_CONFIG_PATH
) -> None:
    """Persist the server-assigned observation scope locally (survives restarts)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        fd, temp_path = tempfile.mkstemp(
            prefix=".scope_config_", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"observation_scope": observation_scope or []}, handle)
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


def load_scope_config(path: Path | str = DEFAULT_SCOPE_CONFIG_PATH) -> List[str]:
    """Load the persisted observation scope, or an empty list if unset/unreadable."""
    target = Path(path)
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        scope = data.get("observation_scope")
        return scope if isinstance(scope, list) else []
    except (OSError, json.JSONDecodeError):
        return []


class ScopeFilter:
    """Keeps a packet if either src_ip or dst_ip is within the assigned CIDR scope.

    Fail-open when the scope list is empty (no assignment received yet).
    """

    def __init__(self, observation_scope: Optional[List[str]] = None):
        self._lock = threading.RLock()
        self._networks = _parse_cidr_list(observation_scope or [])

    def set_scope(self, observation_scope: Optional[List[str]]) -> None:
        """Replace the active server-assigned scope without restarting capture."""
        networks = _parse_cidr_list(observation_scope or [])
        with self._lock:
            self._networks = networks

    @property
    def is_configured(self) -> bool:
        with self._lock:
            return bool(self._networks)

    def keep(self, src_ip: Optional[str], dst_ip: Optional[str]) -> bool:
        """Return True if the packet should be retained under the current scope."""
        with self._lock:
            networks = tuple(self._networks)
        if not networks:
            # Fail-open: no scope assigned yet, or intentionally unrestricted.
            return True
        for ip_str in (src_ip, dst_ip):
            if not ip_str:
                continue
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            for network in networks:
                if addr.version == network.version and addr in network:
                    return True
        return False

    def keep_observation(self, observation: Dict[str, Any]) -> bool:
        """Convenience wrapper for a normalized packet_extractor observation dict."""
        if not isinstance(observation, dict):
            return True
        return self.keep(observation.get("src_ip"), observation.get("dst_ip"))

    @classmethod
    def from_env_or_file(
        cls,
        *,
        env_var: str = "NETWORK_OBSERVATION_SCOPE",
        config_path: Path | str = DEFAULT_SCOPE_CONFIG_PATH,
    ) -> "ScopeFilter":
        """Build a filter from an env var override (comma-separated CIDRs) or the persisted config file."""
        env_value = os.getenv(env_var)
        if env_value:
            cidrs = [part.strip() for part in env_value.split(",") if part.strip()]
            return cls(cidrs)
        return cls(load_scope_config(config_path))
