````md
# Forbidden Process Monitoring & Enforcement — Implementation Plan

## Objective

Upgrade the existing forbidden-process mechanism so that:

1. The client scans for forbidden-process activity every **10 minutes** instead of every hour.
2. The existing log-based detection mechanism remains the primary detection source.
3. When a forbidden process/activity is detected:
   - Determine whether the corresponding process is currently running.
   - If it is running, terminate it.
   - Report the detection and enforcement result to the server.
4. Prevent duplicate alerts for the same event.
5. Allow administrators/server users to **add, update, and remove forbidden processes** through the backend API and UI.
6. Keep the existing client/server architecture and avoid breaking the current startup scan.

---

# Phase 1 — Inspect the Existing Implementation

Before modifying anything, inspect the entire existing forbidden-process flow.

### Backend

Identify:

- `ForbiddenProcess` model.
- Database fields.
- Existing serializers.
- Existing views/viewsets.
- Existing URLs/routes.
- Existing client registration/synchronization endpoint.
- How the forbidden-process list is sent to clients.
- Existing alert model/API.
- Existing authentication/authorization rules.
- Existing frontend pages/components related to administration.

### Client

Identify:

- Current forbidden-process scanner.
- Startup scan implementation.
- Hourly scan implementation.
- Log file generation.
- Log parsing logic.
- Current forbidden-process matching logic.
- Client-side cached forbidden-process list.
- Existing process-management utilities.
- Existing communication mechanism for sending alerts.
- How the client handles server unavailability.
- How the client is started/stopped.

### Important

Do **not** immediately rewrite the scanner.

First understand and preserve the existing behavior.

---

# Phase 2 — Preserve the Existing Detection Logic

The current scanner searches log entries for keywords associated with forbidden processes.

For example:

```text
Forbidden process:
discord
````

If the log contains something such as:

```text
User searched for Discord
```

the current implementation considers this a forbidden-process-related event and alerts the server.

This behavior must remain supported.

## Detection Pipeline

The new architecture should therefore be:

```text
Log File
   |
   v
Log Scanner
   |
   v
Forbidden Keyword Matching
   |
   v
Forbidden Activity Detected
   |
   +----------------------+
   |                      |
   v                      v
Check Active Processes    Create Alert
   |
   v
Process Still Running?
   |
   +--------+---------+
   |                  |
  YES                 NO
   |                  |
   v                  v
Kill Process      Report Detection
   |
   v
Report Detection + Kill Result
```

Do not replace the existing keyword-based detection mechanism with process-name scanning alone.

The two mechanisms serve different purposes:

* **Logs:** detect forbidden activity.
* **Active process list:** determine whether the forbidden application is currently running.

---

# Phase 3 — Change Scan Frequency

Change the periodic scanner from:

```text
Startup
   ↓
Every 1 hour
```

to:

```text
Startup
   ↓
Every 10 minutes
```

The startup scan must remain.

Therefore:

```text
Client starts
      ↓
Scan previous 24 hours
      ↓
Normal client operation
      ↓
Every 10 minutes
      ↓
Scan the appropriate recent log
```

## Important

Do not accidentally scan the entire 24-hour history every 10 minutes.

The startup scan should continue handling historical events.

The periodic scanner should process only newly relevant log data.

---

# Phase 4 — Prevent Duplicate Detection

Because the scanner will run every 10 minutes, it must not repeatedly report the same log entry.

Implement an appropriate mechanism to track processed entries.

Possible approaches:

### Option A — File Offset

Remember the last processed byte/line position.

```text
log file
  |
  +--- processed
  |
  +--- processed
  |
  +--- NEW <--- scan from here
