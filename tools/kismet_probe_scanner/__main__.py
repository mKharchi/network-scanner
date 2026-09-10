"""CLI entry-point for the standalone Kismet probe scanner.

Usage
-----
    # From the repository root (venv active):
    python -m tools.kismet_probe_scanner
    python -m tools.kismet_probe_scanner --capture-dir /home/adonis/kismet
    python -m tools.kismet_probe_scanner --capture-file /path/to/file.kismet

Exit codes
----------
    0  — success (probe found or explicitly no-result)
    1  — operational error (bad arguments, unreadable capture directory)

The JSON record is written to stdout; status messages go to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure the repository server/ directory is importable when this module is
# run directly as ``python -m tools.kismet_probe_scanner`` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_DIR = _REPO_ROOT / "server"
for _extra in (_REPO_ROOT, _SERVER_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from tools.kismet_probe_scanner.scanner import scan_latest_probe  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.kismet_probe_scanner",
        description=(
            "Scan Kismet .kismet captures and emit the single latest Probe Request "
            "as a metadata-only JSON record.  Never emits raw bytes or plaintext SSIDs."
        ),
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--capture-dir",
        metavar="DIR",
        help=(
            "Directory containing .kismet files.  May be supplied multiple times.  "
            "Defaults to KISMET_CAPTURE_ROOT / KISMET_CAPTURE_DIRS environment values."
        ),
        action="append",
        dest="capture_dirs",
    )
    group.add_argument(
        "--capture-file",
        metavar="FILE",
        help="Scan a single .kismet file instead of discovering all captures.",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (equivalent to piping through python -m json.tool).",
    )
    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    capture_dirs = None
    capture_file = None

    if args.capture_file:
        capture_file = Path(args.capture_file)
        if not capture_file.exists():
            print(f"error: capture file not found: {capture_file}", file=sys.stderr)
            return 1
        if not capture_file.suffix == ".kismet":
            print(f"error: expected a .kismet file, got: {capture_file.name}", file=sys.stderr)
            return 1

    elif args.capture_dirs:
        capture_dirs = []
        for raw in args.capture_dirs:
            path = Path(raw)
            if not path.is_dir():
                print(f"error: capture directory not found: {path}", file=sys.stderr)
                return 1
            capture_dirs.append(path)

    result = scan_latest_probe(capture_dirs=capture_dirs, capture_file=capture_file)
    output = result.to_dict()

    indent = 2 if args.pretty else None
    json.dump(output, sys.stdout, indent=indent, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()

    # Emit a brief summary to stderr so piped consumers see clean JSON only
    found = result.status.found
    n_files = result.status.capture_files_scanned
    n_rows = result.status.total_rows_scanned
    if found:
        ts = result.latest_probe.timestamp if result.latest_probe else "?"
        print(
            f"[kismet-probe-scanner] latest probe found: {ts} "
            f"(scanned {n_files} file(s), {n_rows:,} rows)",
            file=sys.stderr,
        )
    else:
        reason = result.status.no_result_reason or "no probe found"
        print(
            f"[kismet-probe-scanner] {reason} "
            f"(scanned {n_files} file(s), {n_rows:,} rows)",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
