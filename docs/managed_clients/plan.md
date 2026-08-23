# Remote Client Screenshot Feature — Detailed Implementation Plan

## Objective

Implement a secure remote screenshot feature for the Windows client agent.

The desired workflow is:

```text
Administrator / Server
        |
        | REQUEST_SCREENSHOT
        v
Windows Client Agent
        |
        | Capture current screen
        v
Screenshot PNG/JPEG
        |
        | Upload
        v
Central Server
        |
        v
Server storage
        |
        v
Stored screenshot + metadata
````

The screenshot must be captured **only when explicitly requested by the server**.

The final implementation must:

* allow the server to request a screenshot from a specific client;
* authenticate/authorize the request;
* capture the client's current screen;
* generate a meaningful filename;
* upload the image to the server;
* store it under the existing `storage` directory;
* maintain metadata linking the screenshot to the client/device;
* provide a clear success/failure result;
* handle offline clients and upload failures safely;
* avoid blocking the client agent;
* avoid uncontrolled screenshot generation or storage growth;
* create a complete audit trail.

---

# Phase 1 — Inspect Existing Architecture

Before changing anything, inspect the current project.

Identify:

## Client

* Client entry point.
* Windows service / background process.
* Server communication mechanism.
* Existing command polling mechanism.
* Existing command execution system.
* Client authentication.
* Client ID / device ID.
* Existing logging.
* Existing configuration system.
* Existing local file/storage handling.
* Existing HTTP upload utilities.

## Server

* API framework.
* Authentication/authorization.
* Client management endpoints.
* Existing command endpoint.
* Existing upload/file endpoints.
* Existing `storage` directory configuration.
* Existing database models.
* Existing API response conventions.
* Existing frontend/admin dashboard.

Do not create a second command channel if an existing one already exists.

Reuse the existing server-to-client command mechanism.

---

# Phase 2 — Define the Feature Flow

The primary workflow should be:

```text
1. Administrator selects client
2. Administrator clicks "Take Screenshot"
3. Server validates authorization
4. Server generates screenshot request
5. Client receives request
6. Client validates request
7. Client captures screenshot
8. Client creates screenshot file
9. Client uploads file to server
10. Server validates upload
11. Server stores file
12. Server creates screenshot metadata
13. Server returns/records success
14. UI displays screenshot information
```

The client should not take periodic screenshots automatically.

The feature is explicitly request-driven.

---

# Phase 3 — Define the Command

Add a server command such as:

```json
{
  "command": "REQUEST_SCREENSHOT",
  "command_id": "uuid",
  "client_id": "client-123",
  "issued_at": "2026-08-23T15:00:00Z",
  "expires_at": "2026-08-23T15:01:00Z"
}
```

The command should contain:

* unique command ID;
* target client ID;
* creation timestamp;
* expiration timestamp;
* command type;
* requesting administrator/user ID if the existing architecture supports it.

The command must be authenticated.

The client must not execute arbitrary unauthenticated screenshot requests.

---

# Phase 4 — Command Validation on Client

When the client receives a screenshot request:

1. Verify that the command is authentic.
2. Verify that it targets the current client.
3. Verify that the command has not expired.
4. Verify that the command ID has not already been processed.
5. Verify that the screenshot operation is currently permitted.
6. Create a local task for screenshot capture.

If validation fails:

```text
REQUEST_REJECTED
```

and record the reason in the client logs.

---

# Phase 5 — Screenshot Capture Module

Create a dedicated module.

Suggested conceptual interface:

```python
class ScreenshotManager:
    def capture(self) -> ScreenshotResult:
        ...
```

Do not put screenshot logic directly into:

* the client main loop;
* server communication code;
* process monitoring;
* passive network discovery.

Keep it isolated.

The module should support:

* full-screen capture;
* multiple-monitor environments if relevant;
* image format selection;
* temporary local file generation;
* resource cleanup.

Use an established Windows-compatible screenshot library/API already compatible with the project's Python/runtime environment.

Before choosing a dependency:

1. inspect existing dependencies;
2. prefer a maintained and deployment-friendly option;
3. consider PyInstaller compatibility;
4. avoid adding a very large dependency unnecessarily.

---

# Phase 6 — Multiple-Monitor Handling

Determine whether the deployment can contain multiple monitors.

Support one of the following clearly defined behaviors:

### Option A — Primary monitor only

Simplest implementation.

### Option B — Entire virtual desktop

Capture all connected monitors as a single image.

### Option C — One screenshot per monitor

For example:

```text
DESKTOP-ABC-20260823-150012-monitor-1.png
DESKTOP-ABC-20260823-150012-monitor-2.png
```

Choose the behavior that best fits the current project requirements.

Document it.

Do not silently capture only one monitor if the target environment commonly uses multiple displays.

---

# Phase 7 — Screenshot Image Format

Prefer PNG by default unless storage size becomes a concern.

Example:

```text
PNG
Advantages:
- lossless
- predictable rendering
- good for UI screenshots
- no quality degradation
```

JPEG can be supported as an optional configuration if needed.

If JPEG is used:

* choose a configurable quality value;
* avoid excessive compression;
* make the format explicit in the response.

Default recommendation:

```text
format = PNG
```

---

# Phase 8 — Temporary Client-Side File

After capture, save to a temporary working directory.

Example:

```text
temp/
  screenshot/
      client-123-20260823-150012.png
