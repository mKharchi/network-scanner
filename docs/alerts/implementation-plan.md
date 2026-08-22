# Network Scanner — Alert Feature Implementation Plan

## 0. Goal and Architecture

The goal is to add an alert system to the existing client/server network-scanner application.

The system has two kinds of alert detection:

1. **Client-side detection**
   - The client periodically collects its activity log.
   - The client scans the newly generated log for suspicious/forbidden processes.
   - If a forbidden process is detected, the client immediately sends an alert to the server.
   - The client should not continuously send the entire activity log to the server.
   - The hourly activity log is mainly used for local detection; the server can request a larger historical log when needed.

2. **Server-side detection**
   - The server detects events based on client connections/disconnections and configuration.
   - When a client registers during working hours, the server creates an informational alert.
   - When a client registers outside working hours, the server creates a warning/security alert.
   - When a client disconnects, the server initially creates an informational "client disconnected" event.
   - The server then checks whether the machine is actually unreachable:
     - Ping fails -> likely machine shutdown/offline. Keep this as an informational event.
     - Ping succeeds -> the client program stopped unexpectedly. Create a warning/security alert.
   - The server owns the final alert storage and display.

3. **Future monitoring**
   - The client can periodically monitor CPU/network/resource usage.
   - If configured thresholds are exceeded for a meaningful duration, the client can send an alert.
   - This should be added only after the basic alert pipeline is stable.

### Existing database concepts

The existing schema contains:

- `clients`
- `connections`
- `activity_logs`
- `alerts`
- `forbidden_processes`
- `working_hours`

The `alerts` table already supports:

- client
- optional activity-log reference
- alert type
- severity
- detection time
- optional activity time
- title
- description
- status (`NEW`, `ACKNOWLEDGED`, `RESOLVED`)

Do not redesign the database unless implementation reveals a concrete missing requirement.

---

# STEP 1 — Process Alerts

## Objective

Implement client-side detection of forbidden processes from the activity log.

The client should generate an activity log approximately every hour, scan that log for forbidden processes, and send only newly detected alerts to the server.

---

## Step 1.1 — Define the forbidden-process model

Use the existing `forbidden_processes` table.

Each forbidden process has:

- `process_name`
- `severity`
- `enabled`
- `description`

The server/database is the source of truth for the forbidden-process configuration.

Do not hard-code the forbidden-process list into the client unless there is a temporary fallback explicitly required by the existing architecture.

Decide how the client obtains the enabled forbidden-process list:

- preferably through a server command/request after registration;
- optionally cache the configuration locally;
- refresh it periodically or when the server changes configuration.

The client should only scan against enabled rules.

---

## Step 1.2 — Implement the hourly activity-log generation

Create a client-side scheduler responsible for periodic activity collection.

Expected behavior:

1. At startup, initialize the activity-monitoring scheduler.
2. Generate/collect the activity log for the relevant period.
3. Store the current hourly log locally.
4. Replace/overwrite the previous hourly log rather than continuously accumulating the same data.
5. After generating the log, trigger the process-alert scanner.
6. Repeat approximately every hour.

The scheduler must not block the client's socket command loop.

Use a background thread/timer or another non-blocking mechanism compatible with the existing client architecture.

The existing `get_activity_log()` function should remain responsible for collecting activity data.

Do not duplicate the browser/history/shell parsing logic.

---

## Step 1.3 — Define the hourly log file format

Use a structured format such as JSON.

Example conceptual structure:

{
    "period": "1h",
    "generated_at": "2026-08-16 14:00:00",
    "client": {
        "hostname": "...",
        "mac": "..."
    },
    "activity": [
        {
            "time": "2026-08-16 13:42:10",
            "type": "Process",
            "detail": "..."
        }
    ]
}

The exact structure should be adapted to the existing activity-log implementation.

Important:

- Keep timestamps.
- Keep activity type.
- Keep process/detail information required for detection.
- Make the file easy for the scanner to parse.
- Avoid storing unnecessary duplicated information.

---

## Step 1.4 — Implement the process scanner

Create a dedicated function/module for scanning the hourly log.

Conceptually:

scan_process_alerts(log_file, forbidden_processes)

The scanner should:

1. Load the current hourly log.
2. Extract process-related activities.
3. Compare process names/details against enabled forbidden-process rules.
4. Produce an alert candidate for every newly detected forbidden process.
5. Include enough information for the server to create an alert.