```

### Option B — Event Timestamp

Track the timestamp of the latest processed log entry.

### Option C — Event Fingerprint

Generate a fingerprint from relevant fields:

```text
timestamp
+
event text
+
forbidden process
```

and keep recently processed fingerprints.

Prefer the approach that best matches the existing logging architecture.

Do not introduce a complicated persistence system if the existing scanner already has a reliable mechanism.

---

# Phase 5 — Detect the Forbidden Process

When the log scanner finds a forbidden keyword:

```text
forbidden_process = "discord"
```

record the detection event.

The event should contain enough information to investigate it later.

Suggested structure:

```json
{
    "forbidden_process": "discord",
    "matched_keyword": "discord",
    "log_source": "browser",
    "detected_at": "...",
    "log_entry": "...",
    "client_id": "..."
}
```

Do not assume that the matching keyword is necessarily the exact executable name.

For example:

```text
Forbidden keyword:
discord
```

could correspond to:

```text
Discord.exe
discord.exe
DiscordSetup.exe
```

Therefore process matching should support configurable mappings where appropriate.

---

# Phase 6 — Enumerate Active Processes

After detecting forbidden activity, enumerate the currently running processes on the client.

For each process collect, where safely available:

```text
PID
Process name
Executable name
Executable path (if available)
```

Example:

```text
PID     Name
-----------------------
4120    Discord.exe
1832    chrome.exe
9020    explorer.exe
```

Then compare the detected forbidden process against the active process list.

---

# Phase 7 — Match the Forbidden Activity to an Active Process

Implement case-insensitive process matching.

Example:

```text
Detected keyword:
discord

Running process:
Discord.exe

Result:
MATCH
```

The matching logic should normalize:

* Case.
* `.exe` suffix.
* Whitespace.
* Configured aliases where applicable.

Example:

```text
discord
Discord
Discord.exe
DISCORD.EXE
```

should resolve to the same logical process where appropriate.

Do not use overly broad substring matching without considering false positives.

For example:

```text
discord
```

should not accidentally match:

```text
mydiscordhelper.exe
```

unless explicitly configured.

---

# Phase 8 — Terminate the Forbidden Process

If the forbidden application is still running:

```text
Forbidden activity detected
        ↓
Process enumeration
        ↓
Forbidden process found
        ↓
Terminate process
```

Attempt graceful termination first if the current architecture supports it.

If graceful termination fails, use the existing process-management mechanism for forced termination.

Record:

```text
process_name
PID
termination_attempted
termination_successful
termination_error
timestamp
```

Example:

```json
{
    "process_name": "Discord.exe",
    "pid": 4120,
    "termination_attempted": true,
    "termination_successful": true
}
```

## Important Safety Requirements

Only terminate processes that match the configured forbidden-process rule.

Do not terminate:

* `explorer.exe`
* system processes
* the client agent itself
* the server communication process
* unrelated processes

The client must never kill itself accidentally.

---

# Phase 9 — Alert the Server

After detection, send an alert to the server.

The server should be able to distinguish:

### Detection only

```text
Forbidden activity detected
Process not currently running
```

### Detection + termination

```text
Forbidden activity detected
Process was running
Process terminated successfully
```

### Detection + failed termination

```text
Forbidden activity detected
Process was running
Termination attempted
Termination failed
```

Suggested payload:

```json
{
    "client_id": "client-123",
    "forbidden_process": "discord",
    "detected_at": "...",
    "matched_keyword": "discord",
    "process_detected": true,
    "process_name": "Discord.exe",
    "pid": 4120,
    "termination_attempted": true,
    "termination_successful": true
}
```

Do not send the raw log unnecessarily if it contains sensitive information.

---

# Phase 10 — Handle Server Unavailability

The client must continue enforcing the forbidden-process policy even if the server is temporarily unreachable.

Correct behavior:

```text
Detect forbidden activity
        ↓
Check process
        ↓
Kill process if necessary
        ↓
Try to alert server
        ↓
Server unavailable?
        ↓
Store alert locally
        ↓
Retry later
```

Do not make process enforcement dependent on successful communication with the server.

The client should eventually synchronize locally stored alerts when the server becomes available.

---

# Phase 11 — Add Forbidden Process Management API

The database already contains the `ForbiddenProcess` table.

Currently:

```text
Database
   ↓