```

Do not immediately store screenshots permanently on the client.

The client should:

1. Capture.
2. Save temporarily.
3. Upload.
4. Verify upload success.
5. Delete the temporary file.

If upload fails:

* retain the file temporarily according to a bounded retry policy;
* do not keep unlimited screenshots;
* clean up stale temporary files.

---

# Phase 9 — Filename Design

The screenshot filename must be meaningful.

Recommended format:

```text
<device-name>-<timestamp>.<extension>
```

Example:

```text
DESKTOP-ABC123-20260823-150012.png
```

If device names can contain invalid filesystem characters, sanitize them.

Example:

```text
DESKTOP/ABC
```

must become something like:

```text
DESKTOP_ABC
```

Allowed filename characters should be handled safely.

The timestamp should preferably be UTC.

Recommended timestamp format:

```text
YYYYMMDD-HHMMSS
```

Example:

```text
DESKTOP-ABC123-20260823-150012.png
```

---

# Phase 10 — Avoid Filename Collisions

Two screenshots could theoretically be generated in the same second.

Use the command ID or millisecond component when necessary.

Example:

```text
DESKTOP-ABC123-20260823-150012-7f3a2c.png
```

or:

```text
DESKTOP-ABC123-20260823-150012-245.png
```

The final naming strategy must guarantee uniqueness.

---

# Phase 11 — Server Upload API

Create a dedicated endpoint.

For example:

```text
POST /api/screenshots/
```

or adapt to the existing API convention.

The upload should contain:

### Multipart file

```text
screenshot=<binary image>
```

### Metadata

```text
client_id
command_id
device_name
captured_at
format
```

The exact field names should match the project's existing API style.

---

# Phase 12 — Upload Validation

The server must not blindly accept arbitrary files.

Validate:

* authenticated client;
* authorized operation;
* command ID;
* target client;
* image MIME type;
* file extension;
* file size;
* image format;
* filename safety.

Accept only configured formats:

```text
image/png
image/jpeg
```

Reject:

```text
.exe
.py
.zip
.html
unknown binary
```

Do not trust the file extension alone.

Validate the actual image content using the image-processing library available in the backend.

---

# Phase 13 — File Size Limits

Introduce a maximum screenshot size.

Example configuration:

```yaml
screenshots:
  max_file_size_mb: 10
```

The exact value should be configurable.

Reject uploads above the limit.

This protects the server against accidental or malicious storage exhaustion.

---

# Phase 14 — Server Storage Structure

The screenshot must be stored inside the existing storage folder.

Example:

```text
storage/
├── screenshots/
│   ├── DESKTOP-ABC123-20260823-150012.png
│   ├── DESKTOP-XYZ456-20260823-150530.png
│   └── LAPTOP-HOME-20260823-151200.png
```

If the application is multi-tenant, prefer a structure that prevents collisions and makes management easier:

```text
storage/
└── screenshots/
    └── <client-id>/
        ├── DESKTOP-ABC123-20260823-150012.png
        └── DESKTOP-ABC123-20260823-151400.png
```

If organizations/tenants already exist, consider:

```text
storage/
└── screenshots/
    └── <organization-id>/
        └── <client-id>/
            └── screenshot.png
