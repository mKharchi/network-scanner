#!/usr/bin/env python3
"""Re-enrich a stored network scan JSON with vendor names from client/data/ieee.

Usage: python3 tools/re_enrich_scan.py /path/to/network_scan.json
"""

import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: re_enrich_scan.py /path/to/network_scan.json")
    sys.exit(2)

scan_path = Path(sys.argv[1])
if not scan_path.is_file():
    print(f"File not found: {scan_path}")
    sys.exit(2)

# Ensure client directory is importable
repo_root = Path(__file__).resolve().parents[1]
client_dir = repo_root / "client"
import sys

sys.path.insert(0, str(client_dir))

import oui

with open(scan_path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

# Backup: try same directory, fall back to repo-level backups folder
try:
    backup = scan_path.with_suffix(scan_path.suffix + ".bak")
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
except PermissionError:
    backups_dir = repo_root / "backups"
    backups_dir.mkdir(exist_ok=True)
    backup = backups_dir / (scan_path.name + ".bak")
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

database = oui.load_oui_database()
updated = 0
checked = 0
for device in data.get("devices", []):
    mac = device.get("mac_address")
    if not isinstance(mac, str):
        continue
    checked += 1
    if device.get("vendor"):
        # skip existing vendors
        continue
    vendor = oui.get_vendor(mac, database)
    if vendor:
        device["vendor"] = vendor
        updated += 1

try:
    with open(scan_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(f"Checked {checked} devices, updated {updated} vendors. Backup at {backup}")
except PermissionError:
    # Write updated file to backups directory instead
    updated_path = backups_dir / (scan_path.name + ".updated.json")
    with open(updated_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(
        f"Checked {checked} devices, updated {updated} vendors."
        f" Could not overwrite original; updated copy at {updated_path}. Backup at {backup}"
    )
