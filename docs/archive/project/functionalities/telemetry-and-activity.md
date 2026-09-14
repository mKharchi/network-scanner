# Telemetry, Flows, Activity, and Screenshots

## Hardware and health telemetry

The client collects CPU, memory, disk, network, system, and process data for
health views and diagnostics. `client_lib.py` formats command responses;
`client_health.py` and related server services normalize health records and
evaluate status. The server stores current client health in the client record
and emits health events for the console.

## Packet and flow telemetry

`packet_observer.py` reads locally observed traffic when the platform and
permissions allow it. `packet_extractor.py` normalizes packet fields,
`scope_filter.py` applies the configured observation scope, and
`telemetry_packet_writer.py` / `packet_storage.py` persist bounded local data.
`flow_aggregator.py` groups traffic into time windows and
`flow_query.py` serves requested flow history.

The packet pipeline is observational. It is separate from Kismet capture and
does not copy raw Kismet databases to the server.

## Activity logs

`event_monitor.py` watches configured user/file activity and writes local event
records. `activity_window_aggregator.py` groups activity into windows;
`sync_manager.py` sends eligible summaries/logs to the server. The server
stores metadata and JSON activity files, and the GUI exposes searchable
activity pages.

Ordinary file activity is treated as log data. It is not automatically turned
into a real-time security alert unless the event is an explicit security or
policy event.

## Screenshots

Screenshots are captured only after an explicit server action routed to the
interactive user-session agent. `screenshot_manager.py` captures/compresses
the desktop; the server validates/stores the image through
`screenshot_storage.py`, associates metadata with the requesting client, and
serves it through the screenshot API. The server generates storage paths; the
client cannot choose an arbitrary server filename.

## Retention and privacy

Client telemetry, activity, screenshots, and packet storage have separate
paths and retention controls. Do not treat a screenshot or raw packet capture
as ordinary inventory data. Before changing retention, document who is
authorized to inspect it, how long it is needed, and how deletion is audited.