An alert candidate should contain information equivalent to:

- process name
- severity
- description
- activity timestamp
- alert title
- alert description
- detection timestamp
- optionally the relevant activity entry

Do not immediately insert the alert into MySQL from the client.

The client only detects and reports it.

---

## Step 1.5 — Prevent duplicate alerts

This is important because the hourly scan may encounter the same activity more than once.

The client should keep enough state to avoid repeatedly sending the same event.

A practical event identity can be based on something such as:

- process name
- activity timestamp
- activity detail

or a hash generated from those fields.

Store the IDs/hashes of recently reported events locally.

Do not make the client permanently store an unlimited history.

Keep only enough state to prevent duplicates across the relevant monitoring window.

---

## Step 1.6 — Define the client-to-server alert message

Add a dedicated protocol message for alerts.

For example:

{
    "type": "ALERT",
    "alert": {
        "alert_type": "FORBIDDEN_PROCESS",
        "severity": "HIGH",
        "title": "Forbidden process detected",
        "description": "...",
        "process_name": "...",
        "activity_time": "...",
        "detected_at": "..."
    }
}

The exact field names should follow the existing protocol conventions.

Important:

- Do not send the entire log file with every alert.
- Send the minimum information required to identify and display the alert.
- The server should remain responsible for persistent alert storage.

---

## Step 1.7 — Handle alert messages on the server

Extend the server's client-message handling so that:

`type == "ALERT"`

is handled separately from normal command responses.

When an alert is received:

1. Validate the message.
2. Identify the client from its active connection/MAC/client ID.
3. Validate the alert type.
4. Validate severity against the allowed values.
5. Store the alert in the `alerts` table.
6. Display the alert in the server console.
7. Do not crash the client connection if the alert payload is malformed.

The server should never blindly trust severity or other security-sensitive fields sent by a client.

---

## Step 1.8 — Decide how `log_id` is handled

For the first implementation, the hourly client alert does not necessarily need to reference an `activity_logs` database row because the complete hourly log is stored as a file.

If the current architecture stores the hourly log file in `activity_logs`, then:

- store the log file first;
- obtain its database `activity_logs.id`;
- associate the alert with that `log_id`.

If the log has not yet been stored on the server, allow `log_id` to remain `NULL`.

Do not introduce unnecessary database duplication just to populate `log_id`.

---

## Step 1.9 — Testing for Step 1

Test at least these cases:

### Case A — No forbidden process

- Generate hourly log.
- Scan it.
- No forbidden process.
- No alert sent.

### Case B — Forbidden process detected

- Add a test process to `forbidden_processes`.
- Generate a log containing that process.
- Scanner detects it.
- Client sends one `FORBIDDEN_PROCESS` alert.
- Server stores it.
- Server displays it.

### Case C — Same event scanned twice

- Scan the same log twice.
- Only one alert should be sent.

### Case D — Disabled forbidden process

- Set `enabled = FALSE`.
- Generate matching activity.
- No alert should be generated.

### Case E — Different severities

Verify that `LOW`, `MEDIUM`, `HIGH`, and `CRITICAL` rules are preserved correctly.

### Case F — Malformed alert

Send an invalid alert payload to the server.

Expected:

- server rejects/logs the invalid message;
- server continues running;
- client connection remains stable if possible.

---

# STEP 2 — Connection / Registration Alerts

## Objective

Add server-side alerts for client registration.

### Step 2.1 — Detect registration

When a client successfully registers, the server already knows:

- client identity
- hostname
- IP
- MAC
- registration time

Use this event as the trigger.

### Step 2.2 — Load working hours

Use the existing `working_hours` table.

Determine:

- current day
- current server time
- configured working interval
- whether working hours are enabled

Do not hard-code working hours into the alert logic.

### Step 2.3 — Normal connection

If the client registers during working hours:

Create an informational alert:

- type: `CLIENT_CONNECTED`
- severity: `LOW`
- title similar to: `Client connected`
- description: identify the client and connection time
- status: `NEW`

### Step 2.4 — Connection outside working hours

If the client registers outside working hours:

Create a warning/security alert:

- type: `CONNECTION_OUTSIDE_WORKING_HOURS`
- severity determined by the chosen policy, initially `MEDIUM`
- title: `Client connected outside working hours`
- description containing client and timestamp

