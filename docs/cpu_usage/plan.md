# Client Resource Protection & Forbidden Process Management

## Objective

Implement two features in the existing client/server platform:

### Feature A — Automatic Resource Protection

The client already has a diagnosis/health system that measures:

- CPU usage
- Memory usage
- Disk usage

Extend the client so that when system resource usage becomes critically high, it can automatically identify the process responsible and terminate it **without requiring server intervention**.

### Feature B — Forbidden Process Management

Restore the missing Settings page/section that allows administrators to manage the list of forbidden processes.

The forbidden-process configuration must be centrally managed by the server but enforced locally by every client.

---

# Part 1 — Automatic Resource Protection

## 1. Reuse the existing health/diagnosis infrastructure

Do not create another independent CPU/memory monitoring system if the current health feature already collects:

```text
CPU usage
Memory usage
Disk usage
```

First inspect the existing implementation and identify:

```text
health collector
resource metrics
process enumeration
client monitoring loop
configuration system
logging system
```

Reuse existing components wherever possible.

The new feature should consume the existing resource information rather than duplicating it.

---

# 2. Add a local resource-protection configuration

Create configuration similar to:

```json
{
  "resource_protection": {
    "enabled": true,

    "cpu": {
      "enabled": true,
      "threshold": 85,
      "sustained_seconds": 30
    },

    "memory": {
      "enabled": true,
      "threshold": 90,
      "sustained_seconds": 30
    },

    "cooldown_seconds": 300
  }
}
```

The exact default values can be adjusted to match the existing project conventions.

Important:

### Do not trigger on a single CPU sample.

For example:

```text
CPU = 91%
```

should not immediately result in killing a process.

Instead:

```text
CPU > threshold
       ↓
start timer
       ↓
still above threshold?
       ↓
yes
       ↓
identify candidate
       ↓
terminate candidate
```

This prevents temporary spikes from causing unnecessary process termination.

---

# 3. CPU protection logic

When:

```text
CPU >= configured threshold
```

for the configured sustained period:

1. Enumerate running processes.
2. Determine CPU consumption of each process.
3. Sort processes by CPU usage.
4. Identify the highest consuming **eligible** process.
5. Verify that it is safe to terminate.
6. Terminate it.
7. Wait briefly.
8. Re-measure CPU.
9. If CPU has returned to a healthy level, stop intervention.
10. Otherwise repeat according to configured safety limits.

Example:

```text
System CPU = 91%

Processes:

Chrome       42%
Python       31%
Explorer      4%
System        3%
Client        2%

Candidate = Chrome
```

The client can terminate Chrome **only if Chrome is eligible according to the safety rules**.

---

# 4. Never kill protected processes

Create a protected-process mechanism.

At minimum, the client must never automatically terminate:

```text
itself / client process
Windows critical system processes
system services required for Windows operation
core security processes
```

Also exclude:

```text
system
idle
registry
smss.exe
csrss.exe
wininit.exe
services.exe
lsass.exe
winlogon.exe
```

and other critical processes identified by the existing implementation/environment.

Do not rely solely on process names.

Where possible, validate the process identity/path and other available process metadata.

---

# 5. Never automatically kill an arbitrary process just because it uses CPU

The resource-protection system should have an **eligibility check**.

Conceptually:

```text
highest CPU process
        ↓
is it the client?
        ↓ yes → SKIP
        ↓ no
is it protected?
        ↓ yes → SKIP
        ↓ no
is it explicitly excluded?
        ↓ yes → SKIP
        ↓ no
is it forbidden?
        ↓ yes → TERMINATE
        ↓ no
is automatic termination allowed?
        ↓
       ...
```

For the first implementation, I would make automatic termination conservative.

A good policy is:

### Priority 1

Terminate a process that is already in the forbidden-process list.

### Priority 2

Terminate a non-protected process explicitly marked as eligible for automatic resource termination.

### Otherwise

Do **not** kill an arbitrary process.

Instead log:

```text
RESOURCE_PRESSURE
CPU = 94%
highest process = xyz.exe
action = SKIPPED
reason = process not eligible for automatic termination
```

