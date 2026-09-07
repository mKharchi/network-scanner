"""
Phase 9 — End-to-End tests against real Kismet capture files.
Exercises the full KismetInvestigationService stack with actual data.
"""
import json
import os
import sys
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from datetime import datetime, timezone
from server_components.kismet_service import KismetInvestigationService

PASS = "\033[32m✅ PASS\033[0m"
FAIL = "\033[31m❌ FAIL\033[0m"
INFO = "\033[36mℹ️  INFO\033[0m"

passed = 0
failed = 0

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        print(f"{PASS}  {name}")
        passed += 1
    else:
        print(f"{FAIL}  {name}  {detail}")
        failed += 1

# ── Bootstrap ────────────────────────────────────────────────────────────────
capture_root = os.getenv("KISMET_CAPTURE_ROOT")
svc = KismetInvestigationService(
    capture_dirs=[capture_root] if capture_root else None,
)

# ── E9.1 File discovery ───────────────────────────────────────────────────────
print("\n── E9.1  File Discovery ──────────────────────────────────────────")
files = svc.find_kismet_database_files()
check("E9.1.1  Discovers real .kismet files", len(files) > 0, f"got {len(files)}")
expected_capture = os.getenv("KISMET_EXPECTED_CAPTURE")
if expected_capture:
    check("E9.1.2  Expected capture is included", any(expected_capture in f.name for f in files))
check("E9.1.3  All discovered files actually exist on disk",
      all(f.exists() for f in files))
print(f"{INFO}  {len(files)} files: {[f.name for f in files]}")

# ── E9.2 Known device query — full history ────────────────────────────────────
print("\n── E9.2  Known Device — All History ─────────────────────────────")
KNOWN_MAC = "B0:3C:DC:95:39:36"   # confirmed present in Phase-1 capture

def fake_device(mac=KNOWN_MAC):
    return {"mac": mac, "ip_address": None, "hostname": None, "vendor": None}

svc.resolve_device = lambda _: fake_device()
result_all = svc.query_wireless_observations("any", lookback_minutes="all")

check("E9.2.1  status == 'ok'", result_all["status"] == "ok")
check("E9.2.2  source == 'KISMET_SERVER'", result_all["source"] == "KISMET_SERVER")
check("E9.2.3  Returns real observations (> 0)", result_all["summary"]["observation_count"] > 0,
      f"got {result_all['summary']['observation_count']}")
check("E9.2.4  query_window.start == 'unbounded'", result_all["query_window"]["start"] == "unbounded")
check("E9.2.5  capture_files_scanned > 0", result_all["capture_files_scanned"] > 0)

obs_count = result_all["summary"]["observation_count"]
print(f"{INFO}  {obs_count} observations, {result_all['capture_files_scanned']} files scanned")

# ── E9.3 Observations are newest-first ───────────────────────────────────────
print("\n── E9.3  Ordering ───────────────────────────────────────────────")
if obs_count >= 2:
    secs = [o["epoch_sec"] for o in result_all["observations"]]
    check("E9.3.1  Observations newest-first", secs == sorted(secs, reverse=True))

# ── E9.4 Per-observation structure ───────────────────────────────────────────
print("\n── E9.4  Observation Field Integrity ────────────────────────────")
REQUIRED_OBS_KEYS = {"timestamp","epoch_sec","epoch_usec","role","source_mac","destination_mac",
                     "transmitter_mac","frame_type","frame_subtype","signal_dbm","frequency_khz",
                     "channel","packet_length","sensor","source","capture_file","packet_hash"}
all_have_keys = all(REQUIRED_OBS_KEYS <= set(o.keys()) for o in result_all["observations"])
check("E9.4.1  All observations have required fields", all_have_keys)

all_have_provenance = all(o.get("source") == "KISMET_SERVER" for o in result_all["observations"])
check("E9.4.2  All observations carry source=KISMET_SERVER", all_have_provenance)

