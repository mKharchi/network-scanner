from scapy.all import ARP, Ether, srp
import socket
import subprocess

NETWORK = "172.16.0.0/16"
INTERFACE = "wlp0s20f3"
OUI_DATABASE = "/usr/share/arp-scan/ieee-oui.txt"
def get_mdns_hostname(ip):
    try:
        result = subprocess.run(
            ["avahi-resolve-address", ip],
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            parts = result.stdout.strip().split()

            if len(parts) >= 2:
                return parts[1]

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None

def load_oui_database():
    vendors = {}

    with open(OUI_DATABASE, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            # Ignore comments and empty lines
            if not line or line.startswith("#"):
                continue

            parts = line.split(maxsplit=1)

            if len(parts) != 2:
                continue

            prefix, vendor = parts

            # We only use standard 24-bit OUI entries for now
            if len(prefix) == 6:
                vendors[prefix.upper()] = vendor.strip()

    return vendors


def get_vendor(mac, vendors):
    prefix = mac.replace(":", "").upper()[:6]

    return vendors.get(prefix, "Unknown")

def get_hostname(ip):
    # First: normal reverse DNS
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror):
        pass

    # Second: mDNS
    hostname = get_mdns_hostname(ip)

    if hostname:
        return hostname

    return "Unknown"

def scan_network():
    ethernet = Ether(dst="ff:ff:ff:ff:ff:ff")
    arp = ARP(pdst=NETWORK)

    packet = ethernet / arp

    answered, unanswered = srp(
        packet,
        iface=INTERFACE,
        timeout=3,
        verbose=False
    )
    answered = answered[:10]  # Limit the number of devices to scan to 10
    devices = []
    
    #limit the number of devices to scan to 5
    for _, received in answered:
        ip = received.psrc
        mac = received.hwsrc

        devices.append({
            "ip": ip,
            "mac": mac,
            "hostname": get_hostname(ip)
        })
        

    return devices


if __name__ == "__main__":
    #limit the number of devices to scan to 10
    devices = scan_network()[:10]
    #display the tiùme taken to scan the network
    print(f"Time taken to scan the network: {len(devices)} devices found.")
    
    
    
    print("\nDiscovered devices:")
    print("-" * 110)

    print(
        f"{'IP':16} "
        f"{'MAC':20} "
        f"{'HOSTNAME':25} "
          )

    print("-" * 110)

    for device in devices:
        print(
            f"{device['ip']:16} "
            f"{device['mac']:20} "
            f"{device['hostname']:25} ")
           