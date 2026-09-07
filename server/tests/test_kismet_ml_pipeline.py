"""Operational tests for Phase 0 checkpointed shadow processing."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.kismet_ml_pipeline import KismetMLShadowProcessor
from server_components.kismet_ml_foundation import LabelRecord


def _data_packet() -> bytes:
    radiotap = b"\x00\x00\x08\x00\x00\x00\x00\x00"
    # Data / To-DS: addr1 BSSID, addr2 source, addr3 destination.
    return radiotap + b"\x08\x01\x00\x00" + bytes.fromhex(
        "AABBCCDDEEFF0211223344551122334455661000"
    )


def _create_capture(path: Path, *, timestamp: int = 100) -> None:
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE packets (
        ts_sec INTEGER, ts_usec INTEGER, sourcemac TEXT, destmac TEXT, transmac TEXT,
        frequency REAL, signal INTEGER, packet_len INTEGER, dlt INTEGER, packet BLOB, hash TEXT
    )""")
    packet = _data_packet()
    con.execute(
        "INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (timestamp, 0, "02:11:22:33:44:55", "AA:BB:CC:DD:EE:FF", "02:11:22:33:44:55", 2412000, -55, len(packet), 127, packet, f"hash-{timestamp}"),
    )
    con.commit()
    con.close()


class KismetMLShadowProcessorTests(unittest.TestCase):
    def test_run_persists_only_derived_records_and_restart_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture_dir, storage_dir = root / "captures", root / "ml"
            capture_dir.mkdir()
            _create_capture(capture_dir / "first.kismet")
            processor = KismetMLShadowProcessor([capture_dir], storage_dir=storage_dir)

            first = processor.run_once()
            self.assertEqual(first["status"], "ok")
            self.assertEqual(first["new_structured_observations"], 1)
            self.assertEqual(first["store_counts"]["structured_observations"], 1)
            self.assertTrue((storage_dir / "derived.sqlite").exists())
            self.assertTrue((storage_dir / "processing-checkpoint.json").exists())
            payloads = processor.store.load_all("structured_observations")
            self.assertNotIn("packet", payloads[0])

            restarted = KismetMLShadowProcessor([capture_dir], storage_dir=storage_dir).run_once()
            self.assertEqual(restarted["new_structured_observations"], 0)
            self.assertEqual(restarted["store_counts"]["structured_observations"], 1)

            # A rotated capture is processed without replaying the first one.
            _create_capture(capture_dir / "rotated.kismet", timestamp=200)
            rotated = KismetMLShadowProcessor([capture_dir], storage_dir=storage_dir).run_once()
            self.assertEqual(rotated["new_structured_observations"], 1)
            self.assertEqual(rotated["store_counts"]["structured_observations"], 2)

    def test_manifest_persists_local_schema_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture_dir, storage_dir = root / "captures", root / "ml"
            capture_dir.mkdir()
            _create_capture(capture_dir / "capture.kismet")
            processor = KismetMLShadowProcessor([capture_dir], storage_dir=storage_dir)
            processor.run_once()
            manifest = processor.export_dataset_manifest(
                dataset_version="activity-test-v1", source_dataset="local-kismet",
                capture_environment="test", label_source_type="ground_truth",
                split_strategy="group:client/session/day",
            )
            self.assertEqual(manifest.feature_schema_version, "kismet-ml-v1")
            self.assertEqual(manifest.capture_files, ("capture.kismet",))
            manifests = processor.store.load_all("dataset_manifests")
            self.assertEqual(manifests[0]["dataset_version"], "activity-test-v1")
            # Schema provenance may name the source payload column, but never
            # contains any raw payload value.
            self.assertEqual(manifests[0]["schema_reports"][0]["packet_payload_column"], "packet")

    def test_labeled_dataset_export_keeps_label_provenance_and_whole_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture_dir, storage_dir, dataset_dir = root / "captures", root / "ml", root / "dataset"
            capture_dir.mkdir()
            _create_capture(capture_dir / "capture.kismet")
            processor = KismetMLShadowProcessor([capture_dir], storage_dir=storage_dir)
            processor.run_once()
            window = processor.store.load_all("traffic_windows")[0]
            processor.store.persist_labels([
                LabelRecord(window["window_id"], "activity", "manually_reviewed", label="idle")
            ])
            result = processor.export_labeled_dataset(
                table="traffic_windows", dataset_version="activity-v1", output_dir=dataset_dir,
                source_dataset="local-kismet", capture_environment="test", label_family="activity",
                label_source_type="manually_reviewed", split_strategy="group:client/session/day",
            )
            self.assertEqual(result["record_count"], 1)
            exported = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in dataset_dir.glob("*.jsonl"))
            self.assertEqual(exported, 1)
            self.assertTrue((dataset_dir / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