This prevents the feature from becoming dangerous.

---

# 6. Memory protection

Apply similar logic to memory.

Example:

```text
Memory = 93%
```

for a sustained period.

Then:

```text
enumerate processes
       ↓
calculate memory usage
       ↓
sort descending
       ↓
find eligible candidate
       ↓
terminate
       ↓
recheck memory
```

Use the existing health/diagnosis metrics where possible.

---

# 7. Prevent kill loops

Add a cooldown.

For example:

```text
10:00 → terminate process A
10:01 → CPU still high
```

Do not immediately repeatedly terminate processes without control.

Maintain:

```text
last_intervention_time
intervention_count
```

and enforce:

```text
max interventions per window
cooldown between interventions
```

Example:

```json
{
  "max_interventions_per_hour": 3,
  "cooldown_seconds": 300
}
```

This prevents:

```text
CPU high
→ kill
→ CPU high
→ kill
→ CPU high
→ kill
→ kill everything
```

---

# 8. Re-check after termination

After terminating a process:

```text
terminate
   ↓
wait 1–3 seconds
   ↓
collect CPU/memory again
```

If:

```text
CPU < threshold
```

stop.

If still high:

```text
CPU > threshold
```

perform another candidate evaluation, subject to the intervention limits.

---

# 9. Logging

Every intervention must be logged.

Example:

```json
{
  "event": "RESOURCE_PROTECTION_ACTION",
  "timestamp": "...",
  "resource": "cpu",
  "system_usage": 93.4,
  "threshold": 85,
  "process_name": "example.exe",
  "pid": 1234,
  "process_cpu": 48.2,
  "action": "terminated",
  "reason": "sustained_resource_pressure"
}
```

Also log skipped candidates:

```json
{
  "event": "RESOURCE_PROTECTION_SKIP",
  "resource": "cpu",
  "process_name": "example.exe",
  "pid": 1234,
  "reason": "protected_process"
}
```

This is important for diagnosis and future debugging.

---

# Part 2 — Forbidden Processes

## 10. Restore the Settings functionality

Inspect the existing frontend and backend architecture first.

Find:

```text
Settings page
settings routes
settings API
configuration models/storage
client configuration mechanism
existing forbidden-process references
```

There appears to have previously been a forbidden-process feature, so **reuse the old implementation if remnants still exist instead of creating a parallel system**.

---

# 11. Forbidden-process settings UI

Restore a section such as:

```text
Settings
│
├── General
├── Client Configuration
├── Resource Protection
│
└── Forbidden Processes
```

The UI should allow:

```text
[ + Add Process ]

Process name       Status       Actions
------------------------------------------------
chrome.exe         Enabled      Edit / Remove
malware.exe        Enabled      Edit / Remove
game.exe           Disabled     Edit / Remove
```

At minimum support:

- add
- remove
- enable/disable
- search/filter
- save

---

# 12. Forbidden-process configuration

Prefer structured records instead of a plain list.

Example:

```json
{
  "name": "example.exe",
  "enabled": true,
  "terminate_on_detection": true,
  "resource_protection_eligible": true
}
```

This gives you flexibility later.

For example, a process can be:

```text
forbidden
```

without necessarily being:

```text
allowed to be killed automatically under resource pressure
```

Those are conceptually different policies.

---

# 13. Server → Client configuration synchronization

The server remains the source of truth.

```text
Admin
  ↓
Settings UI
  ↓
Server configuration
  ↓
Client configuration sync
  ↓
Client enforcement
```

The client should maintain a local copy so it can enforce forbidden processes **without waiting for the server**.

This is particularly important because your new resource-protection feature is intentionally autonomous.

---

# 14. Client-side forbidden-process monitor

The client should periodically inspect running processes.

For example:

```text
every N seconds
       ↓
enumerate processes
       ↓
compare against forbidden-process rules
       ↓
match?
       ↓
yes
       ↓
terminate if rule permits
       ↓
log action
```

Do not make this dependent on the server being online.

---

# 15. Avoid repeatedly terminating the same process

Maintain a short-lived local state:

```text
PID
process name
last detection
last action
```

