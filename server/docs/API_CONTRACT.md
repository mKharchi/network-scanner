# API Contract Specification — Network Monitoring Console

## 1. Overview & General Conventions

* **Base URL:** `/api/v1`
* **Transport:** HTTP/1.1 (JSON payloads)
* **Standard Success Envelope:**
  ```json
  {
    "data": {},
    "meta": {}
  }
  ```
* **Standard Error Envelope:**
  ```json
  {
    "error": {
      "code": "ERROR_CODE",
      "message": "Human readable explanation"
    }
  }
  ```
* **Timestamps:** ISO-8601 UTC strings (e.g., `2026-08-18T10:00:00+00:00`).
* **MAC Addresses:** Canonical uppercase colon-separated format (e.g., `E4:FD:45:BA:8B:96`).
* **Null Values:** `null` is used for missing/unresolved fields (never fake placeholders like `"Unknown"`).

---

## 2. Endpoints Inventory & Contracts

### 2.1 Dashboard
* **Endpoint:** `GET /api/v1/dashboard`
* **Description:** Provides summary counters, server state, recent alerts, online clients, and latest scan preview.
* **Query Parameters:** None.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "generated_at": "2026-08-18T10:00:00+00:00",
      "clients": {
        "online": 2,
        "offline": 3,
        "total": 5
      },
      "alerts": {
        "new": 4,
        "critical": 1
      },
      "latest_scan": {
        "scan_id": "2026-08-18_09-00-00_123456",
        "completed_at": "2026-08-18T09:00:00+00:00",
        "devices_found": 12
      },
      "dhcp_today": {
        "date": "2026-08-18",
        "observations": 8
      },
      "recent_alerts": [],
      "online_clients": []
    },
    "meta": {}
  }
  ```

---

### 2.2 Managed Clients

#### `GET /api/v1/clients`
* **Description:** Lists registered monitoring client agents.
* **Query Parameters:**
  * `state` (`ONLINE` | `OFFLINE`, optional)
  * `search` (string, searches hostname, IP, MAC, optional)
  * `limit` (integer, default 50)
  * `cursor` (string, optional)
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "items": [
        {
          "id": "client-e4fd45ba8b96",
          "database_id": 1,
          "hostname": "DESKTOP-PC1",
          "ip_address": "192.168.1.50",
          "mac_address": "E4:FD:45:BA:8B:96",
          "os": {
            "system": "Linux",
            "release": "6.8.0",
            "version": "#1 SMP",
            "machine": "x86_64"
          },
          "connection": {
            "state": "ONLINE",
            "last_connected_at": "2026-08-18T08:00:00+00:00",
            "last_disconnected_at": null
          },
          "created_at": "2026-08-15T09:00:00+00:00",
          "updated_at": "2026-08-18T08:00:00+00:00"
        }
      ],
      "next_cursor": null
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/clients/{client_id}`
* **Description:** Detailed view of a single managed client including recent connection history and alert totals.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "client": { ... },
      "recent_connections": [
        {
          "connected_at": "2026-08-18T08:00:00+00:00",
          "disconnected_at": null
        }
      ],
      "alert_counts": {
        "new": 0,
        "total": 3
      },
      "latest_activity_log": {
        "id": 12,
        "client": { "id": "client-e4fd45ba8b96", "hostname": "DESKTOP-PC1" },
        "period": "1d",
        "generated_at": "2026-08-18T07:00:00+00:00",
        "received_at": "2026-08-18T07:00:02+00:00"
      }
    },
    "meta": {}
  }
  ```
* **Error Response:** `404 NOT_FOUND` if `client_id` is unknown.

---

### 2.3 Network Scans & Devices

#### `GET /api/v1/network/scans/latest`
* **Description:** Returns the most recent completed network discovery scan.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "scan": {
        "id": "2026-08-18_09-00-00_123456",
        "completed_at": "2026-08-18T09:00:00+00:00",
        "network": {
          "interface": "eth0",
          "local_ip": "192.168.1.10",
          "network": "192.168.1.0/24",
          "gateway": "192.168.1.1"
        },
        "devices_found": 1,
        "devices": [
          {
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "ip_address": "192.168.1.100",
            "hostname": "Printer-HP",
            "vendor": "HP Inc.",
            "os": { "name": null, "family": null, "confidence": null },
            "classification": "UNMANAGED",
            "is_managed": false,
            "managed_client_id": null,
            "last_observed_at": "2026-08-18T09:00:00+00:00",
            "sources": ["CLIENT_ARP"]
          }
        ]
      }
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/network/scans`
* **Description:** Retrieves list of historical scan summaries.
* **Query Parameters:** `from` (YYYY-MM-DD), `to` (YYYY-MM-DD), `limit` (int), `cursor`.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "items": [
        {
          "id": "2026-08-18_09-00-00_123456",
          "completed_at": "2026-08-18T09:00:00+00:00",
          "devices_found": 12,
          "network": { ... }
        }
      ],
      "next_cursor": null
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/network/scans/{scan_id}`
* **Description:** Returns full device list and metadata for a specific scan ID.
* **Success Response (200 OK):** Same structure as `/scans/latest`.

#### `POST /api/v1/network/scans/global-active`
* **Description:** Starts a server-managed active ARP scan across the clients that are online at request time. The response does not wait for ARP results.
* **Success Response (202 Accepted):**
  ```json
  {
    "data": {
      "id": "global-20260819143000-a1b2c3d4",
      "status": "started",
      "total_clients": 25,
      "max_concurrent_clients": 5,
      "started": 0,
      "completed": 0,
      "failed": 0,
      "running": 0,
      "pending": 25,
      "devices_found": 0,
      "started_at": "2026-08-19T14:30:00Z"
    },
    "meta": {}
  }
  ```
* **Already running (200 OK):** Returns the active job with `status` set to `already_running`; no second global scan is created.
* **Configuration:** `GLOBAL_NETWORK_SCAN_MAX_CONCURRENT_CLIENTS` (default `5`), `GLOBAL_NETWORK_SCAN_COMMAND_TIMEOUT` (default `10` seconds), and `GLOBAL_NETWORK_SCAN_TIMEOUT` (default `120` seconds).

#### `GET /api/v1/network/scans/global-active/{scan_id}`
* **Description:** Returns progress for a global client scan, including `pending`, `running`, `completed`, `failed`, `skipped`, and MAC-deduplicated `devices_found` counters.
* **Success Response (200 OK):** Same job structure returned by `POST /network/scans/global-active`, with `updated_at` and `finished_at` fields.

#### `GET /api/v1/network/scans/global-active`
* **Description:** Returns the currently active global client scan. Returns `404 NOT_FOUND` when no job is running.

#### `GET /api/v1/network/devices/{mac_address}`
* **Description:** Retrieves detailed observation history and DHCP traces for a specific MAC.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "device": { ... },
      "observations": [
        {
          "source_type": "CLIENT_ARP",
          "source_client_id": "client-e4fd45ba8b96",
          "ip_address": "192.168.1.100",
          "interface": "eth0",
          "entry_type": "dynamic",
          "observed_at": "2026-08-18T09:00:00+00:00"
        }
      ],
      "dhcp_observations": []
    },
    "meta": {}
  }
  ```

