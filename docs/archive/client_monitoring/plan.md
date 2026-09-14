# Client Reliability & Monitoring Fix Plan

## Overall order

I recommend this implementation order:

1. **File persistence / Flow Aggregator — Windows Error 5**
2. **Client activity/event logging**
3. **Updater reliability**
4. **Screenshot capture under another Windows user session**
5. **Kismet listener + observation query**
6. **Integration testing and regression pass**

---

## Phase 0 — Establish a debugging baseline

Before modifying anything, add/verify a consistent diagnostic mechanism across the client.

### 0.1 Create a clear client diagnostic structure

Separate logs conceptually into:

```text
client/
├── logs/
│   ├── client.log
│   ├── updater.log
│   ├── persistence.log
│   ├── listeners.log
│   ├── screenshot.log
│   └── kismet.log
```

If the current architecture already has centralized logging, don't create unnecessary files; instead introduce **categories/components**:

```text
[PERSISTENCE]
[UPDATER]
[EVENT_MONITOR]
[SCREENSHOT]
[KISMET]
```

Every important operation should contain:

```text
timestamp
client_id
component
operation
result
error
relevant context
```

### 0.2 Capture environment information

For Windows-specific failures, record:

- Windows version
- agent version
- Python version
- client installation directory
- service/process identity
- current user
- session ID
- whether running as service
- whether running interactively
- storage directory permissions
- updater version

This will make the later debugging considerably easier.

---

## Phase 1 — Fix file persistence / Flow Aggregator

Current symptom:

> `Flow aggregator could not persist finalized flow`
>
> `WinError 5 - Access is denied`
>
> `./client/storage/...`

This should be investigated first because persistence is a foundational client operation.

## 1.1 Determine exactly which operation receives Error 5

Don't assume the problem is simply the directory permissions.

Trace:

```text
Flow captured
      ↓
Flow finalized
      ↓
Serialization
      ↓
Storage path resolution
      ↓
File creation/open
      ↓
Write
      ↓
Rename/replace?
      ↓
Persistence complete
```

Log the exact failing operation.

For example:

```text
PERSISTENCE:
finalizing flow abc123
target = ...
operation = open/write/rename/delete
mode = ...
process = ...
user = ...
error = WinError 5
```

This matters because Windows Error 5 could occur during:

- opening a file
- creating a file
- overwriting an existing file
- renaming a temporary file
- deleting an old file
- changing permissions
- directory creation

---

## 1.2 Inspect the storage directory permissions

Check:

```text
client/
client/storage/
client/storage/<flow files>
```

Determine:

- owner
- ACLs
- inherited permissions
- read/write/modify permissions
- whether the agent's execution account has access

Also verify whether the directory was created by:

- installer
- administrator
- another user
- previous agent version
- updater

A particularly important case is:

> The updater runs elevated and creates/replaces files, while the client runs under a different account.

That can produce exactly the kind of permission inconsistency we're seeing.

---

## 1.3 Check for file locking

Windows can return access-denied behavior when another process holds a file open.

Investigate whether:

- Flow Aggregator has the file open
- another thread is writing it
- the storage service is reading it simultaneously
- antivirus/indexing software is temporarily locking it
- the updater is touching the same directory

If temporary files are used:

```text
flow.tmp
     ↓
flow.json
```

verify that the rename/replace operation is safe.

---

## 1.4 Verify path handling

Make sure all storage paths are generated from a known writable root rather than depending on the current working directory.

For example, avoid relying on:

```text
./client/storage
```

if the process can start from different working directories.

Resolve the actual absolute path and log it.

---

## 1.5 Make persistence failure recoverable

After identifying the root cause, add:

- controlled retry
- temporary-file strategy
- atomic replacement where appropriate
- clear failure logging
- recovery after transient locking

But **do not blindly retry indefinitely**.

Example:

```text
write temporary file
        ↓
flush
        ↓
close
        ↓
replace destination
        ↓
success
```

If persistence fails:

```text
retry → retry → mark persistence failure
```

The flow collector itself should not crash because one flow couldn't be persisted.

---

## 1.6 Test matrix

Test:

