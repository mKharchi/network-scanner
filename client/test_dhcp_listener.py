"""
Passive DHCP listener.

This module only observes DHCP traffic visible to the client.
It does not send, modify, or interfere with DHCP traffic.
"""

from scapy.all import sniff, DHCP, BOOTP


def _get_dhcp_option(options, option_name):
    """Return the value of a DHCP option, if present."""
    for option in options:
        if isinstance(option, tuple) and len(option) == 2:
            name, value = option

            if name == option_name:
                return value

    return None


def handle_dhcp_packet(packet):
    """Process one captured DHCP packet."""

    if not packet.haslayer(DHCP) or not packet.haslayer(BOOTP):
        return

    dhcp_layer = packet[DHCP]
    bootp_layer = packet[BOOTP]

    options = dhcp_layer.options

    message_type = _get_dhcp_option(options, "message-type")
    hostname = _get_dhcp_option(options, "hostname")
    requested_ip = _get_dhcp_option(options, "requested_addr")
    vendor_class = _get_dhcp_option(options, "vendor_class_id")
    client_id = _get_dhcp_option(options, "client_id")

    mac_address = bootp_layer.chaddr

    print("\n========== DHCP REQUEST FOUND ==========")
    print(f"MAC:            {mac_address}")
    print(f"Message type:   {message_type}")
    print(f"Requested IP:   {requested_ip}")
    print(f"Hostname:       {hostname}")
    print(f"Vendor class:   {vendor_class}")
    print(f"Client ID:      {client_id}")
    print("========================================\n")


def start_dhcp_listener():
    """Start passively listening for DHCP packets."""

    print("Starting passive DHCP listener...")
    print("Listening for DHCP traffic on UDP ports 67/68...")
    print("Press Ctrl+C to stop.")

    sniff(
        filter="udp and (port 67 or port 68)",
        prn=handle_dhcp_packet,
        store=False,
    )


if __name__ == "__main__":
    start_dhcp_listener()