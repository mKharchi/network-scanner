# Phase 1: Per-window Activity Inference and Kismet Capture Analysis

**Status:** Analysis complete — no Kismet, retention, model, or runtime behaviour was changed.

**Approval checkpoint:** Do not delete raw captures or enable interval processing until the recommended inference fix is approved, implemented, and tested.

## Executive finding

`activity-rf-v1` must not yet be treated as a trusted live Wi-Fi activity classifier. It is a useful VNAT traffic-behaviour proxy candidate, but it was trained from wired PCAPs while its input vector includes Wi-Fi-specific frame counters. Those counters are constant in training and variable in live Kismet traffic. That is an out-of-distribution input problem which can produce confident but incorrect `streaming`, `file_transfer`, `chat`, `voip`, or `other` predictions.

The runtime implementation also predicts during a `GET` request, writes predictions as a side effect of that request, reloads all derived windows before filtering them, and does not have a durable completed-interval watermark. It cannot prove a raw capture was fully processed before deletion.

## Evidence collected

Inspection date: **2026-09-12**. Capture inspection was read-only.

| Area | Evidence | Consequence |
| --- | --- | --- |
| Training source | `activity_dataset.py` converts VNAT Ethernet/raw-IP PCAP records into synthetic `Data` observations and sets `retry=False`; it never creates management or control frames. | This is a network-behaviour proxy model, not a validated 802.11 activity model. |
| Training distribution | The 20,720 generated VNAT windows all have zero `management_packet_count`, `control_packet_count`, and `retry_packet_count`. | These counters have no valid learned live decision boundary. |
| Model features | `activity-features-v1` includes `data_packet_count`, `management_packet_count`, `control_packet_count`, `retry_packet_count`, and `retry_packet_ratio`. | The artifact accepts radio-specific values it never saw while training. |
| Live sample | A read-only parse of 9,954 usable observations from `Kismet-20260912-08-55-15-1.kismet` found 9,866 data frames, 88 management frames, and 945 retries. Of 596 windows, 255 contained management traffic and 92 contained retries; the maxima were 38 management frames and 562 retries per window. | Live input demonstrably differs from the VNAT training domain. |
| Runtime inference | `ActivityInferenceService.predict_device()` uses `load_all("traffic_windows")`, filters in memory, rebuilds smoothing per request, and persists prediction rows during that request. | UI refreshes repeat work; smoothing is query/lookback-dependent rather than interval-deterministic. |
| Shadow processing | `KismetMLShadowProcessor.run_once()` materializes observations in memory and rematerializes windows from currently available captures. Its default cap is 10,000 observations; the supplied timer service sets 1,000. | There is no completion proof that all rows in an interval were consumed before a capture could be removed. |
| Storage | `/home/adonis/kismet` held about 6.5 GiB: one 3,875,090,432-byte capture and one 320,729,088-byte capture. | The raw-storage issue is immediate, not theoretical. |
| Kismet configuration | Kismet 2026.09.0-e24ee9be2 uses `log_types=kismet`, `kis_log_packets=true`, and `kis_log_data_packets=true`. No `kis_log_*_timeout` setting is enabled. | Full packet payloads continue accumulating in the unified SQLite log. |
| Existing cleanup | The retention manager is age/disk-pressure based (48 hours, 5 GiB reserve, dry-run enabled). It protects active targets, journals/sidecars, and holds, but does not know ML completion state. | It must not be repurposed as interval deletion without a completion manifest. |

## The primary inference problem

The artifact has five output classes: `streaming`, `file_transfer`, `chat`, `voip`, and `other`. Its benchmark scores describe only the VNAT wired-PCAP domain; they do not establish accuracy on monitor-mode Wi-Fi captures.

The precise failure path is:

1. VNAT's importer deliberately creates only `Data` observations, so retry, management, and control counters are always zero.
2. The v1 model includes those fields as features.
3. Kismet parses real 802.11 frames, where retries and management traffic vary with signal quality, channel hopping, probe activity, and nearby-device noise.
4. A random forest does not know that a non-zero radio value is outside its training distribution. It can still return a high probability for one of its labels.

Schema compatibility is insufficient: matching field names does not mean that feature values have the same meaning or distribution.

There is a separate attribution limitation. Without an explicit client list, `build_traffic_windows()` treats every observed MAC as a possible client. This includes peers, access points, broadcast-associated observations, and randomized MACs. Future summaries may retain all observed MACs, but an unmapped or randomized MAC must remain an **observed identity** and must not be silently shown as a stable managed device.

