# Client Agent

## What it does

The client agent is the endpoint-side runtime. It connects to the server,
reports hardware and network state, stores bounded local state, receives
commands, enforces policies, captures user-session evidence when enabled, and
reconnects after a transport failure.

## Entrypoints and roles

| Entrypoint | Use |
| --- | --- |
| `client/app/client.py` | Current implementation and lifecycle |
| `client/client.py` | Flat-layout compatibility launcher |
| `client/user_agent.py` | Interactive signed-in-user launcher |
| `client/service.py` | Windows service wrapper using `pywin32` |
| `client/install_user_logon_task.ps1` | Recommended user-session task installer |

The registration payload includes the client version, platform, MAC/identity,
hostname, addresses, and `agent_role`. The combined user-session role is the
normal installation when screenshots and user activity are required. The
service wrapper is suitable for machine-wide background execution but does not
share the interactive user's profile.

## Startup lifecycle

`start_client()`:

1. Loads `config/.env` and the legacy root `.env` fallback.
2. Creates `logs/` and `storage/` if possible.
3. Writes startup diagnostics and checks local storage permissions.
4. Loads cached forbidden-process and resource-protection policies.
5. Starts local workers: process/resource monitors, packet observer, DHCP and
   passive protocol listeners, telemetry/flow writers, activity aggregation,
   device enrichment, scope filtering, and retention cleanup.
6. Connects to `SERVER_IP:SERVER_PORT` and sends `REGISTER`.
7. Receives policy/command frames while sending heartbeats and asynchronous
   reports.
8. Stops workers and reconnects when the socket closes.

## Local subsystems

| Subsystem | Main modules | Output |
| --- | --- | --- |
| Identity/version | `client_lib.py`, `device_model.py` | Registration and heartbeat data |
| Process policy | `process_scanner.py`, `process_monitor.py` | Violations, alerts, optional termination |
| Resource protection | `process_monitor.py` | CPU/RAM/disk policy events |
| Neighbourhood | `network_neighbour_collector.py`, `neighbourhood.py` | Daily snapshots and reports |
| DHCP/passive protocols | `dhcp_listener.py`, `passive_protocol_listener.py` | Passive observations |
| Packet/flow telemetry | `packet_observer.py`, `packet_storage.py`, `flow_aggregator.py` | Protocol and flow records |
| Activity | `event_monitor.py`, `activity_window_aggregator.py` | Local activity logs |
| Screenshots | `screenshot_manager.py` | Explicit server-requested captures |
| Isolation | `quarantine_manager.py`, `network_state_manager.py` | Firewall state and audit |
| Updates | `client_lib.py`, `updater/updater.py` | Staged package results and rollback |

## Kismet boundary

Kismet is not a client feature. The old client-side Kismet listener and its
tests were removed after the server-owned Kismet path and full regressions
passed. Clients never open `.kismet` databases and do not manage monitor mode.

## Local state and privacy

Configuration is kept outside `client/app/` so server-managed app updates do
not overwrite endpoint settings. The client stores logs, caches, telemetry,
neighbourhood snapshots, package state, and quarantine audit state below
`client/storage/` and `client/logs/`. Configure retention and screenshot policy
according to the deployment's authorization requirements.