| Scenario                  | Expected                       |
| ------------------------- | ------------------------------ |
| Normal client startup     | Persist succeeds               |
| Restart client            | Persist succeeds               |
| Different Windows user    | Persist succeeds if supported  |
| Storage directory exists  | Persist succeeds               |
| Storage directory missing | Directory recreated            |
| Existing flow file        | Correctly overwritten/replaced |
| File temporarily locked   | Retry/recover                  |
| Permission removed        | Clear diagnostic               |
| Updater runs              | Permissions remain correct     |

---

## Phase 2 — Expand client activity/event logging

Currently your client logs don't tell you about things such as:

- application uninstall
- file deletion
- potentially application installation
- file creation/modification

This is more than "add a few log messages."

We should introduce a proper **client event monitoring layer**.

## 2.1 Define the event taxonomy first

Create standardized events:

### Application events

```text
APP_INSTALLED
APP_UNINSTALLED
APP_UPDATED
APP_STARTED
APP_STOPPED
```

### File events

```text
FILE_CREATED
FILE_MODIFIED
FILE_DELETED
FILE_RENAMED
```

### Client events

```text
CLIENT_STARTED
CLIENT_STOPPED
CLIENT_UPDATED
CLIENT_UPDATE_FAILED
CLIENT_CONFIG_CHANGED
```

### Network/passive events

Keep your existing:

```text
MDNS
LLMNR
NBNS
SSDP
DHCP
KISMET
```

---

## 2.2 Application uninstall detection

Don't depend only on process monitoring.

Investigate Windows-native sources such as:

- Windows uninstall registry keys
- Windows event logs
- MSI-related events
- package-management events where applicable

The goal is to distinguish:

```text
Application disappeared
```

from:

```text
Application was explicitly uninstalled
```

This distinction is important.

---

## 2.3 File deletion monitoring

Introduce filesystem event monitoring for the directories you actually care about.

The event pipeline should be:

```text
Windows filesystem event
        ↓
Event normalization
        ↓
Filter
        ↓
Deduplication/debouncing
        ↓
Client event
        ↓
Local log
        ↓
Server
```

Don't monitor the entire disk indiscriminately.

Define monitored paths.

For example:

```text
Important application directories
Client directories
Configured monitored folders
```

---

## 2.4 Avoid event storms

Filesystem watchers can generate huge numbers of events.

You need:

### Filtering

Ignore:

```text
temporary files
cache directories
irrelevant system directories
```

### Deduplication

Multiple OS events can represent one logical operation.

### Rate limiting

Prevent one application from generating thousands of events and overwhelming the server.

---

## 2.5 Standardize event format

For example:

```json
{
  "event_type": "FILE_DELETED",
  "timestamp": "...",
  "client_id": "...",
  "path": "...",
  "user": "...",
  "process": "...",
  "source": "filesystem_monitor"
}
```

For uninstall:

```json
{
  "event_type": "APP_UNINSTALLED",
  "application": "...",
  "version": "...",
  "timestamp": "...",
  "user": "...",
  "source": "windows_event"
}
```

This will also make future AI/anomaly-detection features much easier.

---

## Phase 3 — Completely review the updater

This deserves its own investigation because you currently have **two different updater failures**.

### Failure A

```text
Updater says:
UPDATE FAILED

Reality:
Update succeeded
```

### Failure B

```text
Updater says:
client exited during startup

Reality:
Client remains unusable until manually:
stop agent
→ uninstall agent
→ python ./client.py
→ works
```

These strongly suggest that the updater's **state machine/process lifecycle detection isn't reliable**.

---

## 3.1 Map the entire updater lifecycle

Document the actual current flow:

```text
Server
 ↓
Update requested
 ↓
Package downloaded
 ↓
Package validated
 ↓
Updater launched
 ↓
Client stopped
 ↓
Files replaced
 ↓
Client started
 ↓
Client initializes
 ↓
Health check
 ↓
Update confirmed
```

Then identify what the updater currently considers:

```text
SUCCESS
FAILURE
TIMEOUT
ROLLBACK
```

---

## 3.2 Separate "process exited" from "update failed"

This is extremely important.

Currently you may have something like:

```text
client process exited
        ↓
UPDATE FAILED
```

But that's not necessarily true.

During an update, **the client is expected to exit**.

The updater should understand:

```text
EXPECTED EXIT
```

versus:

```text
UNEXPECTED CRASH
```

For example:

```text
UPDATE_REQUESTED
      ↓
STOPPING_CLIENT
      ↓
CLIENT_EXITED_EXPECTEDLY
      ↓
UPDATING_FILES
      ↓
STARTING_CLIENT
```