valid_roles = {"SOURCE","TRANSMITTER","DESTINATION","OBSERVED"}
all_valid_roles = all(o["role"] in valid_roles for o in result_all["observations"])
check("E9.4.3  All roles are valid", all_valid_roles)

if result_all["observations"]:
    sample = result_all["observations"][0]
    check("E9.4.4  timestamp is ISO-8601 string", isinstance(sample["timestamp"], str) and "T" in sample["timestamp"])
    check("E9.4.5  epoch_sec is integer", isinstance(sample["epoch_sec"], int))
    check("E9.4.6  capture_file is non-empty string", isinstance(sample["capture_file"], str) and len(sample["capture_file"]) > 0)
    print(f"{INFO}  Sample: role={sample['role']} frame={sample['frame_type']}:{sample['frame_subtype']} "
          f"ch={sample['channel']} rssi={sample['signal_dbm']}dBm ts={sample['timestamp']}")

# ── E9.5 Exact time-window query (10-minute window inside Phase-1 capture) ────
print("\n── E9.5  10-Minute Exact Window Query ───────────────────────────")
# Phase-1 capture: 2026-09-07 10:38:23 – 11:11:52 UTC
window_start = "2026-09-07T10:45:00Z"
window_end   = "2026-09-07T10:55:00Z"
result_10m = svc.query_wireless_observations(
    "any", start_time=window_start, end_time=window_end)

check("E9.5.1  10m query returns ok", result_10m["status"] == "ok")
check("E9.5.2  query_window.start matches requested start", result_10m["query_window"]["start"].startswith("2026-09-07T10:45"))
check("E9.5.3  lookback_minutes ~= 10", abs((result_10m["query_window"]["lookback_minutes"] or 0) - 10.0) < 0.1)
obs_10m = result_10m["summary"]["observation_count"]
check("E9.5.4  Returns real observations in 10m window (> 0)", obs_10m > 0, f"got {obs_10m}")
print(f"{INFO}  {obs_10m} observations in 10-minute window")

# Verify no packet falls outside the window
if result_10m["observations"]:
    start_ts = datetime(2026,9,7,10,45,0,tzinfo=timezone.utc).timestamp()
    end_ts   = datetime(2026,9,7,10,55,0,tzinfo=timezone.utc).timestamp()
    all_in_window = all(
        start_ts <= (o["epoch_sec"] + o["epoch_usec"]/1_000_000) <= end_ts
        for o in result_10m["observations"]
    )
    check("E9.5.5  All returned packets are strictly within [start, end]", all_in_window)

# ── E9.6 Noise filtering ──────────────────────────────────────────────────────
print("\n── E9.6  Noise Filtering ────────────────────────────────────────")
result_noisy = svc.query_wireless_observations("any", lookback_minutes="all", include_noise=True)
result_clean = svc.query_wireless_observations("any", lookback_minutes="all", include_noise=False)
check("E9.6.1  noise_filtered=True when include_noise=False", result_clean["summary"]["noise_filtered"] is True)
check("E9.6.2  noise_filtered=False when include_noise=True", result_noisy["summary"]["noise_filtered"] is False)
check("E9.6.3  Noisy result has >= clean result (or equal if no noise)",
      result_noisy["summary"]["total_matched_packets"] >= result_clean["summary"]["total_matched_packets"])
print(f"{INFO}  Clean: {result_clean['summary']['observation_count']} obs  |  With noise: {result_noisy['summary']['observation_count']} obs")

# ── E9.7 Limit enforcement ────────────────────────────────────────────────────
print("\n── E9.7  Limit Enforcement ──────────────────────────────────────")
result_lim = svc.query_wireless_observations("any", lookback_minutes="all", limit=5)
check("E9.7.1  limit=5 returns at most 5 observations",
      result_lim["summary"]["observation_count"] <= 5, f"got {result_lim['summary']['observation_count']}")