```

Use whichever structure matches the existing project architecture.

---

# Phase 15 — Prevent Path Traversal

Never directly concatenate the client-supplied filename into the storage path.

For example, reject values containing:

```text
../
..\ 
/
\
```

and other unsafe path constructs.

The server should generate the actual storage path.

The client-provided device name should be sanitized and treated only as part of the filename.

---

# Phase 16 — Screenshot Metadata Model

Create a database model if the project needs persistent screenshot history.

Suggested fields:

```text
Screenshot
---------
id
client_id
command_id
filename
storage_path
mime_type
file_size
device_name
captured_at
uploaded_at
status
requested_by
```

Possible status values:

```text
REQUESTED
CAPTURED
UPLOADED
FAILED
```

If the existing architecture already has an event/audit model, integrate the screenshot request into it.

---

# Phase 17 — Link Screenshot to Client

Every screenshot must be associated with the originating client.

Example:

```json
{
  "id": 42,
  "client_id": "client-123",
  "device_name": "DESKTOP-ABC123",
  "filename": "DESKTOP-ABC123-20260823-150012.png",
  "captured_at": "2026-08-23T15:00:12Z"
}
```

This allows the server UI to show screenshots by device.

---

# Phase 18 — Audit Information

Record who requested the screenshot.

If the existing authentication system supports administrator identities, store:

```text
requested_by
```

Example:

```text
requested_by = admin-42
```

This is important for accountability because screenshots may contain sensitive information.

Also record:

```text
requested_at
captured_at
uploaded_at
```

so the complete lifecycle is auditable.

---

# Phase 19 — Client Response Flow

The client should report status where possible.

Example:

```text
REQUEST_SCREENSHOT
        |
        v
CAPTURE_STARTED
        |
        v
CAPTURE_SUCCESS
        |
        v
UPLOAD_STARTED
        |
        v
UPLOAD_SUCCESS
```

Possible failure:

```text
CAPTURE_FAILED
UPLOAD_FAILED
REQUEST_EXPIRED
REQUEST_REJECTED
```

If the client disappears after the request, the server should eventually mark the request as:

```text
TIMEOUT
```

rather than waiting forever.

---

# Phase 20 — Important Network Failure Scenario

Handle:

```text
Server requests screenshot
        |
        v
Client captures screenshot
        |
        v
Network disappears
        |
        v
Upload fails
```

The client should:

1. Keep the temporary screenshot.
2. Retry according to a bounded retry policy.
3. Avoid infinite retries.
4. Delete the temporary file after the retry policy expires.
5. Log the failure.

Example:

```yaml
screenshot:
  upload:
    max_retries: 3
    retry_delay_seconds: 10
```

---

# Phase 21 — Avoid Duplicate Screenshot Requests

The command ID should be the unique request identifier.

If the same command is delivered twice:

```text
command_id = ABC123
```

the client must not capture two screenshots.

Instead:

```text
already_processed(command_id)
    ↓
return existing result
```

This makes the feature idempotent.

---

# Phase 22 — Screenshot Capture Concurrency

A screenshot operation should not block:

* passive network discovery;
* DHCP scanner;
* forbidden process monitor;
* client heartbeat;
* command processing.

Use the project's existing background-task/thread/async architecture.

Conceptually:

```text
Windows Agent
├── Network Discovery
├── DHCP
├── Forbidden Process Monitor
├── Heartbeat
├── Command Listener
└── Screenshot Worker
```

The screenshot worker performs capture/upload independently.

---

# Phase 23 — Prevent Concurrent Screenshot Flooding

The server should avoid sending unlimited screenshot requests to the same client.

Implement a simple concurrency/rate policy.

Example:

```yaml
screenshots:
  max_concurrent_requests_per_client: 1
  minimum_interval_seconds: 30
```

The client should also reject/queue duplicate concurrent requests.

Recommended behavior:

```text
Screenshot already running
       ↓
New screenshot request
       ↓
REJECT / QUEUE
```

Choose one behavior and document it.

---

# Phase 24 — Server-Side Authorization

Only authorized administrators/operators should be able to request screenshots.

Reuse the existing authorization system.

Before executing:

```text
REQUEST_SCREENSHOT
```

verify:

```text
User authenticated?
User authorized?
Target client exists?
Target client belongs to an accessible organization/tenant?
```

Do not expose a public screenshot endpoint.

---

# Phase 25 — API Design

Possible server endpoints:

```text
POST   /api/clients/{client_id}/screenshots/request/
POST   /api/screenshots/upload/
GET    /api/clients/{client_id}/screenshots/
GET    /api/screenshots/{id}/
DELETE /api/screenshots/{id}/
```

Adapt these to the existing API structure.

The important logical operations are:

```text
request screenshot
upload screenshot
list screenshots
view screenshot metadata
retrieve screenshot
delete screenshot
```

---

# Phase 26 — Frontend UI

Add a screenshot action to the client/device administration interface.

Example:

```text
Device: DESKTOP-ABC123

