# Functionality Index

Each page below explains the user-visible behavior, implementation path, data
flow, configuration, and operational limits of one capability group.

| Capability | Documentation | Main implementation |
| --- | --- | --- |
| Server runtime and API | [server-runtime.md](server-runtime.md) | `server/server.py`, `server/api_server.py`, `server/server_components/server_lib.py` |
| Client agent | [client-agent.md](client-agent.md) | `client/app/client.py`, `client/app/client_lib.py` |
| Network discovery | [discovery-and-observations.md](discovery-and-observations.md) | `network_neighbour_collector.py`, `dhcp_listener.py`, `network_discovery.py` |
| Telemetry and activity | [telemetry-and-activity.md](telemetry-and-activity.md) | telemetry, flow, activity, packet, and screenshot modules |
| Security and isolation | [security-and-isolation.md](security-and-isolation.md) | process monitors, classification, alerts, quarantine |
| Remote actions | [remote-actions.md](remote-actions.md) | `action_framework.py`, `action_service.py`, client command handlers |
| Packages and updates | [packages-and-updates.md](packages-and-updates.md) | `package_service.py`, `action_service.py`, `client/updater/` |
| Spatial localization | [spatial-localization.md](spatial-localization.md) | `spatial_engine.py`, location repositories, GUI scenes |
| Kismet investigation | [kismet-investigation.md](kismet-investigation.md) | `kismet_service.py`, retention manager, systemd unit |
| GUI console | [gui.md](gui.md) | `server/gui/src/`, `api/client.ts` |
| Storage and data model | [storage-and-data-model.md](storage-and-data-model.md) | `scripts.sql`, storage repositories, JSON artifacts |

## Capability status language

- **Implemented** means the code path exists and has regression coverage.
- **Operationally verified** means it has also been exercised on the current
  Linux host or through the documented end-to-end workflow.
- **Compatibility/future** means code or contracts remain, but normal current
  operation does not depend on them.
- **Planned** means the idea is recorded but not presented as available.