The client exiting during this phase is normal.

---

## 3.3 Introduce an explicit update state machine

Something like:

```text
IDLE
 ↓
UPDATE_REQUESTED
 ↓
PACKAGE_DOWNLOADING
 ↓
PACKAGE_VALIDATED
 ↓
CLIENT_STOPPING
 ↓
CLIENT_STOPPED
 ↓
BACKUP_CREATED
 ↓
FILES_REPLACED
 ↓
CLIENT_STARTING
 ↓
CLIENT_HEALTH_CHECK
 ↓
UPDATE_CONFIRMED
```

Failure states:

```text
DOWNLOAD_FAILED
VALIDATION_FAILED
STOP_FAILED
FILE_REPLACEMENT_FAILED
START_FAILED
HEALTH_CHECK_FAILED
ROLLBACK
```

This gives us much more useful diagnostics.

---

## 3.4 Fix the "update succeeded but reported failure" problem

Never use only:

```text
process exited
```

or:

```text
process started
```

as the update result.

Instead verify the new client.

For example:

```text
Updater starts client
        ↓
Client launches
        ↓
Client sends STARTUP_READY
        ↓
Server receives heartbeat
        ↓
Version == expected version
        ↓
Health check passes
        ↓
UPDATE SUCCESS
```

The authoritative signal should be:

> **The new version successfully initialized and became healthy.**

---

## 3.5 Investigate the startup failure

The situation where you had to:

```text
stop agent
uninstall agent
python ./client.py
```

is particularly important.

Investigate:

### Process duplication

Could the updater leave:

```text
old client.exe
old client.py
service
```

running?

### File locks

Could an old process still hold:

```text
DLL
Python module
database
log
configuration
```

open?

### Working directory

Could the updater launch the client from the wrong directory?

### Environment

Does:

```text
python ./client.py
```

have a different environment than the installed agent?

### Permissions

Does the updater launch the new client under a different identity?

### Configuration

Could the update overwrite or corrupt configuration?

### Startup dependency

Could the client start before:

- storage
- network
- required services
- configuration
- database
- listeners

are ready?

---

## 3.6 Add startup diagnostics

At startup, log:

```text
CLIENT_STARTING
version
PID
parent PID
working directory
executable path
Python path
user
session
configuration path
storage path
```

Then:

```text
INITIALIZING_STORAGE
INITIALIZING_NETWORK
INITIALIZING_LISTENERS
INITIALIZING_PASSIVE_MONITORS
INITIALIZING_API
STARTUP_READY
```

If startup fails, we'll immediately know **which subsystem failed**.

---

## 3.7 Add rollback

The updater should preserve the previous version:

```text
current/
backup/
new/
```

Conceptually:

```text
Current version
      ↓
Backup
      ↓
Install new version
      ↓
Start
      ↓
Health check
      ↓
SUCCESS → delete backup
```

If startup fails:

```text
new version
    ↓
rollback
    ↓
restore previous version
    ↓
start old version
```

This is much safer than leaving the client broken.

---

## Phase 4 — Screenshot failure with another logged-in Windows user

This sounds like a **Windows session / desktop isolation problem**, especially if the agent is running as a service or under one account while another user owns the interactive desktop.

The important distinction is:

```text
Agent process
      ≠
Interactive user's desktop session
```

Other functionality can continue working because networking, process enumeration, system information, etc. don't require access to the interactive desktop.

Screenshot capture does.

---

## 4.1 Diagnose the session topology

When screenshot fails, record:

```text
agent user
agent session ID
interactive user
interactive session ID
desktop name
window station
```

Compare:

### Case A

```text
Agent
  ↓
same user
  ↓
same session
  ↓
screenshot works
```

versus:

### Case B

```text
Agent/service
  ↓
Session 0
       │
       └── User
           Session 1
           ↓
           screenshot fails
```

If that's what we're seeing, the cause becomes much clearer.

---

## 4.2 Determine the intended behavior

We need to decide whether screenshots should capture:

1. the **currently active user's desktop**, or
2. a specific user session, or
3. whichever session is active on the machine.

For your management platform, I'd recommend:

> Capture the desktop of the currently active interactive Windows session.

---

## 4.3 Design the screenshot subsystem around sessions

