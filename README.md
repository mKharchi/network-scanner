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
| `DISCONNECT_PING_TIMEOUT_SECONDS` | `3` | Timeout per packet for the two-packet client reachability ping |
| `NETWORK_SCAN_STORAGE_DIR` | `server/storage/network_scans` | Directory for completed scan-result JSON files |
| `NETWORK_CLIENT_OBSERVATION_MAX_AGE_SECONDS` | `3600` | Maximum age of client ARP observations included in a server scan |
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

### Manual LAN Discovery Aggregation

Network discovery is performed entirely on the monitoring clients. Each
client reads its local ARP/neighbour table at startup and periodically sends a
snapshot to the server. Before reporting, the client resolves hostnames with
its local DNS/mDNS and looks up vendors in its local OUI database. The server
only merges recent client reports; it does not transmit ARP, ping, Nmap, DNS,
or mDNS discovery traffic.

Run it directly from the `server/` directory:

```bash
python scanner.py
```

Or select **Merge client network-discovery reports** from the server CLI. The
result contains reports no older than
`NETWORK_CLIENT_OBSERVATION_MAX_AGE_SECONDS`.

Completed discovery results are saved as timestamped JSON files under
`server/storage/network_scans/` by default. Set `NETWORK_SCAN_STORAGE_DIR` to
use a different storage location.

Each client reports one full neighbour snapshot per local day. DHCP
interceptions are not stored as database neighbour observations; instead, they
append to that day's readable audit file, `network_scan_YYYY-MM-DD.json`.
That file contains both the once-daily snapshot for each client and every DHCP
event received that day.

During aggregation, each discovered MAC is compared in one database query with
the registered `clients` table. Results use `MANAGED`, `UNMANAGED`, or
`UNKNOWN` classification. A database lookup failure is `UNKNOWN`, not an
unmanaged-device finding. Managed records reuse the client agent's hostname
and OS information before any network lookup is attempted.

The legacy server-local ARP and OS-detection functions remain in the codebase
for compatibility, but are not invoked by the server or the standalone scan
command.

---

## Client Setup & Running

The client is completely decoupled from MySQL and only requires standard Python libraries plus `psutil`.

### 1. Client Configuration

Configure the server connection via environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `SERVER_IP` | `127.0.0.1` | IP address of the monitoring server |
| `SERVER_PORT` | `5000` | Port of the monitoring server |
| `NETWORK_NEIGHBOUR_HOSTNAME_LOOKUP_LIMIT` | `64` | Maximum neighbours whose hostname is resolved per client report (`0` disables it) |
| `NETWORK_OUI_DATABASE` | detected local files | Optional client-specific OUI database for vendor lookups |
| `DHCP_LISTEN_INTERFACE` | system default | Optional interface for passive DHCP capture on a multi-homed client |

### 2. Install & Run Client

```bash
cd client
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the client
python client.py
```

Passive DHCP observation uses Scapy packet capture. The process needs the same
packet-capture permission as the standalone listener (for example, run it with
the appropriate administrator/root capability on the monitoring client).
On Windows, install the Npcap driver before running the client; it supplies
the capture interface used by Scapy. It is a system driver, not a Python
package named `winpcap`.

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