check("E9.7.2  observation_count == len(observations)",
      result_lim["summary"]["observation_count"] == len(result_lim["observations"]))

# ── E9.8 Reversed range error ─────────────────────────────────────────────────
print("\n── E9.8  Error Handling ─────────────────────────────────────────")
try:
    svc.query_wireless_observations("any", start_time="2026-09-07T12:00:00Z", end_time="2026-09-07T10:00:00Z")
    check("E9.8.1  Reversed range raises ValueError", False, "no exception raised")
except ValueError as e:
    check("E9.8.1  Reversed range raises ValueError", "start_time must be earlier than end_time" in str(e))

# ── E9.9 Summary statistics from real data ────────────────────────────────────
print("\n── E9.9  RF Summary Statistics ──────────────────────────────────")
summary = result_all["summary"]
check("E9.9.1  channels list is sorted ascending", summary["channels"] == sorted(summary["channels"]))
check("E9.9.2  frame_types dict is non-empty", len(summary["frame_types"]) > 0)
check("E9.9.3  avg_signal_dbm is numeric or None", summary["avg_signal_dbm"] is None or isinstance(summary["avg_signal_dbm"], (int,float)))
if summary["avg_signal_dbm"]:
    check("E9.9.4  avg_signal_dbm is in plausible dBm range (-120 to -10)",
          -120 <= summary["avg_signal_dbm"] <= -10, f"got {summary['avg_signal_dbm']}")
print(f"{INFO}  Channels: {summary['channels']}")
print(f"{INFO}  Frame types: {json.dumps(summary['frame_types'], indent=2)[:200]}")
print(f"{INFO}  Avg RSSI: {summary['avg_signal_dbm']} dBm  Range: [{summary['min_signal_dbm']}, {summary['max_signal_dbm']}]")

# ── E9.10 Multi-session data (lookback covers multiple capture files) ──────────
print("\n── E9.10 Multi-Capture-File Coverage ────────────────────────────")
capture_files_in_result = {o["capture_file"] for o in result_all["observations"]}
check("E9.10.1  Observations come from at least 1 capture file", len(capture_files_in_result) >= 1)
print(f"{INFO}  Capture files in result: {sorted(capture_files_in_result)}")

# ── E9.11 get_sensor_health() ─────────────────────────────────────────────────
print("\n── E9.11 Sensor Health ──────────────────────────────────────────")
# Temporarily restore original resolve_device for health check
svc2 = KismetInvestigationService(
    capture_dirs=[capture_root] if capture_root else None,
)
health = svc2.get_sensor_health()
check("E9.11.1  status is ONLINE/DEGRADED/OFFLINE", health["status"] in {"ONLINE","DEGRADED","OFFLINE"})
check("E9.11.2  sensor field present", "sensor" in health)
check("E9.11.3  source == 'KISMET_SERVER'", health.get("source") == "KISMET_SERVER")
check("E9.11.4  process dict present", "process" in health and "running" in health["process"])
check("E9.11.5  interface dict present", "interface" in health and "name" in health["interface"])
check("E9.11.6  storage dict present", "storage" in health and "total_kismet_files" in health["storage"])
check(
    "E9.11.7  storage.total_kismet_files > 0",
    health["storage"]["total_kismet_files"] > 0,
    f"got {health['storage']['total_kismet_files']}",
)
check("E9.11.8  latest_capture dict present", "latest_capture" in health)
print(f"{INFO}  Health status: {health['status']}")
print(f"{INFO}  Process running: {health['process']['running']}  PID: {health['process']['pid']}")
print(f"{INFO}  Interface: {health['interface']['name']} state={health['interface']['state']}")
print(f"{INFO}  Storage: {health['storage']['total_kismet_files']} files  {health['storage']['total_kismet_bytes']//1024//1024} MB total")
print(f"{INFO}  Latest capture packets: {health['latest_capture']['packet_count']}")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  Phase 9 E2E: {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(0 if failed == 0 else 1)
