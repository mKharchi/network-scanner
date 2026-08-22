"""Classify ARP-discovered devices against registered monitoring clients."""

import logging

try:
    from database import get_connection
except ImportError:
    from ..database import get_connection


LOGGER = logging.getLogger(__name__)


def _normalise_mac_address(mac_address):
    return mac_address.upper() if isinstance(mac_address, str) else None


def get_registered_clients_by_mac(mac_addresses):
    """Return registered client metadata keyed by normalized MAC address.

    A single bulk query is used for the entire scan. ``None`` means the
    database lookup failed, which is distinct from an empty successful lookup.
    """
    normalised_macs = sorted(
        {
            mac_address
            for mac_address in (_normalise_mac_address(mac) for mac in mac_addresses)
            if mac_address
        }
    )
    if not normalised_macs:
        return {}

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        placeholders = ", ".join(["%s"] * len(normalised_macs))
        cursor.execute(
            f"""
            SELECT id, client_id, hostname, mac,
                   os_system, os_release, os_version, os_machine
            FROM clients
            WHERE mac IN ({placeholders})
            """,
            normalised_macs,
        )
        clients_by_mac = {}
        for client in cursor.fetchall():
            mac_address = _normalise_mac_address(client.get("mac"))
            if mac_address:
                clients_by_mac[mac_address] = client
        LOGGER.info(
            "Matched %d registered client(s) from %d discovered MAC address(es).",
            len(clients_by_mac),
            len(normalised_macs),
        )
        return clients_by_mac
    except Exception as error:
        LOGGER.warning("Unable to classify devices from the clients table: %s", error)
        return None
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def classify_devices(devices, *, client_fetcher=None):
    """Mark devices as managed, unmanaged, or unknown without changing identity.

    Registered-client hostname and operating-system details are copied into a
    managed record before subsequent network enrichment runs.
    """
    client_fetcher = client_fetcher or get_registered_clients_by_mac
    clients_by_mac = client_fetcher(
        [device.get("mac_address") for device in devices]
    )
    classified_devices = []

    for device in devices:
        classified_device = dict(device)
        mac_address = _normalise_mac_address(classified_device.get("mac_address"))
        client = clients_by_mac.get(mac_address) if clients_by_mac is not None else None

        if client:
            client_details = {
                "database_id": client.get("id"),
                "client_id": client.get("client_id"),
                "hostname": client.get("hostname"),
                "os_system": client.get("os_system"),
                "os_release": client.get("os_release"),
                "os_version": client.get("os_version"),
                "os_machine": client.get("os_machine"),
            }
            classified_device.update(
                {
                    "classification": "MANAGED",
                    "is_managed": True,
                    "managed_client": client_details,
                    "hostname": client.get("hostname") or classified_device.get("hostname"),
                    "os_name": client.get("os_system") or classified_device.get("os_name"),
                    "os_family": client.get("os_system") or classified_device.get("os_family"),
                    "os_confidence": (
                        1.0
                        if client.get("os_system")
                        else classified_device.get("os_confidence")
                    ),
                }
            )
        elif clients_by_mac is None:
            classified_device.update(
                {
                    "classification": "UNKNOWN",
                    "is_managed": None,
                    "managed_client": None,
                }
            )
        else:
            classified_device.update(
                {
                    "classification": "UNMANAGED",
                    "is_managed": False,
                    "managed_client": None,
                }
            )
        classified_devices.append(classified_device)

    managed_count = sum(device["classification"] == "MANAGED" for device in classified_devices)
    unmanaged_count = sum(device["classification"] == "UNMANAGED" for device in classified_devices)
    LOGGER.info(
        "Device classification completed: %d managed, %d unmanaged, %d unknown.",
        managed_count,
        unmanaged_count,
        len(classified_devices) - managed_count - unmanaged_count,
    )
    return classified_devices