This avoids excessive logging and repeated operations against the same process.

If the process restarts with a different PID, it should be detected again.

---

# Part 3 — Interaction Between the Two Features

These two systems should share the **process-management layer**, but their policies should remain separate.

```text
                PROCESS MANAGER
                       │
          ┌────────────┴────────────┐
          │                         │
   Forbidden Process          Resource Protection
      Monitor                     Monitor
          │                         │
          ▼                         ▼
   forbidden rule             CPU/memory pressure
          │                         │
          └────────────┬────────────┘
                       ▼
                Safety Validation
                       │
                       ▼
                Process Termination
                       │
                       ▼
                     Log
```

This avoids having two separate pieces of code that independently implement:

```text
find process
check PID
terminate process
log termination
```

---

# Part 4 — Resource Management

Do not create several aggressive polling loops.

Prefer a single lightweight **process/resource monitoring service** that can provide data to:

```text
health/diagnosis
resource protection
forbidden-process detection
```

For example:

```text
Process Monitor
│
├── process enumeration
├── CPU usage
├── memory usage
├── process identity
└── process metadata
       │
       ├── Health
       ├── Resource Protection
       └── Forbidden Processes
```

This avoids repeatedly enumerating hundreds of processes from three independent loops.

---

# Part 5 — Configuration hierarchy

Use this hierarchy:

```text
SERVER CONFIGURATION
        │
        ▼
CLIENT LOCAL CONFIGURATION
        │
        ├── Forbidden processes
        ├── Resource protection enabled
        ├── CPU threshold
        ├── Memory threshold
        ├── cooldown
        └── intervention limits
```

The client must be able to continue operating safely if the server is unreachable.

---

# Part 6 — Safety requirements

Before implementing automatic termination, verify:

- client cannot terminate itself
- protected processes cannot be terminated
- system-critical processes cannot be terminated
- process identity is validated
- access-denied errors are handled
- process disappearing between enumeration and termination is handled
- race conditions are handled
- termination failures are logged
- cooldown exists
- maximum intervention count exists
- temporary resource spikes do not trigger termination
- disabled configuration means no automatic intervention

Do not use:

```text
CPU > 80% → kill highest CPU process
```

as the literal implementation.

Use:

```text
CPU pressure
    ↓
sustained threshold
    ↓
candidate selection
    ↓
safety validation
    ↓
policy validation
    ↓
termination
    ↓
verification
```

---

# Part 7 — Testing

Test the feature without relying on real system-critical processes.

Create controlled test processes that intentionally consume:

```text
CPU
memory
```

Then verify:

### CPU

```text
CPU below threshold
→ nothing happens

CPU temporarily spikes
→ nothing happens

CPU remains above threshold
→ eligible process selected

process terminated
→ CPU checked again
```

### Memory

Same test for memory pressure.

### Forbidden processes

```text
forbidden process starts
→ detected
→ terminated
→ event logged
```

### Safety

```text
protected process
→ detected as high resource consumer
→ skipped
→ logged
```

### Server unavailable

```text
server offline
→ local configuration still works
→ resource protection still works
→ forbidden-process enforcement still works
```

---

# Implementation order

Have the IDE AI implement in this order:

```text
1. Inspect existing health/diagnosis implementation
          ↓
2. Inspect existing forbidden-process remnants
          ↓
3. Restore Settings UI
          ↓
4. Restore server-side forbidden-process configuration
          ↓
5. Implement client configuration synchronization
          ↓
6. Build/reuse shared Process Monitor
          ↓
7. Implement Forbidden Process Monitor
          ↓
8. Implement Resource Protection Monitor
          ↓
9. Add safety/protected-process layer
          ↓
10. Add intervention cooldown/limits
          ↓
11. Add logging
          ↓
12. Add tests
          ↓
13. Test manually with controlled CPU/memory stress
          ↓
14. Run existing frontend/backend/client tests
```

### One architectural principle

> **Do not duplicate existing health, settings, process-monitoring, or configuration mechanisms. Inspect the current codebase first and integrate into the existing architecture. Preserve existing behavior and APIs unless a change is required for this feature.**
