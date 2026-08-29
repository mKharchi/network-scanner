"""Validate and persist client-provided network-neighbour observations."""

import ipaddress
import logging
import os
import re
from datetime import datetime, timedelta, timezone

try:
    from database import get_connection
except ImportError:
    from ..database import get_connection


LOGGER = logging.getLogger(__name__)
MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
MAX_NEIGHBOURS_PER_REPORT = 1024
DEFAULT_CLIENT_OBSERVATION_MAX_AGE_SECONDS = 604800


def _normalise_mac_address(value):
    if not isinstance(value, str):
        return None
    mac_address = value.strip().replace("-", ":").upper()
    if not MAC_ADDRESS_PATTERN.fullmatch(mac_address):
        return None
    first_octet = int(mac_address[:2], 16)
    return None if mac_address == "FF:FF:FF:FF:FF:FF" or first_octet & 1 else mac_address


def _normalise_metadata(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 255 or any(character in "\r\n\x00" for character in value):
        return None
    return value


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
        record = {
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
        hostname = _normalise_metadata(neighbour.get("hostname"))
        if hostname:
            record["hostname"] = hostname
        vendor = _normalise_metadata(neighbour.get("vendor"))
        if vendor:
            record["vendor"] = vendor
        sources = neighbour.get("sources")
        if not isinstance(sources, list):
            sources = [neighbour.get("source")]
        sources = [source for source in sources if source in {"arp", "dhcp"}]
        if sources:
            record["sources"] = list(dict.fromkeys(sources))
        validated.append(record)
    return validated


def _resolve_neighbour_observed_at(neighbour, batch_observed_at):
    """Prefer a neighbour's own timestamp; fall back to the batch receipt time."""
    from server_components.device_recency import coerce_datetime

    batch = batch_observed_at or datetime.now(timezone.utc).replace(tzinfo=None)
    if not isinstance(neighbour, dict):
        return batch
    parsed = coerce_datetime(neighbour.get("observed_at"))
    if parsed is None:
        return batch
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _upsert_device(cursor, neighbour, observed_at):
    cursor.execute(
        """
        INSERT INTO network_devices (
            mac_address, ip_address, hostname, vendor, first_seen, last_seen
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            ip_address = VALUES(ip_address),
            hostname = COALESCE(VALUES(hostname), hostname),
            vendor = COALESCE(VALUES(vendor), vendor),
            last_seen = GREATEST(last_seen, VALUES(last_seen)),
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            neighbour["mac_address"],
            neighbour["ip_address"],
            neighbour.get("hostname"),
            neighbour.get("vendor"),
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
    return device[0]


def _store_observations(reporter_mac, neighbours, source_type, *, observed_at=None):
    """Store normalized device records from one trusted discovery source."""
    batch_observed_at = observed_at or datetime.now(timezone.utc).replace(tzinfo=None)

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        reporter_client_id = None
        reporter_sensor_id = None
        if reporter_mac:
            cursor.execute("SELECT id FROM clients WHERE mac = %s", (reporter_mac,))
            reporter = cursor.fetchone()
            if not reporter:
                raise ValueError("reporting client is not registered")
            reporter_client_id = reporter[0]

            # A located reporting client is also a physical endpoint sensor.
            # Keep the observation linked to that sensor so spatial consumers
            # can use its coordinates and sensor identity directly.
            cursor.execute(
                "SELECT id FROM sensors WHERE client_id = %s LIMIT 1",
                (reporter_client_id,),
            )
            sensor = cursor.fetchone()
            reporter_sensor_id = sensor[0] if sensor else None
            if reporter_sensor_id is None:
                LOGGER.warning(
                    "No sensor is registered for reporting client %s; "
                    "observation will retain its client attribution only.",
                    reporter_mac,
                )

        updated_device_ids = set()
        for neighbour in neighbours:
            item_observed_at = _resolve_neighbour_observed_at(neighbour, batch_observed_at)
            device_id = _upsert_device(cursor, neighbour, item_observed_at)
            updated_device_ids.add(device_id)
            rssi = neighbour.get("rssi")
            switch_port = neighbour.get("switch_port")
            cursor.execute(
                """
                INSERT INTO network_device_observations (
                    device_id, source_type, source_client_id, sensor_id, ip_address,
                    interface_name, entry_type, observed_at, rssi, switch_port
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    device_id,
                    source_type,
                    reporter_client_id,
                    reporter_sensor_id,
                    neighbour["ip_address"],
                    neighbour.get("interface"),
                    neighbour["entry_type"],
                    item_observed_at,
                    rssi,
                    switch_port,
                ),
            )
        connection.commit()

        # Trigger spatial and rogue evaluation for newly observed devices
        try:
            from server_components import spatial_engine
            for dev_id in updated_device_ids:
                spatial_engine.evaluate_device_spatial_and_rogue_status(dev_id, conn=connection)
        except Exception as spatial_err:
            LOGGER.warning("Spatial triangulation evaluation skipped: %s", spatial_err)

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


def _schedule_location_retries_for_neighbours(neighbours):
    """Retry pending managed-client localization after fresh sensor evidence."""
    macs = [
        _normalise_mac_address(neighbour.get("mac_address"))
        for neighbour in neighbours
        if isinstance(neighbour, dict)
    ]
    macs = list(dict.fromkeys(mac for mac in macs if mac))
    if not macs:
        return

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        placeholders = ", ".join(["%s"] * len(macs))
        cursor.execute(
            f"""
            SELECT client_id
            FROM clients
            WHERE mac IN ({placeholders})
              AND location_id IS NULL
            """,
            macs,
        )
        client_ids = [row[0] for row in cursor.fetchall()]
    except Exception as error:
        LOGGER.warning("Could not identify clients for automatic localization retry: %s", error)
        return
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    if not client_ids:
        return
    try:
        from server_components.client_localization import (
            schedule_automatic_client_location_assignment,
        )
        for client_id in client_ids:
            schedule_automatic_client_location_assignment(client_id)
    except Exception as error:
        LOGGER.warning("Could not schedule automatic localization retry: %s", error)


def store_client_neighbour_observations(reporter_mac, neighbours, *, observed_at=None):
    """Upsert devices and append immutable observations from one client report."""
    reporter_mac = _normalise_mac_address(reporter_mac)
    if not reporter_mac:
        raise ValueError("reporting client MAC is invalid")
    stored = _store_observations(
        reporter_mac, neighbours, "CLIENT_ARP", observed_at=observed_at
    )
    _schedule_location_retries_for_neighbours(neighbours)
    LOGGER.info(
        "Stored %d client ARP observation(s) from reporting client %s.",
        stored,
        reporter_mac,
    )
    return stored


def store_client_dhcp_observations(reporter_mac, neighbours, *, observed_at=None):
    """Upsert devices and append immutable observations from one client DHCP report."""
    reporter_mac = _normalise_mac_address(reporter_mac)
    if not reporter_mac:
        raise ValueError("reporting client MAC is invalid")
    stored = _store_observations(
        reporter_mac, neighbours, "CLIENT_DHCP", observed_at=observed_at
    )
    _schedule_location_retries_for_neighbours(neighbours)
    LOGGER.info(
        "Stored %d client DHCP observation(s) from reporting client %s.",
        stored,
        reporter_mac,
    )
    return stored


def store_client_neighbourhood_observations(reporter_mac, neighbours, *, observed_at=None):
    """Persist one accumulated local-neighbourhood report with source fidelity.

    A device observed by both ARP and DHCP is represented by one device row and
    two immutable source-attributed observation rows.  This preserves the
    useful discovery provenance while later merge operations still correlate
    the physical device by MAC address.
    """
    reporter_mac = _normalise_mac_address(reporter_mac)
    if not reporter_mac:
        raise ValueError("reporting client MAC is invalid")

    arp_neighbours = []
    dhcp_neighbours = []
    for neighbour in neighbours:
        if not isinstance(neighbour, dict):
            continue
        sources = neighbour.get("sources") or [neighbour.get("source")]
        if not isinstance(sources, list):
            sources = []
        if "dhcp" in sources:
            dhcp_neighbours.append(neighbour)
        if "arp" in sources or not sources:
            arp_neighbours.append(neighbour)

    if arp_neighbours:
        _store_observations(
            reporter_mac, arp_neighbours, "CLIENT_ARP", observed_at=observed_at
        )
    if dhcp_neighbours:
        _store_observations(
            reporter_mac, dhcp_neighbours, "CLIENT_DHCP", observed_at=observed_at
        )
    _schedule_location_retries_for_neighbours(neighbours)
    LOGGER.info(
        "Stored %d client neighbourhood device(s) from %s (%d ARP, %d DHCP source rows).",
        len(neighbours),
        reporter_mac,
        len(arp_neighbours),
        len(dhcp_neighbours),
    )
    return len(neighbours)


def store_daily_network_scan_reference(file_path, *, observed_at=None):
    """Upsert the one database reference for a server-local daily JSON file."""
    if not isinstance(file_path, str) or not file_path.strip() or len(file_path) > 512:
        raise ValueError("daily network scan file path is invalid")
    observed_at = observed_at or datetime.now(timezone.utc)
    scan_date = (
        observed_at.astimezone().date()
        if observed_at.tzinfo is not None
        else observed_at.date()
    )

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO daily_network_scan_files (scan_date, file_path)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE file_path = VALUES(file_path)
            """,
            (scan_date, file_path.strip()),
        )
        connection.commit()
    except Exception:
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def store_server_scan_observations(devices, *, observed_at=None):
    """Persist server ARP discoveries as ``SERVER_SCAN`` observations."""
    normalized = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        try:
            ip_address = ipaddress.ip_address(device.get("ip_address"))
        except (TypeError, ValueError):
            continue
        mac_address = _normalise_mac_address(device.get("mac_address"))
        if ip_address.version != 4 or not mac_address:
            continue
        normalized.append(
            {
                "ip_address": str(ip_address),
                "mac_address": mac_address,
                "entry_type": "discovered",
                "interface": None,
            }
        )
    stored = _store_observations(None, normalized, "SERVER_SCAN", observed_at=observed_at)
    LOGGER.info("Stored %d server scan observation(s).", stored)
    return stored


def _read_client_observation_max_age_seconds():
    value = os.getenv(
        "NETWORK_CLIENT_OBSERVATION_MAX_AGE_SECONDS",
        str(DEFAULT_CLIENT_OBSERVATION_MAX_AGE_SECONDS),
    )
    try:
        return max(1, int(value))
    except ValueError:
        LOGGER.warning(
            "Invalid NETWORK_CLIENT_OBSERVATION_MAX_AGE_SECONDS=%r; using %s.",
            value,
            DEFAULT_CLIENT_OBSERVATION_MAX_AGE_SECONDS,
        )
        return DEFAULT_CLIENT_OBSERVATION_MAX_AGE_SECONDS


def get_recent_client_neighbour_observations(*, now=None, max_age_seconds=None):
    """Return the latest fresh observation for every device/client source pair."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    max_age_seconds = (
        _read_client_observation_max_age_seconds()
        if max_age_seconds is None
        else max(1, int(max_age_seconds))
    )
    observed_since = now - timedelta(seconds=max_age_seconds)

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                device.mac_address,
                device.hostname,
                device.vendor,
                observation.source_type,
                observation.ip_address,
                observation.interface_name,
                observation.entry_type,
                observation.observed_at,
                client.id AS source_client_database_id,
                client.client_id AS source_client_id,
                client.hostname AS source_client_hostname
            FROM network_device_observations AS observation
            INNER JOIN network_devices AS device ON device.id = observation.device_id
            LEFT JOIN clients AS client ON client.id = observation.source_client_id
            WHERE observation.source_type IN ('CLIENT_ARP', 'CLIENT_DHCP')
              AND observation.observed_at >= %s
            ORDER BY observation.observed_at DESC
            """,
            (observed_since,),
        )

        observations = []
        seen_sources = set()
        for row in cursor.fetchall():
            mac_address = _normalise_mac_address(row.get("mac_address"))
            if not mac_address:
                continue
            source_client_id = row.get("source_client_id")
            key = (mac_address, source_client_id or "DIRECT", row.get("source_type", "CLIENT"))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            observed_at = row.get("observed_at")
            observations.append(
                {
                    "source_type": row.get("source_type", "CLIENT_ARP"),
                    "ip_address": row.get("ip_address"),
                    "mac_address": mac_address,
                    "hostname": _normalise_metadata(row.get("hostname")),
                    "vendor": _normalise_metadata(row.get("vendor")),
                    "entry_type": row.get("entry_type"),
                    "interface": row.get("interface_name"),
                    "observed_at": (
                        observed_at.replace(tzinfo=timezone.utc).isoformat()
                        if isinstance(observed_at, datetime)
                        else None
                    ),
                    "source_client_database_id": row.get("source_client_database_id"),
                    "source_client_id": source_client_id,
                    "source_client_hostname": row.get("source_client_hostname"),
                }
            )
        LOGGER.info("Loaded %d recent client ARP/DHCP observation(s).", len(observations))
        return observations
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