[ View ] [ Request Screenshot ] [ ... ]
```

When clicked:

```text
Request Screenshot?
This will capture the current screen of the selected managed device.

[Cancel] [Request]
```

After requesting:

```text
Screenshot requested...
```

Then show status:

```text
Pending
Capturing
Uploading
Completed
Failed
```

---

# Phase 27 — Screenshot History

Provide a screenshot history page or section.

Example:

```text
Screenshots — DESKTOP-ABC123

Date/Time             File                         Status
----------------------------------------------------------------
2026-08-23 15:00:12   DESKTOP-ABC123-...png       Completed
2026-08-23 14:30:05   DESKTOP-ABC123-...png       Completed
2026-08-23 13:45:20   DESKTOP-ABC123-...png       Failed
```

Allow the administrator to view a screenshot.

---

# Phase 28 — Preview and Download

For completed screenshots, provide:

```text
[View]
[Download]
```

The actual storage path should never be exposed directly if the application architecture doesn't require it.

Serve the file through an authenticated endpoint.

---

# Phase 29 — Image Access Authorization

Screenshots may contain sensitive information.

Protect them with the same authorization model as managed-device information.

Do not make:

```text
/storage/screenshots/...
```

publicly accessible by default.

Prefer:

```text
GET /api/screenshots/{id}/file/
```

where the backend verifies access before returning the image.

---

# Phase 30 — Storage Cleanup

Screenshots can consume significant disk space.

Add a retention policy.

Example:

```yaml
screenshots:
  retention_days: 30
```

Possible cleanup strategy:

```text
scheduled cleanup
     ↓
find screenshots older than retention period
     ↓
delete file
     ↓
delete metadata
```

Do not delete recent screenshots accidentally.

If the project does not want automatic deletion yet, make the cleanup mechanism configurable but disabled initially.

---

# Phase 31 — Security and Privacy Logging

For each screenshot request, keep an audit record:

```text
requester
target client
requested_at
captured_at
uploaded_at
status
filename
```

Do not store screenshot pixels in application logs.

Do not log base64 image data.

Do not expose screenshot contents in debug logs.

---

# Phase 32 — Client Cleanup

After successful upload:

```text
temporary screenshot
        |
        v
upload confirmed
        |
        v
delete temporary file
```

On failure:

```text
temporary screenshot
        |
        v
retry
        |
        +---- success → delete
        |
        +---- final failure → delete according to retention policy
```

Never let the client accumulate screenshots indefinitely.

---

# Phase 33 — Error Handling

Handle at least:

### Capture errors

* no display available;
* screenshot library failure;
* access/desktop-session issues;
* multiple monitor errors.

### File errors

* temp directory unavailable;
* permission denied;
* insufficient disk space.

### Upload errors

* server unavailable;
* timeout;
* HTTP 4xx;
* HTTP 5xx;
* authentication failure;
* file too large.

### Command errors

* invalid command;
* expired command;
* duplicate command;
* unknown client;
* unauthorized command.

All errors should be logged clearly.

---

# Phase 34 — Important Windows Session Consideration

Determine whether the client agent runs:

```text
in the interactive user session
```

or:

```text
as a Windows service/session 0
```

This is critical because screenshots of an interactive desktop are not necessarily available to a process running in a non-interactive service session.

Before implementing the capture function:

1. Verify how the current client is launched.
2. Verify which Windows session it runs in.
3. Test screenshot capture while a user is logged in.
4. Test behavior when the workstation is locked.
5. Test behavior when no interactive user is logged in.

Do not assume that a service process can automatically capture the interactive desktop.

If the current architecture uses a user-session agent plus a privileged service, keep the screenshot capture in the component that has access to the interactive desktop, while keeping server communication where it already belongs.

---

# Phase 35 — Test the Screenshot Feature

## Test 1 — Basic Capture

```text
Server
  ↓
Request screenshot
  ↓
Client captures
  ↓
Upload
  ↓
