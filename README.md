# Network Scanner & Management System

A Python-based TCP network monitoring and client management system with full separation between the Client and Server applications.

---

## Project Structure

```text
network-scanner/
├── server/
│   ├── server.py                     # Server entry point (TCP listener + CLI)
│   ├── server_components/            # Server-side submodules
│   │   ├── __init__.py
│   │   ├── server_lib.py             # Client registry, commands, database logic
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
├── scanner.py                        # Standalone ARP network discovery utility
├── .gitignore
└── README.md
```

---

## Server Setup & Running

The server requires **Python 3.9+** and a **MySQL** database.

### 1. Database Configuration

The server automatically initializes tables from `server/scripts.sql` on startup. Configure the MySQL connection via environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DB_HOST` | `localhost` | MySQL hostname or IP |
| `DB_PORT` | `3306` | MySQL port |
| `DB_NAME` | `network_scanner` | Database name |
| `DB_USER` | `scanner` | Database username |
| `DB_PASSWORD` | `scanner_password` | Database password |
| `SERVER_HOST` | `0.0.0.0` | IP to bind the TCP server |
| `SERVER_PORT` | `5000` | Port for the TCP server |

### 2. Install & Run Server

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the server
python server.py
```

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