ForbiddenProcess
```

but administrators cannot properly manage it through the application.

Create CRUD API functionality.

Required operations:

```text
GET    /forbidden-processes/
POST   /forbidden-processes/
GET    /forbidden-processes/{id}/
PUT    /forbidden-processes/{id}/
PATCH  /forbidden-processes/{id}/
DELETE /forbidden-processes/{id}/
```

Use the project's existing API conventions.

Do not create a parallel model.

Reuse the existing `ForbiddenProcess` model.

---

# Phase 12 — Forbidden Process API Validation

Validate input before storing it.

At minimum:

* Name/keyword must not be empty.
* Normalize casing where appropriate.
* Prevent accidental duplicates.
* Validate aliases if the model supports them.
* Validate that the value is usable by the client scanner.

Example:

```json
{
    "name": "discord"
}
```

Potential duplicate:

```text
Discord
discord
DISCORD
```

should not create three logically identical rules unless the application explicitly requires case-sensitive rules.

---

# Phase 13 — Authorization

Only authorized users should be able to modify forbidden-process rules.

Separate permissions for:

### Read

Users allowed to view configured forbidden processes.

### Write

Users allowed to:

* Create.
* Update.
* Delete.

Reuse the existing project's role/permission system instead of introducing a new authentication mechanism.

---

# Phase 14 — Frontend Forbidden Process Management

Add an administrative UI for managing forbidden processes.

The page should display:

```text
Forbidden Processes

+-----------------------------------------------+
| Process / Keyword | Status | Actions         |
+-----------------------------------------------+
| Discord           | Active | Edit | Delete    |
| uTorrent          | Active | Edit | Delete    |
| Spotify           | Active | Edit | Delete    |
+-----------------------------------------------+

                [ + Add Forbidden Process ]
```

---

# Phase 15 — Add Forbidden Process

Add a button:

```text
+ Add Forbidden Process
```

Open a form/modal containing the necessary fields.

Example:

```text
Process / Keyword
[ discord              ]

             [Cancel] [Add]
```

After creation:

```text
Frontend
   ↓
POST API
   ↓
Database
   ↓
Success
   ↓
Refresh list
```

---

# Phase 16 — Update Forbidden Process

Allow administrators to modify an existing rule.

Example:

```text
Discord
   ↓
Edit
   ↓
discord.exe
```

The frontend should update the server through:

```text
PATCH /forbidden-processes/{id}/
```

Do not modify local client configuration directly from the frontend.

The server remains the source of truth.

---

# Phase 17 — Delete Forbidden Process

Allow administrators to remove a forbidden process.

Before deletion, display an appropriate confirmation:

```text
Are you sure you want to remove "Discord"
from the forbidden-process list?
```

Then:

```text
DELETE /forbidden-processes/{id}/
```

After successful deletion:

```text
Refresh forbidden-process list
```

Clients should receive the updated configuration according to the existing synchronization mechanism.

---

# Phase 18 — Client Configuration Synchronization

When a client connects to the server:

```text
Client
   ↓
Authentication / Registration
   ↓
Request forbidden-process configuration
   ↓
Server returns current rules
   ↓
Client updates local rules
```

If the server already has a configuration synchronization mechanism, extend it instead of creating another one.

Consider also refreshing the list periodically so newly added forbidden processes do not require a client restart.

For example:

```text
Client
   ↓
Every X minutes
   ↓
Check configuration version
   ↓
Changed?
   ├── No → Continue
   └── Yes → Download new rules
```

---

# Phase 19 — Critical Alert / Repeated Attempts

Integrate the existing repeated-forbidden-process logic if it already exists.

For each forbidden process, track:

```text
Detection count
Termination count
Time window
```

Example:

```text
Discord detected
↓
Discord terminated
↓
Discord starts again
↓
Discord terminated
↓
Discord starts again
↓
Discord terminated
↓
Critical alert
```

Example policy:

```text
5 attempts within 10 minutes
        ↓
CRITICAL ALERT
```

The exact threshold should be configurable rather than hard-coded if the project architecture permits it.

This can indicate:

* repeated user attempts;
* an application automatically restarting;
* a malicious process repeatedly launching the forbidden application.

---

# Phase 20 — Logging and Audit Trail

Every enforcement event should be locally logged.

Example:

```text
2026-08-23 14:10:03
Forbidden activity detected: discord

2026-08-23 14:10:03
Active process found: Discord.exe (PID 4120)

2026-08-23 14:10:04
Process termination successful

