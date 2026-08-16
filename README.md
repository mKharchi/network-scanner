# Network Scanner & Management System

A Python-based TCP network monitoring and client management system with full separation between the Client and Server applications.

---

## Project Structure

```text
network-scanner/
├── server/
│   ├── server.py                     # Server entry point (TCP listener + CLI)
│   ├── scanner.py                    # One-off server-local LAN discovery command
│   ├── server_components/            # Server-side submodules
│   │   ├── __init__.py
│   │   ├── server_lib.py             # Client registry, commands, database logic
│   │   ├── network_discovery.py      # Dynamic ARP-based LAN discovery
│   │   └── log_storage.py            # Filesystem activity log storage
│   ├── database.py                   # MySQL connection and schema initializer
│   ├── scripts.sql                   # MySQL database schema definition
│   ├── requirements.txt              # Server dependencies (mysql-connector-python)
│   └── storage/                      # Storage folder for raw activity log files
│
├── client/
│   ├── client.py                     # Client entry point (connects & handles commands)
│   ├── client_lib.py                 # System info, process control, log collectors
│   └── requirements.txt              # Client dependencies (psutil)
│
├── .gitignore
└── README.md
```

---

## Server Setup & Running

The server requires **Python 3.9+** and a **MySQL** database.

### 1. Database Configuration

The server automatically initializes tables from `server/scripts.sql` on startup. It
loads `server/.env` automatically; configure the MySQL connection and scanner via
the following environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DB_HOST` | `localhost` | MySQL hostname or IP |
| `DB_PORT` | `3306` | MySQL port |
| `DB_NAME` | `network_scanner` | Database name |
| `DB_USER` | `scanner` | Database username |
| `DB_PASSWORD` | `scanner_password` | Database password |
| `SERVER_HOST` | `0.0.0.0` | IP to bind the TCP server |
| `SERVER_PORT` | `5000` | Port for the TCP server |
| `DISCONNECT_PING_DELAY_SECONDS` | `5` | Grace period before classifying an unexpected client disconnect |
| `DISCONNECT_PING_TIMEOUT_SECONDS` | `3` | Timeout for the single client reachability ping |
| `NETWORK_SCAN_INTERFACE` | detected | Optional IPv4 interface override for local LAN discovery |
| `NETWORK_SCAN_SUBNET` | detected | Optional IPv4 CIDR override for local LAN discovery |
| `NETWORK_SCAN_TIMEOUT_SECONDS` | `3` | ARP response wait time in seconds |
| `NETWORK_SCAN_OUI_DATABASE` | `/usr/share/arp-scan/ieee-oui.txt` | Optional local OUI vendor database |
| `NETWORK_SCAN_STORAGE_DIR` | `server/storage/network_scans` | Directory for completed scan-result JSON files |
| `NETWORK_SCAN_OS_TARGETS` | empty | Comma-separated discovered IPv4 addresses for opt-in OS detection |
| `NETWORK_SCAN_OS_TARGET_LIMIT` | `3` | Maximum number of OS-detection targets per scan |
| `LOG_LEVEL` | `INFO` | Console logging threshold (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### 2. Install & Run Server

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the server
python server.py
```

### Manual LAN Discovery

The server process can perform a best-effort IPv4 ARP scan of its own local
network. It determines the active interface and subnet from `ip route` and
`ip addr`; it does not scan a hard-coded network.

Run it directly from the `server/` directory:

```bash
python scanner.py
```

Or select **Run local network discovery** from the server CLI. ARP scanning
requires the `scapy` dependency installed from `server/requirements.txt` and
permission to send raw packets. Hostname and vendor lookup are optional; a
failure to enrich one device does not fail the scan.

Completed discovery results are saved as timestamped JSON files under
`server/storage/network_scans/` by default. Set `NETWORK_SCAN_STORAGE_DIR` to
use a different storage location.

Before enrichment, each discovered MAC is compared in one database query with
the registered `clients` table. Results use `MANAGED`, `UNMANAGED`, or
`UNKNOWN` classification. A database lookup failure is `UNKNOWN`, not an
unmanaged-device finding. Managed records reuse the client agent's hostname
and OS information before any network lookup is attempted.

OS detection is disabled by default and must be explicitly targeted, for
example `NETWORK_SCAN_OS_TARGETS=172.16.1.232`. It uses the system `nmap`
command (install it separately) and runs only for addresses found by the ARP
scan, capped at three targets by default. Missing Nmap, timeout, permission,
or fingerprint failures leave the OS fields unknown without failing the scan.
Nmap host discovery uses two probes only: ICMP echo and TCP SYN to port 443.

---

## Client Setup & Running

The client is completely decoupled from MySQL and only requires standard Python libraries plus `psutil`.

### 1. Client Configuration

Configure the server connection via environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `SERVER_IP` | `127.0.0.1` | IP address of the monitoring server |
| `SERVER_PORT` | `5000` | Port of the monitoring server |

### 2. Install & Run Client

```bash
cd client
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the client
python client.py
```

---

## Supported Commands

- `GET_SYSTEM_INFO`: Retrieve IP, MAC, hostname, and OS details.
- `GET_NETWORK_INFO`: Retrieve network interfaces and assigned addresses.
- `GET_CPU_INFO`: Retrieve CPU model, core counts, and utilization.
- `GET_MEMORY_INFO`: Retrieve memory statistics and percentage used.
- `GET_DISK_INFO`: Retrieve disk usage and free space.
- `GET_PROCESSES`: Retrieve currently running processes.
- `KILL_PROCESS`: Terminate processes by name.
- `START_PROCESS`: Launch an executable or command.
- `PING`: Verify connectivity with the client.
- `GET_NETWORK_LOG`: Retrieve recent network events (DHCP, Wi-Fi, interfaces).
- `GET_ACTIVITY_LOG`: Collect browser history, opened files, and recent terminal commands.
- `DISCONNECT`: Gracefully disconnect the client.