## Recommended Phase 2 fix

Create a new, incompatible Wi-Fi-neutral artifact instead of weakening checks on `activity-rf-v1`.

1. Define `activity-features-v2` from portable traffic-shape features: packet/byte counts and rates, packet-size statistics, inter-arrival statistics, directional packet/byte ratios, burst metrics, periodicity, and missing-value indicators.
2. Exclude `data_packet_count`, `management_packet_count`, `control_packet_count`, `retry_packet_count`, and `retry_packet_ratio` from v2 training and live prediction. Continue collecting them as operational diagnostics only.
3. Retrain the existing VNAT-derived dataset under a new artifact ID, such as `activity-rf-v2`; version the feature schema and metadata so v1 cannot silently consume v2 inputs.
4. Store training reference statistics for every v2 feature. At live inference, detect material out-of-range values and return `unknown` with a `domain_shift` reason instead of accepting a high-probability class blindly.
5. Move inference out of `GET /api/v1/devices/{device_id}/activity`. A completed-interval worker must predict each complete window once, persist it idempotently, and persist/reconstruct the prior two probability vectors for the existing three-window smoother. The API becomes read-only.
6. Retain the current 0.55 confidence threshold as an initial safety gate. It is not calibration proof and should be tuned only after labelled local Wi-Fi validation data exists.

This does not claim that public wired data is fully calibrated for Wi-Fi. It removes known invalid inputs, makes uncertainty explicit, and creates a safe base for later local calibration.

## Capture rotation and deletion finding

Restarting `kismet-sensor.service` is not an acceptable interval mechanism. The unit creates the monitor VIF in `ExecStartPre` and deletes it in `ExecStopPost`, so a restart tears down the capture interface and creates a capture gap.

Kismet provides log listing, stop, and start controls, but its logging API warns that some log classes, including KismetDB, may permit only one logging instance. It also documents packet timeouts and a packet-drop API, but removing SQLite rows is not a guarantee that allocated file space will immediately shrink. Therefore this project must not assume that close/start rotation works for the installed Kismet version or that a timeout alone solves file growth.

Before implementing interval capture-use-delete, run this controlled non-production compatibility rehearsal against Kismet 2026.09.0-e24ee9be2:

1. Record Kismet PID, datasource UUID, monitor interface, channel state, active-log UUID, packet count, and capture filename.
2. Use the authenticated Kismet logging API to stop the active KismetDB log and start its replacement; do not restart the systemd service.
3. Confirm the same PID and datasource remain active, a new log appears, packets resume without a monitor-VIF rebuild, and the closed file opens cleanly read-only.
4. Treat an API refusal, unchanged filename, datasource loss, journal-only closure, or capture gap as failure. Delete nothing.

If sequential KismetDB close/start is unsupported, choose an alternative only after this rehearsal:

- add a rotating PCAP-NG input path with a metadata-only adapter;
- use supported bounded-log facilities while retaining sufficient verified interval history; or
- retain Kismet for investigation and move activity capture to the dedicated metadata sensor.

References: [Kismet logging API](https://www.kismetwireless.net/docs/api/logging/), [KismetDB timed logs](https://www.kismetwireless.net/docs/readme/logging/kismetdb/), and [Kismet logging configuration](https://www.kismetwireless.net/docs/readme/logging/logging/).

## Preconditions for Phase 3

Capture-use-delete may begin only after Phase 2 supplies all of the following:

- 10-minute UTC intervals produce exactly twenty complete, non-overlapping 30-second windows.
- A durable interval manifest records capture files, time bounds, source observation count, window count, prediction count, artifact version, and completion status.
- Retrying an interval is idempotent and cannot duplicate predictions or summaries.
- Raw deletion is blocked unless the associated manifest is `COMPLETED`.
- Active files, SQLite sidecars, investigation holds, malformed captures, and failed/partial intervals remain preserved.
- The daily summarizer can generate seven-day retained database summaries from the interval prediction files before those files are removed.
- The activity API is read-only and distinguishes `unknown`, `low_confidence`, `domain_shift`, and `no_recent_window`.

## Approval checkpoint

Phase 1 stops here. Approve or amend the `activity-features-v2` fix before Phase 2 changes the model, inference path, or storage workflow. Capture rotation and raw-file deletion remain out of scope until the inference fix is validated.
