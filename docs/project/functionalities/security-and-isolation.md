# Security, Policy, Alerts, and Isolation

## Policy sources

The server owns working-hours, forbidden-process, and resource-protection
configuration. Policies are returned through the REST API and delivered to
connected clients. Clients cache the latest policy so enforcement can continue
during a short server outage.

## Forbidden processes and resource protection

`process_monitor.py` periodically evaluates running processes against the
server-provided rules. `process_scanner.py` performs scans and applies the
working-hours context. Repeated violations can produce alerts and, only when
`AUTO_ISOLATE_ON_ESCALATION=1`, trigger automatic isolation. Automatic
termination and isolation are opt-in operational decisions and should be
tested on a non-production client first.

`ResourceProtectionMonitor` applies CPU/RAM/disk thresholds from the resource
protection settings and uses the same alert path for violations.

## Alerts

Client alerts are sent over the TCP connection and persisted by the server.
Connection failures, policy violations, quarantine transitions, activity
events, and device/security findings can create alerts. Alert records include
severity, status, timestamps, client/device references, and investigation
metadata. The GUI supports `NEW`, `ACKNOWLEDGED`, and `RESOLVED` triage.

## Device classification and rogue analysis

`network_device_classification.py`, `device_features.py`, and the stored
classification repositories assign device roles and risk signals. Rogue
analysis combines managed/unmanaged state, vendor/identity quality, observed
network context, recency, and configured rules. The GUI exposes rogue devices,
classification review, labels, and related actions.

Classification is an assessment, not proof of malicious activity. Operators
should review the underlying observations before isolating a device.

## Network quarantine

`quarantine_manager.py` and `network_state_manager.py` implement platform-
specific firewall isolation, state transitions, duration limits, and audit
files. The server can request isolation, release, or status; the client owns
the local firewall operation and reports success/failure. The server preserves
the command and alert history.

Always verify the server address and recovery path before enabling isolation.
An incorrect quarantine rule can disconnect the client from the control plane.

