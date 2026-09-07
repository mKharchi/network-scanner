#!/usr/bin/env python3
"""Run the server-owned Kismet retention policy.

Dry-run is the default. Pass --apply only after the target-server retention
policy has been approved and the dry-run output has been reviewed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - server requirements provide this
    load_dotenv = None

if load_dotenv:
    load_dotenv(SERVER_DIR / ".env")

from server_components.kismet_retention import KismetRetentionManager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete eligible captures; omit for a dry-run",
    )
    args = parser.parse_args()

    manager = KismetRetentionManager(dry_run=not args.apply)
    summary = manager.prune_expired_captures(dry_run=not args.apply)
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
