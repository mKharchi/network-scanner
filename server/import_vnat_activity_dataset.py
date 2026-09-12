#!/usr/bin/env python3
"""Materialize the VNAT PCAP release into metadata-only activity windows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from server_components.activity_dataset import (
    DATASET_VERSION,
    PARSER_VERSION,
    capture_inventory,
    discover_vnat_captures,
    iter_capture_windows,
    label_record,
    window_record,
)
from server_components.kismet_ml_foundation import WindowConfig
from server_components.device_activity import ACTIVITY_FEATURE_SCHEMA_VERSION


def _write_jsonl(path: Path, rows) -> int:
    temporary = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    temporary.replace(path)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("server/storage/ml-2-datasets/VNAT_release_1"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("server/storage/kismet_ml/activity_datasets/vnat-v1"),
    )
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument("--hop-seconds", type=int, default=30)
    parser.add_argument("--limit-captures", type=int, default=0, help="Process only the first N captures (0 = all)")
    args = parser.parse_args()
    if args.window_seconds <= 0 or args.hop_seconds <= 0:
        parser.error("window and hop seconds must be positive")

    captures = discover_vnat_captures(args.dataset_root)
    if args.limit_captures > 0:
        captures = captures[:args.limit_captures]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    inventory = []
    rejected = []
    windows_path = args.output_dir / "windows.jsonl"
    labels_path = args.output_dir / "labels.jsonl"
    windows_tmp = windows_path.with_suffix(".jsonl.tmp")
    labels_tmp = labels_path.with_suffix(".jsonl.tmp")
    window_count = 0
    label_counts = Counter()
    capture_window_counts = Counter()
    config = WindowConfig(length_seconds=args.window_seconds, hop_seconds=args.hop_seconds)

    with windows_tmp.open("w", encoding="utf-8") as windows_handle, labels_tmp.open("w", encoding="utf-8") as labels_handle:
        for capture in captures:
            report = capture_inventory(capture, args.dataset_root)
            inventory.append(asdict(report))
            if report.status != "ok":
                rejected.append({**asdict(report), "reason": report.reason or "capture rejected"})
                continue
            if not report.activity_label:
                rejected.append({**asdict(report), "reason": "unsupported activity label"})
                continue
            try:
                windows, _client_id, _stats = iter_capture_windows(
                    capture, session_id=report.capture_session, config=config,
                )
                capture_count = 0
                for window in windows:
                    windows_handle.write(json.dumps(window_record(
                        window,
                        capture_session=report.capture_session,
                        label=report.activity_label,
                        vpn=report.vpn,
                        source_file=report.relative_path,
                    ), sort_keys=True, separators=(",", ":")) + "\n")
                    labels_handle.write(json.dumps(label_record(
                        window,
                        capture_session=report.capture_session,
                        label=report.activity_label,
                        vpn=report.vpn,
                        source_file=report.relative_path,
                    ), sort_keys=True, separators=(",", ":")) + "\n")
                    capture_count += 1
                    window_count += 1
                    label_counts[report.activity_label] += 1
                capture_window_counts[report.relative_path] = capture_count
            except (OSError, ValueError) as error:
                rejected.append({**asdict(report), "reason": str(error)})
    windows_tmp.replace(windows_path)
    labels_tmp.replace(labels_path)

    for item in inventory:
        item["window_count"] = capture_window_counts.get(item["relative_path"], 0)
    (args.output_dir / "inventory.json").write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    (args.output_dir / "rejected-captures.json").write_text(
        json.dumps(rejected, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    manifest = {
        "dataset_version": DATASET_VERSION,
        "source_dataset": "VNAT_release_1",
        "parser_version": PARSER_VERSION,
        "feature_schema_version": ACTIVITY_FEATURE_SCHEMA_VERSION,
        "window_seconds": args.window_seconds,
        "hop_seconds": args.hop_seconds,
        "split_strategy": "capture_session_hash_60_20_20",
        "label_mapping": {
            "netflix": "streaming", "youtube": "streaming", "vimeo": "streaming",
            "scp": "file_transfer", "sftp": "file_transfer", "rsync": "file_transfer",
            "skype-chat": "chat", "voip": "voip", "ssh": "other", "rdp": "other",
        },
        "capture_count": len(captures),
        "capture_hashes": {
            item["relative_path"]: item["sha256"] for item in inventory
        },
        "accepted_capture_count": sum(1 for item in inventory if item["status"] == "ok" and item.get("activity_label")),
        "rejected_capture_count": len(rejected),
        "rejected_truncated_capture_count": sum(
            1 for item in rejected if "truncated" in str(item.get("reason", "")).lower()
        ),
        "window_count": window_count,
        "label_counts": dict(sorted(label_counts.items())),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outputs": ["manifest.json", "windows.jsonl", "labels.jsonl", "inventory.json", "rejected-captures.json"],
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"status": "ok", **manifest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
