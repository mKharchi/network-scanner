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

#### `POST /api/v1/clients/{client_id}/network-neighbourhood`
* **Description:** Requests the connected client to send its accumulated local neighborhood file. The client does not start a scan; accepted observations are persisted and merged before the command completes.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "status": "completed",
      "client_id": "client-e4fd45ba8b96",
      "observations_sent": 12,
      "timeout_seconds": 12.0
    },
    "meta": {}
  }
  ```
* **Timeout Response (504):** `CLIENT_TIMEOUT`. This is isolated to the requested client.
* **Configuration:** `NETWORK_NEIGHBOURHOOD_REQUEST_TIMEOUT` (default `12` seconds).

#### `POST /api/v1/network/neighbourhood/collections`
* **Description:** Starts passive global neighbourhood collection from the current online-client snapshot. Clients are requested in configured concurrent buckets; no client performs an active ARP scan.
* **Success Response:** `202 Accepted` with the collection ID and `status: "started"`. If a collection is already running, returns `200 OK` with `status: "already_running"` and that collection's state.

#### `GET /api/v1/network/neighbourhood/collections/{collection_id}`
* **Description:** Returns collection progress and final partial-success counts, including requested, succeeded, failed, timed-out clients, completed buckets, and MAC-deduplicated `devices_discovered`.

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
* **Status:** Temporarily disabled during the passive-neighborhood collection rollout.
* **Response:** `409 ACTIVE_NETWORK_SCAN_DISABLED`. The endpoint remains reserved for the future passive global-collection operation.

#### `GET /api/v1/network/scans/global-active/{scan_id}`
* **Description:** Legacy status endpoint for previously created active-scan jobs. No new active jobs can be created while the feature is disabled.

#### `GET /api/v1/network/scans/global-active`
* **Description:** Legacy active-scan status endpoint. Returns `404 NOT_FOUND` when no prior job is running.

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

### 2.3b Device Intelligence & ML Classification

#### `GET /api/v1/devices/{device_id}/classification`
* **Description:** Retrieves the active ML/Hybrid device classification, calibrated confidence, probability distribution across classes, model version, and evidence chain.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "device_id": 42,
      "predicted_class": "ANDROID_MOBILE",
      "confidence": 0.94,
      "source": "HYBRID",
      "model_version": "device-classifier-v1",
      "status": "ACTIVE",
      "probabilities": {
        "ANDROID_MOBILE": 0.93,
        "WINDOWS_WORKSTATION": 0.01,
        "APPLE_MOBILE": 0.02,
        "UNKNOWN": 0.04
      },
      "evidence": [
        "rule.android.dhcp_or_vendor_or_hostname",
        "ml.prediction:ANDROID_MOBILE:0.93",
        "decision.consensus_agreement"
      ]
    },
    "meta": {}
  }
  ```

#### `POST /api/v1/devices/{device_id}/classify`
* **Description:** Forces an on-demand reclassification of the device against latest observations and features.
* **Success Response (200 OK):** Same structure as `GET /classification`.

#### `POST /api/v1/devices/{device_id}/label`
* **Description:** Records an administrator verified ground-truth label for the device, immediately updating the classification record (`source='HUMAN'`) and feeding the training ground truth.
* **Request Body:**
  ```json
  {
    "label": "SMART_TV_MEDIA",
    "confirmed_by": "admin",
    "notes": "Verified living room Samsung Smart TV"
  }
  ```
* **Success Response (201 Created):**
  ```json
  {
    "data": {
      "device_id": 42,
      "predicted_class": "SMART_TV_MEDIA",
      "confidence": 1.0,
      "source": "HUMAN",
      "model_version": "device-classifier-v1",
      "status": "ACTIVE",
      "evidence": ["human.verified_label"]
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/classification/review` (or `/api/v1/devices/classification-review`)
* **Description:** Lists devices requiring human verification (low confidence $< 0.70$, rule/ML conflicts, or `UNKNOWN`).
* **Query Parameters:** `limit` (int, default 50).
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "items": [
        {
          "device_id": 15,
          "mac_address": "AA:BB:CC:DD:EE:FF",
          "hostname": "Unknown",
          "vendor": "Espressif",
          "predicted_class": "IOT_DEVICE",
          "confidence": 0.65,
          "source": "HYBRID",
          "status": "NEEDS_REVIEW"
        }
      ],
      "total": 1
    },
    "meta": {}
  }
  ```

#### `GET /api/v1/classification/stats`
* **Description:** Provides summary counts, class distributions, confidence tiers, human label totals, and current model version.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "total_devices": 128,
      "total_classified": 120,
      "class_distribution": {
        "WINDOWS_WORKSTATION": 45,
        "ANDROID_MOBILE": 32,
        "APPLE_MOBILE": 18,
        "PRINTER": 8,
        "SMART_TV_MEDIA": 6,
        "NETWORK_DEVICE": 5,
        "IOT_DEVICE": 4,
        "UNKNOWN": 2
      },
      "high_confidence_count": 98,
      "medium_confidence_count": 18,
      "low_confidence_count": 4,
      "needs_review_count": 5,
      "average_confidence": 0.9124,
      "human_labels_count": 12,
      "model_version": "device-classifier-v1"
    },
    "meta": {}
  }
  ```

#### `POST /api/v1/classification/retrain`
* **Description:** Triggers benchmark evaluation and model version verification against collected human ground truth.
* **Success Response (200 OK):**
  ```json
  {
    "data": {
      "status": "SUCCESS",
      "model_version": "device-classifier-v1",
      "human_labels_count": 12,
      "benchmark_evaluation": { ... }
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

#### `PATCH /api/v1/alerts/{alert_id}`
* **Description:** Acknowledge or resolve an alert.
* **Request Body:** `{ "status": "ACKNOWLEDGED" | "RESOLVED" }`
* **Valid transitions:** `NEW` → `ACKNOWLEDGED` or `RESOLVED`; `ACKNOWLEDGED` → `RESOLVED`.
* **Success Response (200 OK):** Same shape as `GET /api/v1/alerts/{alert_id}`.
* **Error Responses:** `400 INVALID_STATUS` (invalid transition), `404 NOT_FOUND`.

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