### Step 2.5 — Display and test

The server should display the generated alert immediately.

Test:

- connection during working hours;
- connection outside working hours;
- disabled working-hours configuration;
- boundary times such as exactly at start/end.

---

# STEP 3 — Disconnect Alerts and Client-Process Failure Detection

## Objective

Differentiate between:

1. machine becoming unreachable;
2. client program stopping while the machine remains reachable.

### Step 3.1 — Detect disconnect

When the TCP connection is lost:

Create an informational event:

- type: `CLIENT_DISCONNECTED`
- severity: `LOW`
- title: `Client disconnected`

### Step 3.2 — Ping the client

Use the client's known IP address.

After disconnection:

1. wait a short configurable period;
2. ping the client;
3. interpret the result.

Do not immediately classify every TCP disconnect as a security problem.

### Step 3.3 — Machine unreachable

If ping fails:

Interpret this as likely:

- shutdown;
- network disconnection;
- machine unavailable.

Keep the event informational unless later requirements introduce a different policy.

### Step 3.4 — Client program stopped

If ping succeeds:

Interpret this as:

- machine is reachable;
- client application is no longer connected.

Create a warning/security alert:

- type: `CLIENT_AGENT_STOPPED`
- severity: `HIGH` initially
- title: `Client agent stopped`
- description: client machine remains reachable but the monitoring client is disconnected.

### Step 3.5 — Avoid false positives

Do not generate multiple alerts for the same disconnect.

Maintain a clear connection state.

A reconnect should close/resolve or otherwise logically follow the previous disconnect state according to the chosen alert policy.

---

# STEP 4 — Resource Monitoring Alerts

## Objective

Extend client-side monitoring beyond process activity.

Candidate metrics:

- CPU usage
- memory usage
- network interface traffic/usage
- disk usage
- optionally disk I/O

Start with CPU and network usage.

### Step 4.1 — Define thresholds

Do not hard-code arbitrary thresholds throughout the code.

Create configurable thresholds, for example:

- CPU > X% for Y consecutive measurements
- network traffic > X for Y duration

The exact thresholds should be configurable later.

### Step 4.2 — Periodic monitoring

The client periodically measures the selected resources.

Avoid treating a single CPU spike as an alert.

Require a sustained threshold breach.

### Step 4.3 — Alert generation

When a threshold is exceeded:

- create an alert candidate;
- include metric name;
- observed value;
- threshold;
- duration;
- timestamp;
- severity.

### Step 4.4 — Deduplication / cooldown

Do not send an alert every measurement while the threshold remains exceeded.

Use a cooldown or state transition model:

NORMAL -> THRESHOLD_EXCEEDED -> ALERT_SENT -> STILL_EXCEEDED -> RECOVERED

This prevents alert flooding.

---

# STEP 5 — Central Alert Manager on the Server

## Objective

Avoid spreading alert insertion/display logic across `server_lib.py`.

Create a dedicated server-side alert component.

Possible responsibility:

`alert_manager.py`

It should provide operations conceptually similar to:

- `create_alert(...)`
- `handle_client_alert(...)`
- `handle_connection_alert(...)`
- `handle_disconnect_alert(...)`
- `list_alerts(...)`
- `acknowledge_alert(...)`
- `resolve_alert(...)`

The existing server code should call this component rather than directly manipulating the `alerts` table everywhere.

This gives the project an Observer/Event-driven structure without unnecessarily implementing a complicated framework.

---

# STEP 6 — Alert Persistence and Management

## Objective

Make alerts useful after the server restarts.

Implement:

- database persistence;
- listing alerts;
- filtering by client;
- filtering by severity;
- filtering by status;
- filtering by alert type;
- ordering by detection time.

Add server menu options such as:

1. List recent alerts
2. List alerts for a client
3. Filter by severity
4. Acknowledge alert
5. Resolve alert

Do not modify the database schema unless required.

---

# STEP 7 — Historical Activity Logs

## Objective

Keep the large activity log separate from the alert stream.

The architecture should be:

CLIENT
    |
    | hourly activity log
    v
LOCAL LOG FILE
    |
    | process scan
    v
ALERT DETECTED
    |
    | small alert message
    v
SERVER
    |
    +--> alerts table
    |
    +--> optional complete log file storage

