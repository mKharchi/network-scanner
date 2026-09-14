"""CLI entrypoint for Kismet interval processing (Phase 3) and daily summaries (Phase 4).

Phase 3 commands:
  process-interval   Process a specific 10-minute UTC interval.
  process-completed  Auto-detect and process all closed intervals.
  retry-interval     Force-reprocess a failed or partial interval.
  show-status        Display interval manifests for a day or recent N intervals.
  finalize-day       Verify all intervals for a UTC day and write day summary.

Phase 4 commands:
  summarize-day      Aggregate per-window predictions into daily identity summaries.
  show-day-status    Show Phase 4 summary status for a UTC day.
  enforce-retention  Enforce 7-day rolling retention on daily summaries (dry-run by default).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running as: PYTHONPATH=server python3 server/kismet_interval_processor.py
sys.path.insert(0, str(Path(__file__).parent))

from server_components.kismet_interval_processing import (
    INTERVAL_DURATION_SECONDS,
    IntervalBounds,
    IntervalManifest,
    KismetIntervalProcessor,
)
from server_components.kismet_daily_summary import KismetDailySummarizer
from server_components.kismet_rotator import KismetLogRotator


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def _manifest_summary(m: IntervalManifest) -> Dict[str, Any]:
    return {
        "interval_id": m.interval_id,
        "status": m.status,
        "status_detail": m.status_detail,
        "prediction_count": m.prediction_count,
        "unique_devices_count": m.unique_devices_count,
        "window_count": m.window_count,
        "source_observation_count": m.source_observation_count,
        "safe_for_raw_cleanup": m.safe_for_raw_cleanup,
        "model_version": m.model_version,
        "completed_at_utc": m.completed_at_utc,
    }


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_process_interval(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Process one specific 10-minute UTC interval."""
    if args.interval:
        try:
            interval = IntervalBounds.from_interval_id(args.interval)
        except ValueError as exc:
            print(f"ERROR: invalid interval id: {exc}", file=sys.stderr)
            return 2
    elif args.time:
        try:
            interval = IntervalBounds.from_iso(args.time)
        except (ValueError, TypeError) as exc:
            print(f"ERROR: invalid time value: {exc}", file=sys.stderr)
            return 2
    else:
        print("ERROR: one of --interval or --time is required", file=sys.stderr)
        return 2

    print(f"Processing interval: {interval.interval_id}", file=sys.stderr)
    t0 = time.monotonic()
    manifest = processor.process_interval(interval, force=args.force)
    elapsed = time.monotonic() - t0
    result = _manifest_summary(manifest)
    result["elapsed_seconds"] = round(elapsed, 3)
    _print_json(result)
    return 0 if manifest.status == "COMPLETED" else 1