Conceptually:

```text
Screenshot request
       ↓
Identify active session
       ↓
Identify interactive user
       ↓
Capture that session's desktop
       ↓
Return screenshot
```

Rather than simply:

```text
capture_screen()
```

from the agent's own process context.

---

## 4.4 Test scenarios

We should explicitly test:

| Scenario                 | Expected                       |
| ------------------------ | ------------------------------ |
| Same user logged in      | Works                          |
| Different user logged in | Works                          |
| Lock screen              | Defined behavior               |
| RDP session              | Defined behavior               |
| Multiple sessions        | Capture active session         |
| No interactive user      | Clear failure                  |
| Agent running as service | Works                          |
| User logs out/in         | Works without restarting agent |

This should be solved before calling screenshot support complete.

---

## Phase 5 — Kismet observation problem

Your symptom is very useful:

> Filter = 15 minutes, but observations from yesterday appear.

Combined with:

> Most observations are broadcast packets.

We should **not immediately assume the Kismet listener is broken**.

There are two separate components to investigate:

```text
Kismet
   ↓
Listener
   ↓
Storage
   ↓
Observation query
   ↓
15-minute filter
   ↓
UI
```

The failure could be anywhere along that pipeline.

---

## 5.1 Add Kismet listener lifecycle logging

Yes — I agree with your idea.

Make Kismet behave like the other passive listeners.

Log:

```text
KISMET_LISTENER_STARTING
KISMET_CONNECTED
KISMET_LISTENING
KISMET_EVENT_RECEIVED
KISMET_EVENT_PARSED
KISMET_OBSERVATION_STORED
KISMET_DISCONNECTED
KISMET_RECONNECTING
KISMET_ERROR
KISMET_STOPPED
```

For example:

```text
09:32:01 KISMET_LISTENER_STARTING
09:32:02 KISMET_CONNECTED
09:32:02 KISMET_LISTENING
09:32:15 KISMET_EVENT_RECEIVED type=...
09:32:15 KISMET_OBSERVATION_STORED id=...
```

---

## 5.2 Add listener health information

The client should be able to report:

```json
{
  "listener": "kismet",
  "status": "active",
  "connected": true,
  "last_event": "...",
  "events_received": 152,
  "observations_stored": 91,
  "last_error": null
}
```

This immediately answers:

> Is Kismet actually listening?

without guessing from the UI.

---

## 5.3 Investigate the 15-minute filter independently

This is critical.

Test the query directly against storage.

For example:

```text
NOW = 2026-09-06 09:30

requested:
last 15 minutes

expected:
09:15 → 09:30
```

Verify:

- timestamp column
- timezone
- UTC vs local time
- timestamp serialization
- database comparison
- API filtering
- frontend filtering

A very common bug is:

```text
DB stores UTC
UI assumes local time
```

or the reverse.

---

## 5.4 Verify that old records aren't being returned

Run controlled queries:

```text
last 15 minutes
last 1 hour
last 24 hours
```

Compare the results.

If:

```text
15 min → yesterday's records
1 hour → yesterday's records
24 hour → yesterday's records
```

then the filter/query layer is probably broken.

If:

```text
database contains only yesterday's records
```

then the listener/storage layer is likely the problem.

---

## 5.5 Investigate broadcast-heavy observations

Don't automatically consider broadcast traffic invalid.

Kismet will naturally observe a lot of:

- beacon frames
- broadcast/multicast traffic
- probe-related traffic
- management frames

But we need to determine whether we're actually receiving **useful observation/device information**.

Separate:

```text
raw packets
```

from:

```text
device observations
```

and make sure your storage model represents that distinction.

---

## 5.6 Add an end-to-end Kismet test

Create a controlled test:

```text
Kismet running
       ↓
Listener connected
       ↓
Generate/observe traffic
       ↓
Listener receives event
       ↓
Event parsed
       ↓
Observation stored
       ↓
Query last 15 minutes
       ↓
Observation appears
       ↓
UI displays it
```

If it fails, the logs tell us exactly where.

---

## Phase 6 — Cross-feature integration

Once the individual problems are fixed, test them together because they interact.

Particularly:

### Updater + persistence

```text
Update client
 ↓
restart
 ↓
Flow Aggregator starts
 ↓
flows persist
```

### Updater + listeners