Server stores PNG
```

Verify the image opens correctly.

---

## Test 2 — Filename

Expected:

```text
DESKTOP-ABC123-20260823-150012.png
```

Verify:

* meaningful device name;
* valid timestamp;
* correct extension;
* no invalid path characters.

---

## Test 3 — Multiple Screens

If supported:

```text
Monitor 1
Monitor 2
```

Verify the chosen behavior.

---

## Test 4 — Duplicate Command

Send the same command ID twice.

Expected:

```text
One screenshot only.
```

---

## Test 5 — Offline Client

Request screenshot while client is offline.

Expected:

```text
PENDING / NOT_REACHABLE
```

not a crash or indefinite request.

---

## Test 6 — Server Goes Offline During Upload

Expected:

```text
Capture succeeds
Upload fails
Retry
Eventually cleanup
```

---

## Test 7 — Large Screenshot

Verify server rejects files exceeding the configured limit.

---

## Test 8 — Unauthorized User

Attempt screenshot request using an account without permission.

Expected:

```text
403 Forbidden
```

or the equivalent authorization response used by the project.

---

## Test 9 — Storage

Verify:

```text
storage/
    screenshots/
        ...
```

contains the actual image.

Verify the database metadata points to the correct file.

---

## Test 10 — Client Stability

While capturing/uploading, verify:

* passive network discovery continues;
* DHCP continues;
* forbidden process scanner continues;
* heartbeat continues;
* command processing continues.

The screenshot operation must not freeze the entire client.

---

# Phase 36 — Backend Tests

Create tests for:

* screenshot request authorization;
* valid screenshot upload;
* invalid MIME type;
* invalid file extension;
* oversized file;
* invalid client;
* invalid command ID;
* duplicate command ID;
* screenshot metadata creation;
* screenshot retrieval authorization;
* screenshot deletion authorization;
* retention cleanup.

---

# Phase 37 — Client Tests

Create tests/mocks for:

* valid command;
* expired command;
* duplicate command;
* screenshot capture success;
* screenshot capture failure;
* upload success;
* upload failure;
* retry;
* cleanup;
* filename generation;
* multiple monitor behavior;
* no interactive session.

---

# Phase 38 — End-to-End Test

Run the complete scenario:

```text
Administrator
      |
      | Click "Request Screenshot"
      v
Server
      |
      | REQUEST_SCREENSHOT
      v
Client
      |
      | validate command
      v
ScreenshotManager
      |
      | capture
      v
DESKTOP-ABC123-20260823-150012.png
      |
      | multipart upload
      v
Server
      |
      | validate
      v
storage/screenshots/
      |
      v
Screenshot Metadata
      |
      v
Frontend
      |
      v
Administrator views screenshot
```

---

# Phase 39 — Recommended Data Model

If persistent screenshot history is required, use something conceptually like:

```text
Screenshot
--------------------------------
id
client_id
command_id
requested_by
device_name
filename
storage_path
mime_type
file_size
status
requested_at
captured_at
uploaded_at
created_at
```

Optional:

```text
width
height
monitor_count
```

---

# Phase 40 — Final Architecture

The target architecture should look like:

```text
                         CENTRAL SERVER
                               |
                    +----------+----------+
                    |                     |
               Command API            Screenshot API
                    |                     |
                    v                     ^
             REQUEST_SCREENSHOT     Upload Image
                    |                     |
                    v                     |
              WINDOWS CLIENT              |
                    |                     |
             Command Handler              |
                    |                     |
                    v                     |
             Screenshot Worker             |
                    |                     |
                    v                     |
             Screenshot Manager            |
                    |                     |
                    v                     |
             Temporary PNG                 |
                    |                     |
                    +---------------------+
                              |
                              v
                      Central Storage
                              |
                              v
                       Screenshot DB
                              |
                              v
                         Admin UI