---

### 2.4 DHCP Activity

#### `GET /api/v1/network/dhcp`
* **Description:** Returns timeline of passive DHCP packet observations for a specific date.
* **Query Parameters:** `date` (YYYY-MM-DD, defaults to server current date), `reporter_mac` (optional), `limit` (default 100), `cursor`.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "date": "2026-08-18",
      "items": [
        {
          "received_at": "2026-08-18T08:30:00+00:00",
          "reporting_client_mac": "E4:FD:45:BA:8B:96",
          "neighbours": [],
          "dhcp": {
            "message_type": 3,
            "vendor_class": "MSFT 5.0",
            "client_id": "01:e4:fd:45:ba:8b:96"
          }
        }
      ],
      "next_cursor": null
    },
    "meta": {}
  }
  ```

---

### 2.5 Alerts

#### `GET /api/v1/alerts`
* **Description:** Paginated alerts list with multi-criteria filtering.
* **Query Parameters:** `status` (`NEW` | `ACKNOWLEDGED` | `RESOLVED`), `severity` (`LOW` | `MEDIUM` | `HIGH` | `CRITICAL`), `client_id`, `from`, `to`, `limit`, `cursor`.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "items": [
        {
          "id": 101,
          "client": { "id": "client-e4fd45ba8b96", "hostname": "DESKTOP-PC1" },
          "type": "FORBIDDEN_PROCESS",
          "severity": "HIGH",
          "status": "NEW",
          "detected_at": "2026-08-18T09:15:00+00:00",
          "activity_time": "2026-08-18T09:14:50+00:00",
          "title": "Forbidden Process Executed",
          "description": "Process 'discord' was detected running during restricted hours.",
          "activity_log_id": 5
        }
      ],
      "next_cursor": null
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/alerts/{alert_id}`
* **Description:** Single alert details with related client and activity log metadata.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "alert": { ... },
      "client": { ... },
      "activity_log": { ... }
    },
    "meta": {}
  }
  ```

---

### 2.6 Activity Logs

#### `GET /api/v1/activity-logs`
* **Description:** Paginated list of client activity log batch records.
* **Query Parameters:** `client_id`, `period` (`1h` | `1d` | `1w`), `from`, `to`, `limit`, `cursor`.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "items": [
        {
          "id": 5,
          "client": { "id": "client-e4fd45ba8b96", "hostname": "DESKTOP-PC1" },
          "period": "1d",
          "generated_at": "2026-08-18T07:00:00+00:00",
          "received_at": "2026-08-18T07:00:02+00:00"
        }
      ],
      "next_cursor": null
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/activity-logs/{log_id}`
* **Description:** Full timeline content of the activity log loaded safely from the referenced filesystem JSON.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "log": { ... },
      "since": "2026-08-17T07:00:00+00:00",
      "activity": [
        {
          "time": "2026-08-18T06:45:00+00:00",
          "type": "PROCESS_SPAWN",
          "detail": { "name": "code", "pid": 4821 }
        }
      ]
    },
    "meta": {}
  }
  ```

---

### 2.7 Settings & Policies

#### `GET /api/v1/settings/working-hours`
* **Description:** Working hours schedule rules and real-time evaluation status.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "rules": [
        {
          "day_of_week": 0,
          "start_time": "09:30:00",
          "end_time": "18:00:00",
          "enabled": true
        }
      ],
      "current_status": {
        "within_working_hours": true,
        "checked_at": "2026-08-18T10:00:00+00:00"
      }
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/settings/forbidden-processes`
* **Description:** List of banned process rules enforced across clients.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "items": [
        {
          "process_name": "discord",
          "severity": "HIGH",
          "enabled": true,
          "description": "Unauthorized communication client"
        }
      ]
    },
    "meta": {}
  }
  ```

---

## 3. Error Codes Reference
* `NOT_FOUND` (404)
* `BAD_REQUEST` (400)
* `INVALID_QUERY` (400)
* `SCAN_DATA_UNAVAILABLE` (500)
* `LOG_CONTENT_UNAVAILABLE` (410)
* `DHCP_AUDIT_UNAVAILABLE` (500)
* `INTERNAL_ERROR` (500)