```text
Update
 ↓
restart
 ↓
mDNS listener active
 ↓
Kismet listener active
 ↓
events received
```

### Updater + screenshot

```text
Update
 ↓
client restarts
 ↓
different Windows user logged in
 ↓
screenshot works
```

### Different Windows user + persistence

```text
User A installs/runs agent
 ↓
User B logs in
 ↓
flow persistence still works
```

---

## Phase 7 — Add automated regression tests

The final result should not depend entirely on manually testing 25 machines.

Create tests around the critical logic.

### Persistence

```text
test_storage_directory_creation
test_flow_persistence
test_locked_file_retry
test_permission_failure
test_atomic_write
```

### Events

```text
test_file_created_event
test_file_deleted_event
test_file_modified_event
test_app_uninstall_event
test_event_deduplication
```

### Updater

```text
test_expected_client_exit
test_update_success
test_startup_timeout
test_version_verification
test_rollback
test_update_failure_reporting
```

### Kismet

```text
test_listener_start
test_listener_reconnect
test_event_parsing
test_observation_storage
test_time_filter
```

---

## Recommended architecture after the fixes

I'd aim for this overall client structure:

```text
                         CLIENT AGENT
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   Core Runtime          Event Monitoring       Update System
        │                     │                     │
        │              ┌──────┼──────┐              │
        │              │      │      │              │
        │            Files    Apps  System          │
        │                                             │
        ├──────────── Passive Monitoring ────────────┤
        │              │      │      │                │
        │             mDNS   SSDP   Kismet            │
        │                                             │
        ├────────────── Persistence ──────────────────┤
        │              │                              │
        │         Flow Storage                  Event Storage
        │                                             │
        ├─────────────── Diagnostics ─────────────────┤
        │              │                              │
        │          Component Logs               Health State
        │                                             │
        └────────────── Screenshot ──────────────────┘
                              │
                              ▼
                         Server/API
```

The important architectural improvement is that **each subsystem exposes its own health state**.

For example:

```text
Client Health
├── Core             OK
├── Persistence      OK
├── Event Monitor    OK
├── mDNS             OK
├── Kismet           ACTIVE
├── Screenshot       READY
└── Updater          READY
```

That would make future debugging dramatically easier.

---

## Implementation milestones

I'd break the actual work into these milestones:

### Milestone 1 — Diagnostics

- Standardize component logging
- Add startup diagnostics
- Add client environment/session information
- Add Kismet lifecycle logging

### Milestone 2 — Persistence

- Trace exact Error 5 operation
- Fix ACL/path/locking issue
- Implement safe persistence
- Add retry/recovery
- Test under different execution contexts

### Milestone 3 — Event monitoring

- Define event schema
- Add file deletion monitoring
- Add application uninstall detection
- Add filtering/deduplication
- Send events to server

### Milestone 4 — Updater

- Map current updater behavior
- Implement explicit state machine
- Separate expected exit from failure
- Add startup handshake
- Add version verification
- Add timeout handling
- Implement rollback
- Test repeated updates

### Milestone 5 — Screenshot

- Diagnose Windows session isolation
- Detect active interactive session
- Capture correct user's desktop
- Handle multiple/no sessions
- Test service + different-user scenarios

### Milestone 6 — Kismet

- Instrument listener lifecycle
- Verify connection/event reception
- Verify storage
- Test timestamp handling
- Fix 15-minute query
- Investigate broadcast-only observations
- Validate UI results against raw database/API results

### Milestone 7 — Regression

Run the complete client test matrix:

```text
Fresh installation
      ↓
Normal operation
      ↓
Passive monitoring
      ↓
Flow persistence
      ↓
File/app events
      ↓
Screenshot
      ↓
Kismet
      ↓
Update
      ↓
Restart
      ↓
Verify everything again
```

## One important recommendation

**Do not start by modifying all five features at once.** The updater especially should come after we have good diagnostics. Otherwise, if an update fails, we'll still be guessing whether the problem is the updater, permissions, startup, listeners, or storage.

The first concrete task I'd tackle is therefore:

> **Instrument the client → reproduce the Flow Aggregator Error 5 → identify the exact filesystem operation and execution identity causing it → fix persistence → then use the improved diagnostics as the foundation for the updater and Kismet investigations.**

That gives us a much cleaner debugging path instead of chasing five symptoms independently.
