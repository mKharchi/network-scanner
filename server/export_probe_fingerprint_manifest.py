"""Append selected, decoded Kismet probe sessions to the local fingerprint manifest.

This curation utility intentionally reads Kismet captures through the same
metadata-only probe service used by the GUI.  It never copies a packet BLOB or
SSID body into the training manifest.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from server_components.kismet_service import KismetInvestigationService


DEFAULT_MANIFEST = Path("server/storage/kismet_ml/local_fingerprints/manifest.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--physical-device-guid", required=True)
    parser.add_argument("--capture-session", required=True)
    parser.add_argument("--condition", required=True, help="Controlled capture condition, e.g. channel-1-wifi-scan")
    parser.add_argument("--sensor-id", default="sensor-01")
    parser.add_argument("--start", required=True, help="UTC ISO-8601 or epoch start")
    parser.add_argument("--end", required=True, help="UTC ISO-8601 or epoch end")
    parser.add_argument("--source-mac", action="append", default=[], help="Observed source MAC; repeatable")
    parser.add_argument("--expected-mac", help="Stable expected MAC, when applicable")
    parser.add_argument("--mac-randomization", action="store_true")
    parser.add_argument("--subtype", choices=("all", "request", "response"), default="all")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--capture-dir", type=Path, action="append", help="Override Kismet capture directory; repeatable")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def build_records(args: argparse.Namespace) -> List[Dict[str, Any]]:
    service = KismetInvestigationService(capture_dirs=args.capture_dir) if args.capture_dir else KismetInvestigationService()
    source_filter = args.source_mac[0] if len(args.source_mac) == 1 else None
    data = service.query_recent_probes(
        start_time=args.start,
        end_time=args.end,
        lookback_minutes=None,
        limit=2000,
        subtype=args.subtype,
        randomized=True if args.mac_randomization else None,
        source_mac=source_filter,
    )
    requested_sources = {value.upper() for value in args.source_mac}
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for observation in data["observations"]:
        source = str(observation.get("source_mac") or "").upper()
        if requested_sources and source not in requested_sources:
            continue
        grouped[observation["capture_file"]].append(observation)

    capture_paths = {path.name: str(path) for path in service.find_kismet_database_files()}
    records: List[Dict[str, Any]] = []
    for index, (capture_file, observations) in enumerate(sorted(grouped.items()), start=1):
        macs = sorted({item["source_mac"] for item in observations if item.get("source_mac")})
        signatures = sorted({item["fingerprint_signature"] for item in observations})
        records.append({
            "capture_file": capture_paths.get(capture_file, capture_file),
            "physical_device_guid": args.physical_device_guid,
            "capture_session": f"{args.capture_session}-{index:02d}" if len(grouped) > 1 else args.capture_session,
            "expected_mac": args.expected_mac,
            "observed_macs": macs,
            "mac_randomization": bool(args.mac_randomization),
            "condition": args.condition,
            "sensor_id": args.sensor_id,
            "start_utc": args.start,
            "end_utc": args.end,
            "probe_count": len(observations),
            "probe_subtypes": sorted({item["frame_subtype"] for item in observations}),
            "candidate_fingerprint_signatures": signatures,
            "source": "kismet-probe-export-v1",
        })
    return records


def main() -> int:
    args = build_parser().parse_args()
    records = build_records(args)
    if not records:
        print(json.dumps({"status": "no_probes", "message": "No matching decoded probes found; manifest unchanged."}))
        return 2
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "records": records}, indent=2))
        return 0
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    print(json.dumps({"status": "ok", "manifest": str(args.manifest), "records_appended": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