The server should request/store the larger historical activity log when needed, rather than receiving large logs continuously.

At client registration:

- server may request the last day's activity log;
- client sends/stores that historical log according to the existing log-transfer design.

This keeps alerts lightweight while preserving forensic/history data.

---

# STEP 8 — Refactor Toward an Event/Observer Architecture

## Objective

Once the individual alert categories work, organize the code around events.

Potential client events:

- `ForbiddenProcessDetected`
- `ResourceThresholdExceeded`
- `ActivityLogGenerated`

Potential server events:

- `ClientConnected`
- `ClientConnectedOutsideWorkingHours`
- `ClientDisconnected`
- `ClientAgentStopped`
- `ClientAlertReceived`

Observers/handlers can react to these events.

Do not implement a complex generic event framework unless it actually simplifies the project.

The important separation is:

    Detection
       |
       v
    Event/Alert
       |
       v
    Handler
       |
       v
    Server persistence + display

This will make adding future alert types easier.

---

# STEP 9 — End-to-End Testing

Test the complete system with multiple clients.

## Process alert

Client starts forbidden process -> hourly scan -> alert -> server -> MySQL -> console.

## Normal connection

Client connects during working hours -> informational alert -> database.

## Suspicious connection

Client connects outside working hours -> warning alert -> database.

## Normal shutdown

Client disconnects -> server pings -> machine unreachable -> informational disconnect event.

## Agent stopped

Kill client application while PC stays online -> server detects successful ping -> warning alert.

## Resource alert

CPU/network exceeds configured threshold for the required duration -> client sends alert -> server stores/displays it.

## Reconnection

Client reconnects after disconnect -> connection state remains consistent and duplicate alerts are avoided.

## Restart

Restart the server -> existing alerts remain available from MySQL.

---

# Implementation Order

Implement strictly in this order:

1. **Process alerts**
   - hourly log generation
   - local log storage
   - forbidden-process configuration
   - log scanning
   - duplicate prevention
   - alert protocol
   - server alert reception
   - database persistence
   - console display

2. **Connection alerts**
   - working-hours evaluation
   - normal connection alert
   - outside-working-hours alert

3. **Disconnect alerts**
   - disconnect detection
   - ping verification
   - machine-offline vs agent-stopped distinction
   - duplicate prevention

4. **Resource monitoring**
   - CPU
   - network
   - thresholds
   - sustained violation detection
   - cooldown/recovery

5. **Central alert manager**
   - consolidate alert creation
   - separate detection from persistence

6. **Alert management**
   - list
   - filter
   - acknowledge
   - resolve

7. **Historical logs**
   - daily log retrieval
   - server-side file storage
   - association with `activity_logs`

8. **Observer/event refactoring**
   - only after functionality is working

9. **End-to-end testing**

---

# Rules for the AI Implementing Each Step

For every step:

1. Inspect the current project before changing code.
2. Reuse the existing socket protocol and length-prefixed JSON communication.
3. Reuse existing functions whenever possible.
4. Do not rewrite unrelated parts of the application.
5. Do not introduce Docker unless explicitly requested.
6. Do not redesign the MySQL schema without explaining why it is necessary.
7. Keep client-side detection separate from server-side persistence.
8. Never send the complete activity log when a small alert message is sufficient.
9. Prevent duplicate alerts.
10. Keep background monitoring non-blocking so the client can still receive server commands.
11. Validate messages received from clients on the server.
12. After each implementation step:
    - run the relevant tests;
    - perform a manual test;
    - explain which files changed;
    - explain how the new flow works;
    - identify any assumptions or remaining issues.
13. Do not implement future steps automatically. Stop after the requested step so the next step can be reviewed independently.

# Prompting Strategy

The main project context should be given once.

Then give the AI only one implementation step at a time.

Example:

"Implement STEP 1 only from ALERT_IMPLEMENTATION_PLAN.md.
First inspect the existing client/server code and explain your intended changes.
Then implement Step 1.1 through Step 1.9.
Do not start Step 2.
Preserve the existing architecture and protocol unless a change is necessary.
Run tests/manual checks and report the result."

After reviewing Step 1, continue with:

"Now implement STEP 2 only from ALERT_IMPLEMENTATION_PLAN.md. Do not implement later steps."

This keeps each change small, reviewable, and easier to debug.
