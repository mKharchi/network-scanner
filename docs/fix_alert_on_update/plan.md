# File Activity Logging — Correction & Verification Plan

## 1. Objective

The current implementation detects file modifications and deletions, but it does not behave according to the intended design.

### Current behavior

When a monitored file is modified or removed:

```text
File change
    ↓
File monitor
    ↓
Alert generated
    ↓
Server receives alert
```

This is not the desired behavior.

### Required behavior

File activity should be collected as part of the client's normal log/report:

```text
File change
    ↓
File monitor
    ↓
Filter
    ↓
Store file activity event
    ↓
Client "Get Log" request
    ↓
Log/report contains relevant file changes
```

There must be **no real-time alert generated for ordinary file modifications/deletions**.

Additionally, frequently changing passive-monitoring/packet files must be excluded because they create excessive noise.

---

# 2. First: Inspect the Existing Implementation

Before changing code, scan the project and identify the current file-monitoring implementation.

Search for:

```text
FILE_CREATED
FILE_MODIFIED
FILE_DELETED
FILE_RENAMED
file monitor
filesystem
watcher
alert
notification
event
```

Determine:

- Which component detects file changes.
- Where file events are created.
- Where they are currently converted into alerts.
- Where alerts are sent to the server.
- How the existing client log is generated.
- Where the "Get Log" operation retrieves information.
- Whether file events are already stored locally or only sent immediately.

Do not create a second file-monitoring system if the existing implementation can be reused.

---

# 3. Separate File Events From Alerts

The key architectural change is:

> **A file event is not automatically an alert.**

Currently the implementation appears to be treating:

```text
FILE_MODIFIED
FILE_DELETED
```

as:

```text
ALERT
```

Change the architecture so that file activity is represented as a normal client event/log entry.

Conceptually:

```text
                 FILE EVENT
                     │
              ┌──────┴──────┐
              │             │
          Relevant       Excluded
              │             │
              ▼             ▼
        Log storage       Ignore
              │
              ▼
         Get Log
```

There should be no path such as:

```text
FILE_MODIFIED → CREATE_ALERT
```

for ordinary file activity.

---

# 4. Define the File Activity Log Events

Use standardized event types.

For example:

```text
FILE_CREATED
FILE_MODIFIED
FILE_DELETED
FILE_RENAMED
```

Only implement the event types that the existing monitor actually supports and that are required by the original design.

Each event should contain enough information to understand what happened.

For example:

```json
{
  "event_type": "FILE_DELETED",
  "timestamp": "...",
  "path": "...",
  "filename": "...",
  "user": "...",
  "source": "filesystem_monitor"
}
```

For a modification:

```json
{
  "event_type": "FILE_MODIFIED",
  "timestamp": "...",
  "path": "...",
  "filename": "...",
  "user": "...",
  "source": "filesystem_monitor"
}
```

Do not include unnecessary sensitive information.

---

# 5. Integrate File Activity Into the Existing Client Log

Find the existing implementation behind:

```text
Get Log
```

and determine how the client currently builds its log.

The desired behavior is:

```text
Client activity
├── startup/shutdown
├── errors
├── configuration events
├── application events
├── file activity
├── passive listener activity
└── other existing events
```

File events should become another category in that existing log.

For example:

```text
CLIENT LOG

[10:32:12] CLIENT_STARTED
[10:35:41] APP_UNINSTALLED: ...
[10:42:13] FILE_DELETED: C:\...
[10:43:01] FILE_MODIFIED: C:\...
[10:45:20] KISMET_CONNECTED
```

The exact format should follow the existing project's log format rather than introducing an unrelated format.

---

# 6. Decide Where File Events Are Stored

Inspect the current architecture before deciding.

If the client already maintains an event/log store, reuse it.

The preferred flow is:

```text
Filesystem watcher
        ↓
Normalized event
        ↓
Filtering
        ↓
Local event/log storage
        ↓
Get Log
        ↓
Server
```

If the existing client log is generated dynamically, integrate the events into that mechanism instead.

Do not create a completely separate database/table/file unless the existing architecture requires it.

---

# 7. Remove the Real-Time Alert Behavior

Find exactly where file events become alerts.

Remove that connection.

The final behavior should be:

```text
FILE_DELETED
      ↓
log event
      ↓
available through Get Log
```

NOT:

```text
FILE_DELETED
      ↓
alert
      ↓
notification
```

Likewise:

```text
FILE_MODIFIED
      ↓
log event
```

not:

```text
FILE_MODIFIED
      ↓
alert
```

---

# 8. Important: Do Not Remove File Monitoring

The goal is **not** to disable the file watcher.

The watcher should continue detecting relevant events.

We are changing what happens **after detection**.

Correct:

```text
Detect → Filter → Log
```

Incorrect:

```text
Disable watcher
```

The ability to determine whether a file was deleted must remain available through the client log.

---

# 9. Exclude High-Frequency Passive Packet Files

The current implementation generates excessive events because some files are continuously modified by passive network monitoring.

The known example is:

```text
DHCP observation files
```

These should not appear in the file activity log.

The same principle should apply to other files that are expected to change continuously as part of passive packet/observation collection.

First scan the project to identify all such files.

Search for:

```text
DHCP
mDNS
LLMNR
NBNS
SSDP
Kismet
packet
observation
capture
flow
telemetry
```

Identify the actual storage paths used by these components.

Do **not** guess filenames.

---

# 10. Create an Explicit Exclusion Policy

Create one centralized filtering mechanism.

Conceptually:

```text
FILE EVENT
    ↓
is_excluded_path?
    ├── YES → ignore
    └── NO  → log
```

Avoid scattering exclusions throughout the watcher:

```python
if file != x:
...
if file != y:
...
```

Instead maintain a centralized policy.

For example:

```text
Excluded categories:

Passive packet/observation storage
Temporary files
Cache files
Other explicitly approved high-frequency files
```

The exact implementation should follow the project's existing configuration architecture.

---

# 11. Prefer Path-Based Exclusion Over Fragile Filename Matching

If the passive files are stored under known directories, prefer excluding their directories rather than relying only on filenames.

For example conceptually:

```text
client/storage/passive/
```

could be excluded as a monitored source.

This is safer than:

```text
if filename contains "dhcp":
```

because filenames can change.

However, inspect the actual project structure first.

---

# 12. Avoid Over-Excluding

Do not exclude the entire:

```text
client/storage/
```

unless the implementation plan explicitly says that all storage files should be ignored.

The objective is:

```text
Normal/relevant files → logged
Passive packet files → ignored
```

not:

```text
Everything in storage → ignored
```

This distinction is important because you still want the client to report meaningful file deletions.

---

# 13. Handle Temporary and Internal Files

Inspect whether the watcher currently reports files such as:

```text
.tmp
.temp
.lock
.cache
.partial
```

or files created temporarily during persistence.

If these are internal implementation artifacts, determine whether they should be excluded.

Do not blindly exclude every temporary extension; verify their role in the project.

---

# 14. Prevent Event Flooding

Even after excluding passive packet files, the watcher should have basic protection against event storms.

For example, if an application modifies a file 100 times in a few seconds, the log should not necessarily become:

```text
FILE_MODIFIED
FILE_MODIFIED
FILE_MODIFIED
...
```

Check the implementation plan for the expected behavior.

If deduplication/debouncing was planned, verify it.

If it wasn't planned, don't silently redesign the feature; report the potential issue separately.

---

# 15. Verify "Get Log" Behavior

This is the most important functional test.

Create a controlled test file:

```text
test_file.txt
```

Perform:

```text
1. Create file
2. Modify file
3. Delete file
```

Then:

```text
Client → Get Log
```

Expected:

```text
FILE_CREATED
FILE_MODIFIED
FILE_DELETED
```

according to the event types supported by the implementation.

There should be:

```text
0 file alerts
```

---

# 16. Verify Deletion Specifically

Because the original problem was:

> Not being able to know whether a client removed a file.

Perform:

```text
Create test file
↓
Verify it exists
↓
Delete it
↓
Request client log
```

The returned log must clearly indicate:

```text
FILE_DELETED
path = <expected path>
timestamp = <expected time>
```

This is the primary acceptance test.

---

# 17. Verify Modification

Perform:

```text
Create test file
↓
Modify it
↓
Get Log
```

Expected:

```text
FILE_MODIFIED
```

Again:

```text
No alert
```

---

# 18. Verify Passive Files Are Ignored

Identify an actual DHCP/passive observation file from the project.

Cause it to change repeatedly.

For example:

```text
Passive listener running
        ↓
Observation received
        ↓
File changes
        ↓
File changes
        ↓
File changes
```

Then request the client log.

Expected:

```text
No FILE_MODIFIED events for the passive packet file.
```

Also verify:

```text
No alerts
```

---

# 19. Verify Kismet/Passive Storage Specifically

Because Kismet is now part of the client, check whether its:

- observation files
- packet files
- flow files
- temporary capture files
- database/storage files

are being monitored by the filesystem watcher.

The Kismet integration must not accidentally create a new source of log noise.

If Kismet data is intentionally supposed to be logged separately, follow the Kismet implementation plan rather than treating those files as ordinary user-file activity.

---

# 20. Verify Real User/Application Files Still Work

Do not only test exclusions.

Test a normal application/user file:

```text
C:\...\test.txt
```

and verify:

```text
Create → logged
Modify → logged
Delete → logged
```

This confirms that the filtering mechanism didn't become too aggressive.

---

# 21. Verify Restart Persistence

Perform:

```text
Client running
↓
file modified
↓
client restart
↓
Get Log
```

Determine whether the existing architecture expects the event to survive restart.

If persistent logs were part of the original design, verify that the event remains available.

---

# 22. Verify Multiple Clients

Test at least:

```text
Client A
Client B
```

Perform a file deletion on A.

Then retrieve logs for both.

Expected:

```text
Client A → FILE_DELETED
Client B → no corresponding event
```

This verifies that events aren't incorrectly associated with the wrong client.

---

# 23. Review the Server Side

Inspect the server/API implementation.

Verify that file activity:

```text
Client
 ↓
event/log payload
 ↓
API
 ↓
server storage
 ↓
Get Log response
```

is correctly handled.

Make sure the server does not automatically convert:

```text
FILE_DELETED
```

into an alert.

The change needs to be correct on both client and server sides.

---

# 24. Final Architecture

The desired final flow is:

```text
                     FILESYSTEM
                         │
                         ▼
                  File Watcher
                         │
                         ▼
                 Event Normalizer
                         │
                         ▼
                    Filter
                    /     \
                   /       \
             Excluded     Relevant
                │             │
                ▼             ▼
             IGNORE       Log/Event Store
                              │
                              ▼
                         Get Log
                              │
                              ▼
                           Server
                              │
                              ▼
                             UI
```

And explicitly:

```text
                         File Event
                              │
                              X
                         No Alert
```

---

# 25. Acceptance Criteria

The feature is considered correctly implemented only when all of these are true:

### File deletion

- [ ] File deletion is detected.
- [ ] Deletion is recorded as a client log event.
- [ ] The event appears through "Get Log".
- [ ] Path is available.
- [ ] Timestamp is available.
- [ ] No alert is generated.

### File modification

- [ ] Modification is detected.
- [ ] Modification is recorded in the log.
- [ ] No alert is generated.
- [ ] High-frequency irrelevant modifications are filtered.

### Passive files

- [ ] DHCP observation files are excluded.
- [ ] Other passive packet/observation files are identified.
- [ ] Those files do not flood the client log.
- [ ] Those files do not generate alerts.

### Normal files

- [ ] Normal user/application files continue to be monitored.
- [ ] Creation/modification/deletion work.
- [ ] Filtering does not suppress legitimate events.

### Architecture

- [ ] File events are separate from alerts.
- [ ] Filtering is centralized.
- [ ] Client and server agree on the event format.
- [ ] Get Log retrieves file activity correctly.
- [ ] No duplicate file-monitoring mechanism was introduced.

---

# 26. Final Verification Report

After implementing the correction, produce a short report containing:

```text
FILE ACTIVITY VERIFICATION
==========================

Current implementation:
...

Changed behavior:
...

Alert behavior:
Before → file changes generated alerts
After  → file changes are log events only

Excluded paths/files:
1. ...
2. ...
3. ...

Tests:
[PASS] File creation
[PASS] File modification
[PASS] File deletion
[PASS] Passive DHCP file ignored
[PASS] Other passive files ignored
[PASS] No file alerts
[PASS] Get Log contains relevant file events
[PASS] Normal files remain monitored

Remaining issues:
...
```

## Final rule

**Do not solve the notification problem by simply disabling the existing alerts globally.**

Only file-activity alerts should disappear.

Other legitimate alerts in the client must continue to function normally.

The intended final behavior is:

> **Relevant file changes → recorded in the client's log → visible when "Get Log" is requested.**

> **Frequent passive packet/observation files → ignored.**

> **Ordinary file changes → no real-time alert.**
