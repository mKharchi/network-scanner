"""Bounded orchestration for legacy active scans and passive collection jobs.

This module deliberately keeps only job metadata in memory. The observations
themselves continue through the existing network-device storage path as each
client report arrives.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
import uuid
from datetime import datetime, timezone


LOGGER = logging.getLogger(__name__)


def _job_log(message, *args):
    """Write scan-job progress to both configured logs and the server console."""
    LOGGER.info(message, *args)
    print("[GLOBAL NETWORK SCAN] " + (message % args if args else message), flush=True)


def _collection_log(message, *args, level="info"):
    """Write passive collection progress to configured logs and the console."""
    getattr(LOGGER, level)(message, *args)
    print(
        "[GLOBAL NEIGHBOURHOOD COLLECTION] "
        + (message % args if args else message),
        flush=True,
    )


def _positive_int(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        LOGGER.warning("Invalid %s; using %s.", name, default)
        return default


def _positive_float(name, default):
    try:
        return max(0.1, float(os.getenv(name, str(default))))
    except ValueError:
        LOGGER.warning("Invalid %s; using %s.", name, default)
        return default


def _utc_now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


class GlobalNetworkScanManager:
    """Run at most one global scan and bound concurrent client ARP scans."""

    def __init__(self):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._active_scan_id = None
        self._sessions = {}

    def start(self, clients):
        """Create a scan from an online-client snapshot and return its state."""
        with self._lock:
            if self._active_scan_id:
                return self._summary_locked(self._sessions[self._active_scan_id]), False

            scan_id = f"global-{_utc_now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            now = _utc_now()
            targets = {}
            for client in clients:
                client_id = client.get("client_id")
                client_mac = client.get("mac")
                if not client_id or not client_mac:
                    continue
                targets[client_mac.upper().replace("-", ":")] = {
                    "client_id": client_id,
                    "client_mac": client_mac.upper().replace("-", ":"),
                    "status": "PENDING",
                    "dispatched_at": None,
                    "started_at": None,
                    "completed_at": None,
                    "error": None,
                }

            session = {
                "id": scan_id,
                "status": "PENDING",
                "started_at": now,
                "finished_at": None,
                "updated_at": now,
                "error": None,
                "targets": targets,
                "device_macs": set(),
                "max_concurrent_clients": _positive_int(
                    "GLOBAL_NETWORK_SCAN_MAX_CONCURRENT_CLIENTS", 5
                ),
                "command_timeout": _positive_float(
                    "GLOBAL_NETWORK_SCAN_COMMAND_TIMEOUT", 10
                ),
                "scan_timeout": _positive_float(
                    "GLOBAL_NETWORK_SCAN_TIMEOUT", 120
                ),
            }
            self._sessions[scan_id] = session
            self._active_scan_id = scan_id
            _job_log(
                "Global network scan %s started: eligible_clients=%d concurrency=%d.",
                scan_id,
                len(targets),
                session["max_concurrent_clients"],
            )
            threading.Thread(
                target=self._run_session,
                args=(scan_id,),
                daemon=True,
                name=f"global-network-scan-{scan_id[-8:]}",
            ).start()
            return self._summary_locked(session), True

    def get(self, scan_id):
        with self._lock:
            session = self._sessions.get(scan_id)
            return self._summary_locked(session) if session else None

    def active(self):
        with self._lock:
            if not self._active_scan_id:
                return None
            return self._summary_locked(self._sessions[self._active_scan_id])

    def record_report(self, scan_id, reporter_mac, neighbours, *, failed=False, error=None):
        """Record a correlated report after it has been persisted.

        Repeated reports are idempotent: they can contribute device identities
        but never advance the same client twice or reopen its slot.
        """
        if not isinstance(scan_id, str) or not isinstance(reporter_mac, str):
            return False
        normalized_mac = reporter_mac.upper().replace("-", ":")
        with self._lock:
            session = self._sessions.get(scan_id)
            target = session and session["targets"].get(normalized_mac)
            if not target:
                return False
            if target["status"] in {"COMPLETED", "FAILED", "SKIPPED_ALREADY_RUNNING"}:
                return True
            if target["status"] not in {"DISPATCHING", "RUNNING"}:
                return False

            now = _utc_now()
            if failed:
                target["status"] = "FAILED"
                target["error"] = (error or "Client reported scan failure.")[:255]
                LOGGER.warning(
                    "Global scan %s client %s failed: %s",
                    scan_id,
                    target["client_id"],
                    target["error"],
                )
                print(
                    f"[GLOBAL NETWORK SCAN] Global scan {scan_id} client "
                    f"{target['client_id']} reported failure: {target['error']}",
                    flush=True,
                )
            else:
                target["status"] = "COMPLETED"
                for neighbour in neighbours:
                    mac = neighbour.get("mac_address") if isinstance(neighbour, dict) else None
                    if isinstance(mac, str):
                        session["device_macs"].add(mac.upper().replace("-", ":"))
                _job_log(
                    "Global scan %s client %s completed; devices_found=%d.",
                    scan_id,
                    target["client_id"],
                    len(session["device_macs"]),
                )
            target["completed_at"] = now
            session["updated_at"] = now
            self._wake.set()
            return True

    def is_duplicate_report(self, scan_id, reporter_mac):
        """Return whether a correlated client report was already completed.

        This is checked before observation persistence so a client retry does
        not append duplicate immutable observation rows.
        """
        if not isinstance(scan_id, str) or not isinstance(reporter_mac, str):
            return False
        normalized_mac = reporter_mac.upper().replace("-", ":")
        with self._lock:
            session = self._sessions.get(scan_id)
            target = session and session["targets"].get(normalized_mac)
            return bool(
                target
                and target["status"]
                in {"COMPLETED", "FAILED", "SKIPPED_ALREADY_RUNNING"}
            )

    def _run_session(self, scan_id):
        """Dispatch a new client only when a reserved scan slot is available."""
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._session_value(scan_id, "max_concurrent_clients")
        ) as executor:
            futures = {}
            while True:
                with self._lock:
                    session = self._sessions.get(scan_id)
                    if not session:
                        return
                    self._expire_running_locked(session)
                    for future in [future for future in futures if future.done()]:
                        target_mac = futures.pop(future)
                        self._handle_dispatch_result_locked(session, target_mac, future)

                    occupied = sum(
                        target["status"] in {"DISPATCHING", "RUNNING"}
                        for target in session["targets"].values()
                    )
                    capacity = session["max_concurrent_clients"] - occupied
                    for target_mac, target in session["targets"].items():
                        if capacity <= 0:
                            break
                        if target["status"] != "PENDING":
                            continue
                        target["status"] = "DISPATCHING"
                        target["dispatched_at"] = _utc_now()
                        session["status"] = "RUNNING"
                        session["updated_at"] = target["dispatched_at"]
                        futures[executor.submit(self._dispatch, scan_id, target.copy(), session["command_timeout"])] = target_mac
                        capacity -= 1
                        _job_log(
                            "Global scan %s dispatching client %s.", scan_id, target["client_id"]
                        )

                    if self._finalize_if_done_locked(session):
                        return

                self._wake.wait(0.25)
                self._wake.clear()

    def _session_value(self, scan_id, key):
        with self._lock:
            return self._sessions[scan_id][key]

    @staticmethod
    def _dispatch(scan_id, target, command_timeout):
        from server_components import server_lib

        try:
            return server_lib.execute_client_command(
                target["client_id"],
                "SCAN_NETWORK",
                args={"global_scan_id": scan_id},
                timeout=command_timeout,
                process_network_scan=False,
            )
        except Exception as error:  # Defensive boundary around a worker thread.
            return {"status": "error", "message": str(error)}

    def _handle_dispatch_result_locked(self, session, target_mac, future):
        target = session["targets"][target_mac]
        if target["status"] != "DISPATCHING":
            return
        try:
            result = future.result()
        except Exception as error:
            result = {"status": "error", "message": str(error)}

        data = result.get("data") if isinstance(result, dict) else None
        response_status = data.get("status") if isinstance(data, dict) else None
        active_scan_id = data.get("global_scan_id") if isinstance(data, dict) else None
        now = _utc_now()
        if result.get("status") == "ok" and response_status == "started":
            target["status"] = "RUNNING"
            target["started_at"] = now
            _job_log(
                "Global scan %s client %s acknowledged start.",
                session["id"],
                target["client_id"],
            )
        elif result.get("status") == "ok" and response_status == "already_running":
            if active_scan_id == session["id"]:
                target["status"] = "RUNNING"
                target["started_at"] = now
            else:
                target["status"] = "SKIPPED_ALREADY_RUNNING"
                target["completed_at"] = now
                target["error"] = "Client already has an unrelated active scan."
                _job_log(
                    "Global scan %s client %s skipped: another active scan is running.",
                    session["id"],
                    target["client_id"],
                )
        else:
            target["status"] = "FAILED"
            target["completed_at"] = now
            target["error"] = (result.get("message") if isinstance(result, dict) else None) or "Command acknowledgement failed."
            LOGGER.warning(
                "Global scan %s client %s dispatch failed: %s",
                session["id"], target["client_id"], target["error"],
            )
            print(
                f"[GLOBAL NETWORK SCAN] Global scan {session['id']} client "
                f"{target['client_id']} dispatch failed: {target['error']}",
                flush=True,
            )
        session["updated_at"] = now

    def _expire_running_locked(self, session):
        now = _utc_now()
        for target in session["targets"].values():
            if target["status"] != "RUNNING" or not target["started_at"]:
                continue
            if (now - target["started_at"]).total_seconds() < session["scan_timeout"]:
                continue
            target["status"] = "FAILED"
            target["completed_at"] = now
            target["error"] = f"Scan report timed out after {session['scan_timeout']}s."
            session["updated_at"] = now
            LOGGER.warning("Global scan %s client %s timed out.", session["id"], target["client_id"])
            print(
                f"[GLOBAL NETWORK SCAN] Global scan {session['id']} client "
                f"{target['client_id']} timed out waiting for its report.",
                flush=True,
            )

    def _finalize_if_done_locked(self, session):
        if any(target["status"] in {"PENDING", "DISPATCHING", "RUNNING"} for target in session["targets"].values()):
            return False
        statuses = [target["status"] for target in session["targets"].values()]
        session["status"] = "COMPLETED" if statuses and all(status == "COMPLETED" for status in statuses) else "PARTIAL"
        if not statuses:
            session["status"] = "COMPLETED"
        session["finished_at"] = _utc_now()
        session["updated_at"] = session["finished_at"]
        if self._active_scan_id == session["id"]:
            self._active_scan_id = None
        _job_log(
            "Global network scan %s finished: status=%s total=%d completed=%d failed=%d skipped=%d devices=%d.",
            session["id"], session["status"], len(statuses), statuses.count("COMPLETED"),
            statuses.count("FAILED"), statuses.count("SKIPPED_ALREADY_RUNNING"), len(session["device_macs"]),
        )
        return True

    def _summary_locked(self, session):
        if not session:
            return None
        targets = list(session["targets"].values())
        statuses = [target["status"] for target in targets]
        return {
            "id": session["id"],
            "status": session["status"].lower(),
            "total_clients": len(targets),
            "clients_dispatched": sum(status != "PENDING" for status in statuses),
            "started": sum(status in {"RUNNING", "COMPLETED"} for status in statuses),
            "completed": statuses.count("COMPLETED"),
            "failed": statuses.count("FAILED"),
            "skipped": statuses.count("SKIPPED_ALREADY_RUNNING"),
            "running": sum(status in {"DISPATCHING", "RUNNING"} for status in statuses),
            "pending": statuses.count("PENDING"),
            "devices_found": len(session["device_macs"]),
            "started_at": _timestamp(session["started_at"]),
            "updated_at": _timestamp(session["updated_at"]),
            "finished_at": _timestamp(session["finished_at"]),
            "max_concurrent_clients": session["max_concurrent_clients"],
        }


class GlobalNeighbourhoodCollectionManager:
    """Collect stored neighbourhoods one concurrent bucket at a time.

    Unlike :class:`GlobalNetworkScanManager`, this class never initiates ARP
    scans.  Its workers use the direct ``GET_NETWORK_NEIGHBOURHOOD`` request
    operation, whose client report is received, persisted, and merged through
    the normal server path before the request is reported as completed.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._active_collection_id = None
        self._sessions = {}

    def start(self, clients):
        """Start a collection over a stable snapshot of online clients.

        Only one passive collection runs at once. Targets are deduplicated by
        normalized reporter MAC and sorted so bucket membership is stable.
        """
        with self._lock:
            if self._active_collection_id:
                return self._summary_locked(
                    self._sessions[self._active_collection_id]
                ), False

            collection_id = (
                f"neighbourhood-{_utc_now().strftime('%Y%m%d%H%M%S')}-"
                f"{uuid.uuid4().hex[:8]}"
            )
            now = _utc_now()
            bucket_size = _positive_int(
                "GLOBAL_NEIGHBOURHOOD_COLLECTION_BUCKET_SIZE", 5
            )
            direct_request_timeout = _positive_float(
                "NETWORK_NEIGHBOURHOOD_REQUEST_TIMEOUT", 12
            )
            request_timeout = _positive_float(
                "GLOBAL_NEIGHBOURHOOD_COLLECTION_CLIENT_TIMEOUT",
                direct_request_timeout,
            )
            targets_by_mac = {}
            for client in clients:
                client_id = client.get("client_id") if isinstance(client, dict) else None
                client_mac = client.get("mac") if isinstance(client, dict) else None
                if not client_id or not client_mac:
                    continue
                normalized_mac = client_mac.upper().replace("-", ":")
                targets_by_mac.setdefault(
                    normalized_mac,
                    {
                        "client_id": client_id,
                        "client_mac": normalized_mac,
                        "status": "PENDING",
                        "bucket": None,
                        "dispatched_at": None,
                        "completed_at": None,
                        "observations_sent": 0,
                        "error": None,
                    },
                )

            targets = [
                targets_by_mac[mac]
                for mac in sorted(targets_by_mac)
            ]
            for index, target in enumerate(targets):
                target["bucket"] = index // bucket_size + 1

            session = {
                "id": collection_id,
                "status": "PENDING",
                "started_at": now,
                "finished_at": None,
                "updated_at": now,
                "targets": targets,
                "bucket_size": bucket_size,
                "request_timeout": request_timeout,
                "buckets_total": (len(targets) + bucket_size - 1) // bucket_size,
                "buckets_completed": 0,
                "current_bucket": None,
                "devices_discovered": 0,
                "merge_error": None,
            }
            self._sessions[collection_id] = session
            self._active_collection_id = collection_id
            _collection_log(
                "Collection %s started: eligible_clients=%d bucket_size=%d request_timeout=%.1fs.",
                collection_id,
                len(targets),
                bucket_size,
                request_timeout,
            )
            threading.Thread(
                target=self._run_session,
                args=(collection_id,),
                daemon=True,
                name=f"global-neighbourhood-{collection_id[-8:]}",
            ).start()
            return self._summary_locked(session), True

    def get(self, collection_id):
        with self._lock:
            session = self._sessions.get(collection_id)
            return self._summary_locked(session) if session else None

    def active(self):
        with self._lock:
            if not self._active_collection_id:
                return None
            return self._summary_locked(self._sessions[self._active_collection_id])

    def _run_session(self, collection_id):
        with self._lock:
            session = self._sessions.get(collection_id)
            if not session:
                return
            session["status"] = "RUNNING"
            session["updated_at"] = _utc_now()
            buckets = [
                session["targets"][start:start + session["bucket_size"]]
                for start in range(0, len(session["targets"]), session["bucket_size"])
            ]

        for bucket_number, bucket in enumerate(buckets, start=1):
            with self._lock:
                session = self._sessions.get(collection_id)
                if not session:
                    return
                session["current_bucket"] = bucket_number
                session["updated_at"] = _utc_now()
                for target in bucket:
                    target["status"] = "DISPATCHING"
                    target["dispatched_at"] = _utc_now()
                _collection_log(
                    "Collection %s bucket %d/%d started: clients=%d.",
                    collection_id,
                    bucket_number,
                    session["buckets_total"],
                    len(bucket),
                )

            # Exiting this executor waits for every request in this bucket.
            # The following bucket cannot be dispatched until all of them have
            # produced a terminal outcome.
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(bucket)
            ) as executor:
                futures = {
                    executor.submit(
                        self._request_target,
                        target.copy(),
                        session["request_timeout"],
                    ): target
                    for target in bucket
                }
                for future in concurrent.futures.as_completed(futures):
                    target = futures[future]
                    try:
                        result = future.result()
                    except Exception as error:  # Defensive worker boundary.
                        result = {
                            "status": "client_error",
                            "message": str(error),
                        }
                    with self._lock:
                        session = self._sessions.get(collection_id)
                        if session:
                            self._record_target_result_locked(session, target, result)

            with self._lock:
                session = self._sessions.get(collection_id)
                if not session:
                    return
                session["buckets_completed"] += 1
                session["updated_at"] = _utc_now()
                _collection_log(
                    "Collection %s bucket %d/%d completed.",
                    collection_id,
                    bucket_number,
                    session["buckets_total"],
                )

        with self._lock:
            session = self._sessions.get(collection_id)
            should_merge = bool(
                session
                and any(target["status"] == "COMPLETED" for target in session["targets"])
            )

        devices_discovered = 0
        merge_error = None
        if should_merge:
            try:
                devices_discovered = len(
                    self._merge_collection_results(collection_id)
                )
            except Exception as error:
                merge_error = str(error)[:255]
                LOGGER.warning(
                    "Global neighbourhood collection %s final merge failed: %s",
                    collection_id,
                    merge_error,
                )

        with self._lock:
            session = self._sessions.get(collection_id)
            if session:
                session["devices_discovered"] = devices_discovered
                session["merge_error"] = merge_error
                self._finalize_locked(session)

    @staticmethod
    def _merge_collection_results(collection_id):
        """Return the final MAC-deduplicated snapshot for a collection job."""
        from server_components import server_lib

        devices, _ = server_lib.merge_and_broadcast_neighbourhood(
            context_overrides={
                "scan_type": "GLOBAL_NEIGHBOURHOOD_COLLECTION",
                "collection_id": collection_id,
            }
        )
        return devices

    @staticmethod
    def _request_target(target, request_timeout):
        from server_components import server_lib

        try:
            return server_lib.request_client_network_neighbourhood(
                target["client_id"], timeout=request_timeout
            )
        except Exception as error:  # Defensive boundary around a worker thread.
            return {"status": "client_error", "message": str(error)}

    def _record_target_result_locked(self, session, target, result):
        now = _utc_now()
        result = result if isinstance(result, dict) else {}
        result_status = result.get("status")
        target["completed_at"] = now
        target["observations_sent"] = result.get("observations_sent", 0)
        if result_status == "completed":
            target["status"] = "COMPLETED"
        elif result_status == "client_timeout":
            target["status"] = "TIMED_OUT"
        elif result_status == "client_unavailable":
            target["status"] = "UNAVAILABLE"
        else:
            target["status"] = "FAILED"
        if target["status"] != "COMPLETED":
            target["error"] = str(
                result.get("message", "Client neighbourhood request failed.")
            )[:255]
        session["updated_at"] = now
        if target["status"] == "COMPLETED":
            _collection_log(
                "Collection %s client %s responded: observations=%d.",
                session["id"],
                target["client_id"],
                target["observations_sent"],
            )
        else:
            level = "warning" if target["status"] == "TIMED_OUT" else "info"
            _collection_log(
                "Collection %s client %s %s: %s",
                session["id"],
                target["client_id"],
                target["status"].lower(),
                target["error"],
                level=level,
            )

    def _finalize_locked(self, session):
        statuses = [target["status"] for target in session["targets"]]
        session["status"] = (
            "COMPLETED" if all(status == "COMPLETED" for status in statuses) else "PARTIAL"
        )
        session["finished_at"] = _utc_now()
        session["updated_at"] = session["finished_at"]
        session["current_bucket"] = None
        if self._active_collection_id == session["id"]:
            self._active_collection_id = None
        _collection_log(
            "Collection %s completed: status=%s requested=%d succeeded=%d failed=%d timed_out=%d devices=%d buckets=%d.",
            session["id"],
            session["status"],
            len(statuses),
            statuses.count("COMPLETED"),
            statuses.count("FAILED") + statuses.count("UNAVAILABLE"),
            statuses.count("TIMED_OUT"),
            session["devices_discovered"],
            session["buckets_completed"],
        )

    def _summary_locked(self, session):
        if not session:
            return None
        statuses = [target["status"] for target in session["targets"]]
        failed = statuses.count("FAILED") + statuses.count("UNAVAILABLE")
        return {
            "id": session["id"],
            "status": session["status"].lower(),
            "total_clients": len(statuses),
            "completed": statuses.count("COMPLETED"),
            "failed": failed,
            "timed_out": statuses.count("TIMED_OUT"),
            "unavailable": statuses.count("UNAVAILABLE"),
            "running": statuses.count("DISPATCHING"),
            "pending": statuses.count("PENDING"),
            "bucket_size": session["bucket_size"],
            "request_timeout": session["request_timeout"],
            "buckets_total": session["buckets_total"],
            "buckets_completed": session["buckets_completed"],
            "current_bucket": session["current_bucket"],
            "devices_discovered": session["devices_discovered"],
            "merge_error": session["merge_error"],
            "clients_requested": len(statuses),
            "clients_succeeded": statuses.count("COMPLETED"),
            "clients_failed": failed,
            "clients_timed_out": statuses.count("TIMED_OUT"),
            "started_at": _timestamp(session["started_at"]),
            "updated_at": _timestamp(session["updated_at"]),
            "finished_at": _timestamp(session["finished_at"]),
        }


global_network_scan_manager = GlobalNetworkScanManager()
global_neighbourhood_collection_manager = GlobalNeighbourhoodCollectionManager()
