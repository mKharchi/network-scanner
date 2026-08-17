"""Validate and persist client-provided network-neighbour observations."""

import ipaddress
import logging
import re
from datetime import datetime, timezone

try:
    from database import get_connection
except ImportError:
    from ..database import get_connection


LOGGER = logging.getLogger(__name__)
MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
MAX_NEIGHBOURS_PER_REPORT = 1024


def _normalise_mac_address(value):
    if not isinstance(value, str):
        return None
    mac_address = value.strip().replace("-", ":").upper()
    if not MAC_ADDRESS_PATTERN.fullmatch(mac_address):
        return None
    first_octet = int(mac_address[:2], 16)
    return None if mac_address == "FF:FF:FF:FF:FF:FF" or first_octet & 1 else mac_address


def validate_neighbour_report(payload):
    """Return safe normalized neighbours or raise ``ValueError``.

    The client timestamp is validated for protocol consistency but is not used
    for presence history: the server's receipt time is authoritative.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    observed_at = payload.get("observed_at")
    if not isinstance(observed_at, str):
        raise ValueError("observed_at must be an ISO-8601 timestamp")
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from error

    neighbours = payload.get("neighbours")
    if not isinstance(neighbours, list):
        raise ValueError("neighbours must be a list")
    if len(neighbours) > MAX_NEIGHBOURS_PER_REPORT:
        raise ValueError(f"neighbours cannot contain more than {MAX_NEIGHBOURS_PER_REPORT} entries")

    validated = []
    for neighbour in neighbours:
        if not isinstance(neighbour, dict):
            continue
        try:
            ip_address = ipaddress.ip_address(neighbour.get("ip_address"))
        except (TypeError, ValueError):
            continue
        mac_address = _normalise_mac_address(neighbour.get("mac_address"))
        entry_type = neighbour.get("entry_type")
        if (
            ip_address.version != 4
            or ip_address.is_multicast
            or ip_address.is_unspecified
            or ip_address.is_loopback
            or ip_address.is_reserved
            or not mac_address
            or entry_type not in {"dynamic", "static"}
        ):
            continue
        validated.append(
            {
                "ip_address": str(ip_address),
                "mac_address": mac_address,
                "entry_type": entry_type,
                "interface": (
                    neighbour["interface"].strip()
                    if isinstance(neighbour.get("interface"), str)
                    and neighbour["interface"].strip()
                    else None
                ),
            }
        )
    return validated


def store_client_neighbour_observations(reporter_mac, neighbours, *, observed_at=None):
    """Upsert devices and append immutable observations from one client report."""
    reporter_mac = _normalise_mac_address(reporter_mac)
    if not reporter_mac:
        raise ValueError("reporting client MAC is invalid")
    observed_at = observed_at or datetime.now(timezone.utc).replace(tzinfo=None)

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM clients WHERE mac = %s", (reporter_mac,))
        reporter = cursor.fetchone()
        if not reporter:
            raise ValueError("reporting client is not registered")
        reporter_client_id = reporter[0]

        for neighbour in neighbours:
            cursor.execute(
                """
                INSERT INTO network_devices (mac_address, ip_address, first_seen, last_seen)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    ip_address = VALUES(ip_address),
                    last_seen = VALUES(last_seen),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    neighbour["mac_address"],
                    neighbour["ip_address"],
                    observed_at,
                    observed_at,
                ),
            )
            cursor.execute(
                "SELECT id FROM network_devices WHERE mac_address = %s",
                (neighbour["mac_address"],),
            )
            device = cursor.fetchone()
            if not device:
                raise RuntimeError("upserted network device could not be read")
            cursor.execute(
                """
                INSERT INTO network_device_observations (
                    device_id, source_type, source_client_id, ip_address,
                    interface_name, entry_type, observed_at
                ) VALUES (%s, 'CLIENT_ARP', %s, %s, %s, %s, %s)
                """,
                (
                    device[0],
                    reporter_client_id,
                    neighbour["ip_address"],
                    neighbour["interface"],
                    neighbour["entry_type"],
                    observed_at,
                ),
            )
        connection.commit()
        LOGGER.info(
            "Stored %d client ARP observation(s) from reporting client %s.",
            len(neighbours),
            reporter_mac,
        )
        return len(neighbours)
    except Exception:
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
