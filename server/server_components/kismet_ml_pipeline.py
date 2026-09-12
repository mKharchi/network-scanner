"""Operational Phase 0 shadow processing for server-owned Kismet captures.

The pipeline is intentionally pull-based: a systemd timer, cron job, or an
explicit CLI invocation calls :meth:`KismetMLShadowProcessor.run_once`.  It
does not start a second capture process and it never writes to a Kismet file.
Only normalized, derived ML records are stored in its own SQLite database.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .kismet_ml_foundation import (
    CheckpointStore,
    DatasetManifest,
    FEATURE_SCHEMA_VERSION,
    KismetMLExtractor,
    LabelRecord,
    ProcessingCheckpoint,
    StructuredObservation,
    build_traffic_windows,
    inspect_kismet_schema,
    make_dataset_manifest,
    group_aware_split,
    time_block_split,
    to_fingerprint_observation,
)

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_ML_STORAGE_DIR = SERVER_DIRECTORY / "storage" / "kismet_ml"


def get_ml_storage_dir() -> Path:
    """Return the derived-data directory, never a Kismet capture directory."""
    return Path(os.getenv("KISMET_ML_STORAGE_DIR", str(DEFAULT_ML_STORAGE_DIR))).resolve()


class KismetMLDerivedStore:
    """Idempotent storage of only Phase 0 derived values and metadata."""

    _TABLES = {
        "structured_observations": "observation_id",
        "fingerprint_observations": "observation_id",
        "threat_ticks": "threat_tick_id",
        "traffic_windows": "window_id",
        "labels": "label_id",
        "dataset_manifests": "dataset_version",
    }

    def __init__(self, storage_dir: Path | str | None = None):
        self.storage_dir = Path(storage_dir or get_ml_storage_dir())
        self.db_path = self.storage_dir / "derived.sqlite"

    def initialize(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        try:
            for table, primary_key in self._TABLES.items():
                con.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("
                    f"{primary_key} TEXT PRIMARY KEY, payload_json TEXT NOT NULL, persisted_at TEXT NOT NULL)"
                )
            con.commit()
        finally:
            con.close()

    def persist_many(self, table: str, records: Iterable[Any]) -> int:
        if table not in self._TABLES:
            raise ValueError(f"unsupported derived table '{table}'")
        primary_key = self._TABLES[table]
        serialized = []
        now = datetime.now(timezone.utc).isoformat()
        for record in records:
            payload = asdict(record) if not isinstance(record, Mapping) else dict(record)
            record_id = payload.get(primary_key)
            if not record_id:
                raise ValueError(f"{table} record has no {primary_key}")
            serialized.append((str(record_id), json.dumps(payload, sort_keys=True), now))
        if not serialized:
            return 0
        self.initialize()
        con = sqlite3.connect(self.db_path)
        try:
            con.executemany(
                f"INSERT INTO {table} ({primary_key}, payload_json, persisted_at) VALUES (?, ?, ?) "
                f"ON CONFLICT({primary_key}) DO UPDATE SET payload_json=excluded.payload_json, persisted_at=excluded.persisted_at",
                serialized,
            )
            con.commit()
        finally:
            con.close()
        return len(serialized)

    def load_all(self, table: str) -> List[Dict[str, Any]]:
        if table not in self._TABLES:
            raise ValueError(f"unsupported derived table '{table}'")
        if not self.db_path.exists():
            return []
        con = sqlite3.connect(self.db_path)
        try:
            rows = con.execute(f"SELECT payload_json FROM {table} ORDER BY persisted_at, rowid").fetchall()
        finally:
            con.close()
        return [json.loads(row[0]) for row in rows]

    def counts(self) -> Dict[str, int]:
        if not self.db_path.exists():
            return {table: 0 for table in self._TABLES}
        con = sqlite3.connect(self.db_path)
        try:
            return {table: int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) for table in self._TABLES}
        finally:
            con.close()

    def persist_labels(self, labels: Iterable[LabelRecord]) -> int:
        """Persist provenance-preserving labels separately from derived records."""
        return self.persist_many("labels", labels)


class KismetMLShadowProcessor:
    """Checkpointed dual-path materializer that tolerates capture rotation/restart."""

    def __init__(
        self, capture_dirs: Optional[Sequence[Path | str]] = None, *, storage_dir: Path | str | None = None,
        max_observations_per_run: Optional[int] = None,
    ):
        configured_dirs = os.getenv("KISMET_CAPTURE_DIRS")
        if capture_dirs is not None:
            self.capture_dirs = [Path(path) for path in capture_dirs]
        elif configured_dirs:
            self.capture_dirs = [Path(path.strip()) for path in configured_dirs.split(",") if path.strip()]
        else:
            self.capture_dirs = [Path(os.getenv("KISMET_CAPTURE_ROOT") or os.getenv("KISMET_CAPTURE_DIR") or "/home/adonis/kismet")]
        self.store = KismetMLDerivedStore(storage_dir)
        self.checkpoints = CheckpointStore(self.store.storage_dir / "processing-checkpoint.json")
        configured_limit = os.getenv("KISMET_ML_MAX_OBSERVATIONS_PER_RUN", "10000")
        self.max_observations_per_run = max_observations_per_run if max_observations_per_run is not None else int(configured_limit)

    def find_capture_files(self) -> List[Path]:
        files: List[Path] = []
        for directory in self.capture_dirs:
            try:
                if directory.is_file() and directory.suffix == ".kismet":
                    files.append(directory)
                elif directory.is_dir():
                    files.extend(path for path in directory.glob("*.kismet") if path.is_file())
            except OSError:
                continue
        return sorted(set(files), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

    def run_once(self) -> Dict[str, Any]:
        """Materialize a consistent shadow snapshot and atomically advance its cursor.

        Derived-record IDs are primary keys.  If a process dies after the store
        transaction but before its checkpoint update, the next run safely
        upserts the same records; no raw payloads are written or replayed.
        """
        capture_files = self.find_capture_files()
        extractor = KismetMLExtractor(capture_files, max_observations=self.max_observations_per_run)
        observations = list(extractor.iter_structured_observations())
        checkpoint = self.checkpoints.load()
        seen = set(checkpoint.emitted_observation_ids)
        new_observations = [item for item in observations if item.observation_id not in seen]
        fingerprints = [item for observation in observations if (item := to_fingerprint_observation(observation))]
        # Windows and rate ticks are re-materialized from the available source
        # captures so a new run can correct incomplete active-capture windows.
        windows = build_traffic_windows(observations)
        ticks = KismetMLExtractor(capture_files, max_observations=self.max_observations_per_run).threat_ticks()

        persisted = {
            "structured_observations": self.store.persist_many("structured_observations", observations),
            "fingerprint_observations": self.store.persist_many("fingerprint_observations", fingerprints),
            "threat_ticks": self.store.persist_many("threat_ticks", ticks),
            "traffic_windows": self.store.persist_many("traffic_windows", windows),
        }
        offsets = dict(checkpoint.capture_offsets)
        for observation in observations:
            offsets[observation.capture_file] = max(offsets.get(observation.capture_file, -1), observation.timestamp_epoch_ms)
        next_checkpoint = ProcessingCheckpoint(
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            capture_offsets=offsets,
            emitted_observation_ids=tuple(sorted(seen | {item.observation_id for item in new_observations})),
        )
        self.checkpoints.save(next_checkpoint)
        return {
            "status": "ok", "capture_files": [path.name for path in capture_files],
            "new_structured_observations": len(new_observations), "persisted": persisted,
            "store_counts": self.store.counts(), "rejected_captures": dict(extractor.rejected_captures),
        }

    def export_dataset_manifest(
        self, *, dataset_version: str, source_dataset: str, capture_environment: str,
        label_source_type: str, split_strategy: str,
    ) -> DatasetManifest:
        """Persist a provenance manifest for data materialized by this processor."""
        reports = []
        for capture_file in self.find_capture_files():
            try:
                reports.append(inspect_kismet_schema(capture_file))
            except (OSError, sqlite3.DatabaseError):
                continue
        manifest = make_dataset_manifest(
            dataset_version=dataset_version, source_dataset=source_dataset,
            capture_environment=capture_environment, label_source_type=label_source_type,
            split_strategy=split_strategy, schema_reports=reports,
        )
        self.store.persist_many("dataset_manifests", [manifest])
        return manifest

    def export_labeled_dataset(
        self, *, table: str, dataset_version: str, output_dir: Path | str,
        source_dataset: str, capture_environment: str, label_family: str,
        label_source_type: str, split_strategy: str,
    ) -> Dict[str, Any]:
        """Write split JSONL files plus a manifest for offline train/eval work.

        The export reads only derived records and separately persisted labels.
        Missing labels are excluded deliberately: silently treating them as a
        class would corrupt training data and provenance.
        """
        records = self.store.load_all(table)
        labels = {
            (item["target_id"], item["label_family"]): item
            for item in self.store.load_all("labels")
        }
        labeled: List[Dict[str, Any]] = []
        for record in records:
            record_id = record.get(self.store._TABLES[table])
            label = labels.get((record_id, label_family))
            if label:
                labeled.append({"record": record, "label": label})
        if label_family == "fingerprint":
            for item in labeled:
                item["split_group"] = f"{item['label']['physical_device_guid']}|{item['record'].get('capture_file', 'unknown')}"
            splits, split_metadata = group_aware_split(labeled, group_field="split_group")
        elif label_family in {"activity", "mining"}:
            for item in labeled:
                # Activity windows from one capture must remain together.  A
                # day-only split leaks adjacent windows and can put the same
                # PCAP into train and test, especially for public datasets.
                capture_session = item["record"].get("capture_session") or item["label"].get("capture_session")
                if not capture_session:
                    timestamp = int(item["record"].get("window_start_ms", 0)) / 1000.0
                    capture_session = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
                item["split_group"] = f"{capture_session}"
            splits, split_metadata = group_aware_split(labeled, group_field="split_group")
        elif label_family == "threat":
            for item in labeled:
                item["split_block"] = datetime.fromtimestamp(
                    int(item["record"].get("timestamp_sec", 0)), timezone.utc
                ).date().isoformat()
            splits, split_metadata = time_block_split(labeled, block_field="split_block")
        else:
            raise ValueError("unsupported label family")
        manifest = self.export_dataset_manifest(
            dataset_version=dataset_version, source_dataset=source_dataset,
            capture_environment=capture_environment, label_source_type=label_source_type,
            split_strategy=json.dumps({"requested": split_strategy, **split_metadata}, sort_keys=True),
        )
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for split_name, rows in splits.items():
            target = destination / f"{split_name}.jsonl"
            temporary = target.with_suffix(".jsonl.tmp")
            temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
            temporary.replace(target)
        manifest_path = destination / "manifest.json"
        temporary_manifest = manifest_path.with_suffix(".json.tmp")
        payload = {**manifest.to_dict(), "record_table": table, "record_count": len(labeled), "split_metadata": split_metadata}
        temporary_manifest.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary_manifest.replace(manifest_path)
        return {"dataset_dir": str(destination), "record_count": len(labeled), "split_metadata": split_metadata, "manifest": payload}