```

---

# Implementation Order

Implement in this order:

1. **Inspect current command/communication architecture.**
2. **Inspect Windows client execution/session model.**
3. **Create ScreenshotManager abstraction.**
4. **Implement local screenshot capture.**
5. **Implement meaningful filename generation.**
6. **Implement temporary-file handling.**
7. **Add `REQUEST_SCREENSHOT` command.**
8. **Add command validation and idempotency.**
9. **Add screenshot upload endpoint.**
10. **Add server-side image validation.**
11. **Store images under `storage/screenshots/`.**
12. **Add screenshot metadata model.**
13. **Add authenticated screenshot retrieval.**
14. **Add server-side screenshot request history.**
15. **Add frontend "Request Screenshot" action.**
16. **Add screenshot history/viewer.**
17. **Add cleanup/retention configuration.**
18. **Add client/server tests.**
19. **Run complete end-to-end testing.**
20. **Only then deploy to additional managed clients.**

---

# Important Design Rules

## Rule 1 — Explicit Request Only

Do not implement automatic periodic screenshots.

A screenshot should happen only after an authenticated server request.

## Rule 2 — Do Not Block the Agent

Screenshot capture/upload must run independently from:

* passive network discovery;
* DHCP;
* forbidden-process monitoring;
* heartbeat;
* command handling.

## Rule 3 — Protect Stored Screenshots

Screenshots can contain sensitive information.

They must be protected by the application's authentication and authorization model.

## Rule 4 — Never Trust Client Filenames

The server must sanitize and/or generate the final storage filename.

## Rule 5 — Verify File Content

Do not trust a `.png` or `.jpg` extension alone.

Validate that the uploaded file is actually an image.

## Rule 6 — Keep Audit History

Every screenshot must be traceable to:

```text
who requested it
which client produced it
when it was requested
when it was captured
when it was uploaded
where it is stored
```

## Rule 7 — Clean Up Temporary Files

The client must not accumulate screenshots indefinitely.

## Rule 8 — Understand Windows Sessions

Verify whether the screenshot component runs in the interactive user's Windows session. Do not assume a Windows service running in Session 0 can directly capture the user's desktop.

---

# Implementation Notes — 2026-08-23

## Initial architecture review

* The Windows client has two launch modes: `client/service.py` runs `client.py` as the `NetworkClient` Windows service, while `client/user_agent.py` launches the same client loop from the interactive Task Scheduler task defined in `client/install_user_logon_task.ps1`.
* Screenshot capture must run in the interactive user-session agent. The service runs in Session 0 and cannot be assumed to access the signed-in user's desktop.
* Both launch modes currently register with the same MAC-derived client ID. A remote screenshot command cannot yet reliably target the interactive agent rather than the Session 0 service; agent-role/session identity must be added before command integration.
* The server's existing socket command transport is `server_components.server_lib.execute_client_command`. It should be reused rather than creating another command channel.
* The REST API currently has no operator authentication or authorization and permits command dispatch. This implementation follows the requested trusted-private-network assumption; access control remains a deployment follow-up.
* `client/screenshot_manager.py` provides a local, explicit-call-only ScreenshotManager. It captures the entire virtual desktop as a PNG, uses UTC collision-resistant sanitized filenames, stages files atomically in a bounded temporary directory, and does not schedule captures or open network listeners.
* The interactive agent now registers with `agent_role=interactive`; the server keeps its connection separately from the Session 0 service and routes `REQUEST_SCREENSHOT` only to it.
* `POST /api/v1/clients/{client_id}/screenshot` dispatches the existing TCP command, validates the returned PNG signature/chunks/CRC/image data, stores it under `server/storage/screenshots/<client-id>/`, and persists a `screenshots` metadata record including `requested_by`.
* Failed socket delivery retains the temporary screenshot for bounded `ScreenshotManager` cleanup rather than deleting it immediately; successful delivery removes it.
* `client/tests/test_screenshot_manager.py` covers filename safety, capture success/failure cleanup, bounded temporary-file cleanup, and interactive registration. `server/tests/test_screenshot_storage.py` covers PNG validation and storage. `server/tests/test_screenshot_requests.py` covers interactive dispatch and unavailable-agent handling.

## Next safe implementation sequence

1. Add distinct registration identity for the interactive user-session agent without breaking the service identity.
2. Implement authenticated operator authorization and audit attribution for sensitive command execution.
3. Define a signed/traceable `REQUEST_SCREENSHOT` command with command ID, target agent role, creation/expiry timestamps, and duplicate protection.
4. Wire the command only to the interactive agent's background screenshot worker; add bounded retry/upload and server-side validated storage.

# Definition of Done

The feature is complete when:

* [ ] Server can request a screenshot for a specific client.
* [ ] Only authorized users can request screenshots.
* [ ] Client validates the screenshot command.
* [ ] Client captures the current screen.
* [ ] Screenshot filename contains device name + timestamp.
* [ ] Screenshot is uploaded successfully.
* [ ] Server validates the image.
* [ ] Server stores the file under the existing `storage/screenshots` structure.
* [ ] Screenshot metadata is persisted.
* [ ] Screenshots can be listed by client.
* [ ] Authorized administrators can view/retrieve screenshots.
* [ ] Duplicate requests do not create duplicate screenshots.
* [ ] Upload failures are retried safely.
* [ ] Temporary client files are cleaned up.
* [ ] Screenshot capture does not block other client features.
* [ ] Interactive Windows-session behavior has been tested.
* [ ] Multiple-monitor behavior is documented.
* [ ] File size limits are enforced.
* [ ] Screenshot retention is configurable.
* [ ] Screenshot actions are auditable.
* [ ] End-to-end tests pass.

```