def cmd_process_completed(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Auto-detect and process all closed intervals not yet in COMPLETED state."""
    now_ms = int(time.time() * 1000)
    margin = getattr(args, "margin", 120)

    # Walk back through recent intervals looking for work
    results: List[Dict[str, Any]] = []
    look_back_intervals = getattr(args, "lookback", 144)  # default: 24 hours worth
    interval_ms = INTERVAL_DURATION_SECONDS * 1000
    snap_ms = (now_ms // interval_ms) * interval_ms

    to_process: List[IntervalBounds] = []
    for i in range(1, look_back_intervals + 1):
        candidate_end_ms = snap_ms - (i - 1) * interval_ms
        candidate_start_ms = candidate_end_ms - interval_ms
        # Ensure it's truly closed (end + margin < now)
        if candidate_end_ms + margin * 1000 > now_ms:
            continue
        try:
            candidate = IntervalBounds.from_epoch_ms(candidate_start_ms)
        except ValueError:
            continue
        existing = processor.get_manifest(candidate)
        if existing and existing.status == "COMPLETED":
            continue
        to_process.append(candidate)

    if not to_process:
        _print_json({"status": "nothing_to_process", "checked_intervals": look_back_intervals})
        return 0

    print(f"Found {len(to_process)} intervals to process", file=sys.stderr)
    for interval in reversed(to_process):  # oldest first
        print(f"  Processing {interval.interval_id}", file=sys.stderr)
        t0 = time.monotonic()
        manifest = processor.process_interval(interval)
        elapsed = time.monotonic() - t0
        result = _manifest_summary(manifest)
        result["elapsed_seconds"] = round(elapsed, 3)
        results.append(result)

    _print_json({
        "processed": len(results),
        "completed": sum(1 for r in results if r["status"] == "COMPLETED"),
        "failed": sum(1 for r in results if r["status"] != "COMPLETED"),
        "intervals": results,
    })
    return 0 if all(r["status"] == "COMPLETED" for r in results) else 1


def cmd_retry_interval(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Force-reprocess a failed or partial interval."""
    try:
        interval = IntervalBounds.from_interval_id(args.interval)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Retrying interval: {interval.interval_id}", file=sys.stderr)
    t0 = time.monotonic()
    manifest = processor.process_interval(interval, force=True)
    elapsed = time.monotonic() - t0
    result = _manifest_summary(manifest)
    result["elapsed_seconds"] = round(elapsed, 3)
    _print_json(result)
    return 0 if manifest.status == "COMPLETED" else 1


def cmd_show_status(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Display interval manifests, optionally filtered by date."""
    date: Optional[str] = getattr(args, "date", None)
    limit: int = getattr(args, "limit", 24)
    manifests = processor.list_intervals(date=date, limit=limit)
    if not manifests:
        _print_json({"status": "no_data", "date": date, "limit": limit})
        return 0

    rows = [_manifest_summary(m) for m in manifests]
    completed = sum(1 for m in manifests if m.status == "COMPLETED")
    safe = sum(1 for m in manifests if m.safe_for_raw_cleanup)
    _print_json({
        "total": len(rows),
        "completed": completed,
        "failed": len(rows) - completed,
        "safe_for_raw_cleanup": safe,
        "intervals": rows,
    })
    return 0


def cmd_finalize_day(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Aggregate all interval manifests for a UTC day into a finalization record."""
    date: str = args.date
    # Validate format
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: invalid date '{date}', expected YYYY-MM-DD", file=sys.stderr)
        return 2

    print(f"Finalizing day: {date}", file=sys.stderr)
    summary = processor.finalize_day(date)
    _print_json(summary)
    return 0 if summary.get("status") == "ready_for_daily_summary" else 1


# ---------------------------------------------------------------------------
# Phase 4 commands
# ---------------------------------------------------------------------------

def _make_summarizer(args: argparse.Namespace) -> KismetDailySummarizer:
    return KismetDailySummarizer(
        storage_dir=args.storage_dir,
        capture_dirs=args.capture_dirs,
    )


def cmd_summarize_day(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Aggregate per-window predictions into daily identity summaries."""
    date: str = args.date
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: invalid date '{date}', expected YYYY-MM-DD", file=sys.stderr)
        return 2

    dry_run: bool = args.dry_run
    delete_files: bool = args.delete_per_window_files and not dry_run

    summarizer = _make_summarizer(args)
    print(f"Summarizing day: {date} (dry_run={dry_run}, delete_files={delete_files})", file=sys.stderr)
    t0 = time.monotonic()
    record = summarizer.summarize_day(date, dry_run=dry_run, delete_per_window_files=delete_files)
    elapsed = time.monotonic() - t0

    result = record.to_dict()
    result["elapsed_seconds"] = round(elapsed, 3)
    _print_json(result)
    return 0 if record.status in ("completed", "empty") else 1


def cmd_show_day_status(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Show Phase 4 summary processing status for a UTC day."""
    date: str = args.date
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: invalid date '{date}', expected YYYY-MM-DD", file=sys.stderr)
        return 2

    summarizer = _make_summarizer(args)
    status = summarizer.show_day_status(date)
    _print_json(status)
    return 0


def cmd_enforce_retention(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Enforce 7-day rolling retention on daily summaries."""
    dry_run: bool = not args.execute
    summarizer = _make_summarizer(args)
    result = summarizer.enforce_retention(dry_run=dry_run)
    _print_json(result)
    if dry_run and result.get("dates_to_delete"):
        print(
            f"\nDRY RUN: {len(result['dates_to_delete'])} date(s) would be deleted. "
            "Re-run with --execute to apply.",
            file=sys.stderr,
        )
    return 0


# ---------------------------------------------------------------------------
# Automation & Rotation commands
# ---------------------------------------------------------------------------

def _make_rotator(args: argparse.Namespace) -> KismetLogRotator:
    return KismetLogRotator(
        storage_dir=args.storage_dir,
        capture_dirs=args.capture_dirs,
    )


def cmd_rotate_log(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Rotate the live Kismet logfile via REST API."""
    rotator = _make_rotator(args)
    res = rotator.rotate(log_class=getattr(args, "log_class", "kismet"))
    _print_json(res.to_dict())
    return 0 if res.success else 1


def cmd_cleanup_captures(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Safely delete closed raw .kismet captures that are verified and completed."""
    dry_run: bool = not args.execute
    rotator = _make_rotator(args)
    res = rotator.cleanup_verified_captures(dry_run=dry_run)
    _print_json(res.to_dict())
    if dry_run and res.deleted_captures:
        print(
            f"\nDRY RUN: {len(res.deleted_captures)} capture(s) ({res.freed_mb} MB) eligible for deletion. "
            "Re-run with --execute to delete.",
            file=sys.stderr,
        )
    return 0


def cmd_run_cycle(args: argparse.Namespace, processor: KismetIntervalProcessor) -> int:
    """Full 10-minute cycle: rotate log, process completed intervals, cleanup, and summarize."""
    print("=== Starting 10-Minute Kismet ML Cycle ===", file=sys.stderr)
    t0 = time.monotonic()
    rotator = _make_rotator(args)
    summarizer = _make_summarizer(args)
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.strftime("%Y-%m-%d")

    # 1. Rotate live log so the completed interval is cleanly closed
    print("1. Rotating live Kismet capture...", file=sys.stderr)
    rot_res = rotator.rotate(log_class=getattr(args, "log_class", "kismet"))
    if not rot_res.success:
        print(f"WARNING: Kismet rotation reported: {rot_res.error}", file=sys.stderr)

    # 2. Process all closed intervals
    print("2. Processing closed intervals...", file=sys.stderr)
    proc_args = argparse.Namespace(lookback=getattr(args, "lookback", 144), margin=30)
    proc_res_code = cmd_process_completed(proc_args, processor)

    # 3. Clean up verified closed raw captures
    cleanup_dry = not args.execute_cleanup
    print(f"3. Cleaning up verified raw captures (dry_run={cleanup_dry})...", file=sys.stderr)
    clean_res = rotator.cleanup_verified_captures(dry_run=cleanup_dry)

    # 4. Generate / update daily summary
    print(f"4. Updating daily summary for {today_utc}...", file=sys.stderr)
    day_record = summarizer.summarize_day(today_utc, dry_run=False, delete_per_window_files=False)

    total_time = round(time.monotonic() - t0, 3)
    cycle_summary = {
        "status": "success" if proc_res_code == 0 else "partial",
        "cycle_duration_seconds": total_time,
        "rotation": rot_res.to_dict(),
        "cleanup": clean_res.to_dict(),
        "daily_summary": {
            "date": day_record.date_utc,
            "status": day_record.status,
            "identities": day_record.identity_count,
            "total_windows": day_record.total_window_count,
            "active_duration_seconds": day_record.total_active_duration_seconds,
        },
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _print_json(cycle_summary)
    return 0 if proc_res_code == 0 else 1


# ---------------------------------------------------------------------------

# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Override Kismet ML storage root (default: server/storage/kismet_ml)",
    )
    parser.add_argument(
        "--capture-dir",
        dest="capture_dirs",
        action="append",
        default=None,
        help="Add a Kismet capture directory (repeatable; overrides KISMET_CAPTURE_DIRS env)",
    )
    parser.add_argument(
        "--model-version",
        default="activity-rf-v2",
        help="Model version to use for inference (default: activity-rf-v2)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # process-interval
    pi = subparsers.add_parser(
        "process-interval",
        help="Process one specific 10-minute UTC interval",
    )
    interval_group = pi.add_mutually_exclusive_group(required=True)
    interval_group.add_argument(
        "--interval",
        help="Interval ID in format 2026-09-12T09:00:00Z_2026-09-12T09:10:00Z",
    )
    interval_group.add_argument(
        "--time",
        help="Any ISO-8601 timestamp within the interval (e.g. 2026-09-12T09:05:00Z)",
    )
    pi.add_argument(
        "--force",
        action="store_true",
        help="Re-process even if a COMPLETED manifest already exists",
    )

    # process-completed
    pc = subparsers.add_parser(
        "process-completed",
        help="Auto-detect and process all closed intervals not yet COMPLETED",
    )
    pc.add_argument(
        "--lookback",
        type=int,
        default=144,
        help="Number of intervals to look back (default: 144 = 24 hours)",
    )
    pc.add_argument(
        "--margin",
        type=int,
        default=120,
        help="Seconds after interval close before processing (default: 120)",
    )

    # retry-interval
    ri = subparsers.add_parser(
        "retry-interval",
        help="Force-reprocess a failed or partial interval",
    )
    ri.add_argument(
        "--interval",
        required=True,
        help="Interval ID to retry",
    )

    # show-status
    ss = subparsers.add_parser(
        "show-status",
        help="Display interval manifests",
    )
    ss.add_argument(
        "--date",
        default=None,
        help="Filter by UTC day YYYY-MM-DD (default: all recent)",
    )
    ss.add_argument(
        "--limit",
        type=int,
        default=24,
        help="Maximum number of intervals to display (default: 24)",
    )

    # finalize-day
    fd = subparsers.add_parser(
        "finalize-day",
        help="Verify all intervals for a UTC day and write day_finalization.json",
    )
    fd.add_argument(
        "--date",
        required=True,
        help="UTC day to finalize, YYYY-MM-DD",
    )

    # summarize-day
    sd = subparsers.add_parser(
        "summarize-day",
        help="Aggregate per-window predictions into daily identity summaries",
    )
    sd.add_argument("--date", required=True, help="UTC day to summarize, YYYY-MM-DD")
    sd.add_argument("--dry-run", action="store_true", help="Compute but do not write to SQLite")
    sd.add_argument(
        "--delete-per-window-files",
        action="store_true",
        help="Delete prediction JSONL files after verified summary write",
    )

    # show-day-status
    sds = subparsers.add_parser(
        "show-day-status",
        help="Show Phase 4 daily summary status for a UTC day",
    )
    sds.add_argument("--date", required=True, help="UTC day YYYY-MM-DD")

    # enforce-retention
    er = subparsers.add_parser(
        "enforce-retention",
        help="Enforce 7-day rolling retention on daily summaries (dry-run by default)",
    )
    er.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete expired summaries (default is dry-run only)",
    )

    # rotate-log
    rl = subparsers.add_parser(
        "rotate-log",
        help="Rotate the live Kismet capture file via REST API",
    )
    rl.add_argument("--log-class", default="kismet", help="Kismet log class to rotate (default: kismet)")

    # cleanup-captures
    cc = subparsers.add_parser(
        "cleanup-captures",
        help="Delete closed raw .kismet captures whose intervals are verified and safe",
    )
    cc.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete files (default is dry-run only)",
    )

    # run-cycle
    rc = subparsers.add_parser(
        "run-cycle",
        help="Automated 10-minute cycle: rotate log, process completed intervals, cleanup, and summarize",
    )
    rc.add_argument("--log-class", default="kismet", help="Kismet log class to rotate (default: kismet)")
    rc.add_argument("--lookback", type=int, default=144, help="Interval lookback count (default: 144)")
    rc.add_argument(
        "--execute-cleanup",
        action="store_true",
        help="Actually delete verified raw captures (if omitted, cleanup is dry-run only)",
    )

    return parser



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    storage_dir = args.storage_dir
    model_version = args.model_version
    capture_dirs = args.capture_dirs  # list or None

    processor = KismetIntervalProcessor(
        capture_dirs=capture_dirs,
        storage_dir=storage_dir,
        model_version=model_version,
    )

    dispatch = {
        "process-interval": cmd_process_interval,
        "process-completed": cmd_process_completed,
        "retry-interval": cmd_retry_interval,
        "show-status": cmd_show_status,
        "finalize-day": cmd_finalize_day,
        "summarize-day": cmd_summarize_day,
        "show-day-status": cmd_show_day_status,
        "enforce-retention": cmd_enforce_retention,
        "rotate-log": cmd_rotate_log,
        "cleanup-captures": cmd_cleanup_captures,
        "run-cycle": cmd_run_cycle,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        print(f"ERROR: unknown command '{args.command}'", file=sys.stderr)
        return 2

    try:
        return handler(args, processor)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