2026-08-23 14:10:04
Alert sent to server
```

This will make debugging significantly easier during the internship.

---

# Phase 21 — Testing

## Client Tests

Test:

### Detection

```text
Log contains forbidden keyword
→ detection occurs
```

### No detection

```text
Normal log
→ no alert
→ no process termination
```

### Process running

```text
Forbidden activity
+
Discord.exe running
→ Discord.exe terminated
→ server alert
```

### Process not running

```text
Forbidden activity
+
Discord.exe not running
→ no termination
→ server alert
```

### Case sensitivity

```text
discord
Discord
DISCORD
Discord.exe
```

should behave consistently.

### Repeated launches

```text
Start
→ kill
→ start
→ kill
→ start
→ kill
```

verify critical alert behavior.

### Client protection

Verify that the client agent itself can never be terminated by the forbidden-process mechanism.

---

# Phase 22 — Backend Tests

Test:

```text
GET forbidden processes
POST forbidden process
GET single forbidden process
PATCH forbidden process
DELETE forbidden process
```

Test:

* Unauthorized user.
* Authorized user.
* Duplicate process.
* Invalid process name.
* Missing required fields.
* Non-existent process ID.

---

# Phase 23 — Frontend Tests

Test:

```text
Display forbidden processes
Add process
Edit process
Delete process
Validation errors
API errors
Loading state
Empty state
```

Also verify that the UI refreshes correctly after mutations.

---

# Phase 24 — Integration Test

Run the complete scenario:

```text
Administrator
      |
      | Adds "Discord"
      v
Server Database
      |
      | Client synchronization
      v
Windows Client
      |
      | User opens/searches Discord
      v
Log Entry
      |
      | 10-minute scanner
      v
Forbidden Activity Detected
      |
      v
Process Enumeration
      |
      +---- Discord.exe found
      |
      v
Terminate Discord.exe
      |
      v
Generate Enforcement Event
      |
      v
Send Alert
      |
      v
Server Dashboard
      |
      v
Administrator sees event
```

Then test the case where Discord is no longer running:

```text
Forbidden activity
      ↓
No active Discord process
      ↓
No termination
      ↓
Alert server
```

---

# Final Target Architecture

The completed system should look like:

```text
                    CENTRAL SERVER
                         |
              +----------+----------+
              |                     |
       ForbiddenProcess DB      Alert System
              |                     ^
              |                     |
       Configuration API       Enforcement Events
              |                     |
              +----------+----------+
                         |
                    Client Sync
                         |
                         v
                +------------------+
                | Windows Client   |
                +------------------+
                         |
                +--------+---------+
                |                  |
                v                  v
          Log Scanner       Process Scanner
                |                  |
                |                  |
                +--------+---------+
                         |
                         v
                Forbidden Activity
                         |
                         v
                  Active Process?
                    /        \
                  YES         NO
                   |           |
                   v           v
             Kill Process   Report Only
                   |
                   +-----+
                         |
                         v
                    Alert Server
```

# Implementation Order

Implement in this exact order:

1. **Inspect existing forbidden-process implementation.**
2. **Preserve existing keyword-based log detection.**
3. **Change periodic scanning from 1 hour → 10 minutes.**
4. **Implement duplicate-event protection.**
5. **Implement active-process enumeration.**
6. **Implement safe forbidden-process matching.**
7. **Implement process termination.**
8. **Add enforcement result to server alerts.**
9. **Ensure enforcement works when the server is temporarily unavailable.**
10. **Implement ForbiddenProcess CRUD API.**
11. **Implement API authorization and validation.**
12. **Implement frontend forbidden-process management UI.**
13. **Implement client configuration synchronization for newly added/updated rules.**
14. **Integrate repeated-attempt/critical-alert logic.**
15. **Add client, backend, frontend, and integration tests.**
16. **Run the complete end-to-end test on a controlled test machine.**

## Important Implementation Rule

**Do not rewrite working parts unnecessarily.**

The existing system already has:

* forbidden processes in the database;
* client synchronization;
* startup log scanning;
* hourly scanning;
* server alerts.

Extend those components rather than creating parallel implementations.

The main architectural change is:

```text
Current:

Log detection
      ↓
Alert


New:

Log detection
      ↓
Process verification
      ↓
Process termination (if active)
      ↓
Enforcement result
      ↓
Server alert
```

while simultaneously adding:

```text
Administrator
      ↓
Forbidden Process CRUD API
      ↓
ForbiddenProcess DB
      ↓
Client synchronization
```

The final implementation should remain compatible with the existing client/server communication, authentication, database schema, alert mechanism, and deployment process.

```
```
