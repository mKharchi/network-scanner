"""Phase 0 tests: local schema safeguards and ML-derived Kismet contracts."""

from __future__ import annotations

import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.kismet_ml_foundation import (
    CheckpointStore,
    FEATURE_SCHEMA_VERSION,
    LABEL_SCHEMA_VERSION,
    KismetMLExtractor,
    LabelRecord,
    ModelArtifactMetadata,
    ModelCompatibilityError,
    ModelSchemaRegistry,
    ProcessingCheckpoint,
    StructuredObservation,
    WindowConfig,
    build_traffic_windows,
    group_aware_split,
    inspect_kismet_schema,
    is_randomized_mac,
    parse_80211_packet,
    resume_from_checkpoint,
    time_block_split,
)


CLIENT = "02:11:22:33:44:55"
AP = "AA:BB:CC:DD:EE:FF"
DESTINATION = "11:22:33:44:55:66"


def _mac(value: str) -> bytes:
    return bytes.fromhex(value.replace(":", ""))


def _radiotap() -> bytes:
    return struct.pack("<BBHI", 0, 0, 8, 0)


def _management_blob(subtype: int, *, source: str = CLIENT, destination: str = "FF:FF:FF:FF:FF:FF", bssid: str = AP, ies: bytes = b"") -> bytes:
    header = struct.pack("<H", subtype << 4) + b"\x00\x00" + _mac(destination) + _mac(source) + _mac(bssid) + struct.pack("<H", 7 << 4)
    fixed = {0: b"\x00" * 4, 1: b"\x00" * 6, 2: b"\x00" * 10, 4: b"", 5: b"\x00" * 12, 8: b"\x00" * 12}.get(subtype, b"")
    return _radiotap() + header + fixed + ies


def _data_blob(*, source: str = CLIENT, destination: str = DESTINATION, bssid: str = AP, sequence: int = 1, retry: bool = False) -> bytes:
    # To-DS means addr1=BSSID, addr2=client transmitter, addr3=final destination.
    fc = 0x0108 | (0x0800 if retry else 0)
    return _radiotap() + struct.pack("<H", fc) + b"\x00\x00" + _mac(bssid) + _mac(source) + _mac(destination) + struct.pack("<H", sequence << 4)


def _control_blob(subtype: int) -> bytes:
    return _radiotap() + struct.pack("<H", (subtype << 4) | 0x0004) + b"\x00" * 14


def _create_capture(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE packets (
          ts_sec INTEGER, ts_usec INTEGER, sourcemac TEXT, destmac TEXT, transmac TEXT,
          frequency REAL, signal INTEGER, packet_len INTEGER, dlt INTEGER, packet BLOB, hash TEXT
        )
    """)
    con.execute("CREATE TABLE devices (devmac TEXT, device BLOB)")
    con.executemany("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()


class PacketParsingTests(unittest.TestCase):
    def test_radiotap_header_length_and_management_ies_are_parsed(self):
        ies = b"".join((
            b"\x00\x03abc",  # SSID
            b"\x2d\x02\x11\x22",  # HT capabilities
            b"\xbf\x02\x33\x44",  # VHT capabilities
            b"\xff\x03\x23\x55\x66",  # extension 35 = HE capabilities
            b"\xdd\x04\x00\x50\xf2\x02",  # Microsoft WMM
        ))
        parsed = parse_80211_packet(_management_blob(4, ies=ies), dlt=127)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["frame_subtype"], "Probe Request")
        self.assertEqual(parsed["sequence_number"], 7)
        self.assertEqual(parsed["bssid"], AP)
        self.assertEqual(parsed["tags"], [0, 45, 191, 255, 221])
        self.assertEqual(parsed["vendor_ouis"], ["0050F2"])
        self.assertEqual(parsed["ht"], "1122")
        self.assertEqual(parsed["vht"], "3344")
        self.assertEqual(parsed["he"], "5566")
        self.assertTrue(parsed["wmm"])

    def test_frame_control_flags_are_little_endian_and_not_inferred(self):
        parsed = parse_80211_packet(_data_blob(retry=True), dlt=127)
        assert parsed is not None
        self.assertTrue(parsed["to_ds"])
        self.assertFalse(parsed["from_ds"])
        self.assertTrue(parsed["retry"])
        self.assertFalse(parsed["power_management"])
        self.assertEqual(parsed["bssid"], AP)
        self.assertTrue(is_randomized_mac(CLIENT))
        self.assertFalse(is_randomized_mac("A8:BB:CC:DD:EE:FF"))


class ExtractorTests(unittest.TestCase):
    def test_schema_is_verified_and_dual_path_outputs_do_not_contain_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.kismet"
            probe = _management_blob(4, ies=b"\xdd\x04\x00\x50\xf2\x02")
            rows = [
                (100, 0, CLIENT, "FF:FF:FF:FF:FF:FF", CLIENT, 2412000, -42, len(probe), 127, probe, "probe"),
                (100, 10, CLIENT, AP, CLIENT, 2412000, -43, 100, 127, _control_blob(11), "rts"),
                (100, 20, CLIENT, AP, CLIENT, 2412000, -44, 100, 127, _control_blob(12), "cts"),
                (100, 30, CLIENT, AP, CLIENT, 2412000, -45, 100, 127, _management_blob(12), "deauth"),
                (100, 40, CLIENT, AP, CLIENT, 2412000, -46, 100, 127, _management_blob(10), "disassoc"),
                (100, 50, CLIENT, AP, CLIENT, 2412000, -47, 100, 127, _management_blob(0), "assoc"),
                (100, 60, CLIENT, AP, CLIENT, 2412000, -48, 100, 127, _management_blob(11), "auth"),
                (100, 70, CLIENT, AP, CLIENT, 2412000, -49, 100, 127, _data_blob(sequence=1, retry=True), "data1"),
                (100, 80, CLIENT, AP, CLIENT, 2412000, -50, 100, 127, _data_blob(sequence=4), "data2"),
            ]
            _create_capture(path, rows)
            report = inspect_kismet_schema(path)
            self.assertTrue(report.has_required_packet_columns)
            self.assertFalse(report.bssid_is_packet_column)
            self.assertEqual(report.device_json_column, "device")
            self.assertTrue(report.device_json_decodable)

            observations = list(KismetMLExtractor([path]).iter_structured_observations())
            self.assertEqual(len(observations), len(rows))
            self.assertFalse(hasattr(observations[0], "packet"))
            fingerprints = list(KismetMLExtractor([path]).fingerprint_observations())
            self.assertEqual(len(fingerprints), 2)  # probe and association request
            self.assertTrue(fingerprints[0].is_randomized_mac)
            ticks = KismetMLExtractor([path]).threat_ticks()
            # Control frames do not carry a BSSID, so they remain in a distinct
            # unknown-BSSID tick rather than being falsely assigned to the AP.
            self.assertEqual(len(ticks), 2)
            self.assertEqual(sum(tick.rts_frame_count for tick in ticks), 1)
            self.assertEqual(sum(tick.cts_frame_count for tick in ticks), 1)
            self.assertEqual(sum(tick.deauth_frame_count for tick in ticks), 1)
            self.assertEqual(sum(tick.disassoc_frame_count for tick in ticks), 1)
            self.assertEqual(sum(tick.assoc_req_count for tick in ticks), 1)
            self.assertEqual(sum(tick.auth_req_count for tick in ticks), 1)
            self.assertEqual(sum(tick.retry_frame_count for tick in ticks), 1)
            self.assertEqual(sum(tick.sequence_gap_delta_sum for tick in ticks), 2)

    def test_optional_kismet_hash_column_is_not_a_schema_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "no-hash.kismet"
            con = sqlite3.connect(path)
            con.execute("""CREATE TABLE packets (
                ts_sec INTEGER, ts_usec INTEGER, sourcemac TEXT, destmac TEXT, transmac TEXT,
                frequency REAL, signal INTEGER, packet_len INTEGER, dlt INTEGER, packet BLOB
            )""")
            packet = _data_blob()
            con.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (1, 0, CLIENT, AP, CLIENT, 2412000, -50, len(packet), 127, packet))
            con.commit()
            con.close()
            observations = list(KismetMLExtractor([path]).iter_structured_observations())
            self.assertEqual(len(observations), 1)


class WindowAndLifecycleTests(unittest.TestCase):
    def _observation(self, timestamp_ms: int, length: int = 100) -> StructuredObservation:
        return StructuredObservation(
            observation_id=str(timestamp_ms), timestamp_epoch_ms=timestamp_ms, source_mac=CLIENT,
            destination_mac=DESTINATION, transmitter_mac=CLIENT, bssid=AP, frame_type="Data",
            frame_subtype="Data", frame_length=length, signal_dbm=-50, frequency_mhz=2412,
            sequence_number=None, to_ds=True, from_ds=False, retry=False, power_management=False,
        )

    def test_overlapping_windows_have_versioned_features_and_safe_direction(self):
        observations = [self._observation(timestamp) for timestamp in (0, 1, 2, 3, 5000, 10000)]
        windows = build_traffic_windows(observations, config=WindowConfig(length_seconds=10, hop_seconds=5), client_macs=[CLIENT])
        self.assertEqual([(item.window_start_ms, item.window_end_ms) for item in windows], [(0, 10000), (5000, 15000), (10000, 20000)])
        first = windows[0]
        self.assertEqual(first.uplink_frame_count, 5)
        self.assertEqual(first.downlink_frame_count, 0)
        self.assertIn(f"{FEATURE_SCHEMA_VERSION}.packet_rate", first.derived_features_json)
        self.assertEqual(first.derived_features_json[f"{FEATURE_SCHEMA_VERSION}.burst_rate"], 0.1)

    def test_dataset_splitting_registry_and_checkpoint_contracts(self):
        records = [{"group": "device-a/session-1", "day": "2026-01-01"}, {"group": "device-a/session-1", "day": "2026-01-01"}, {"group": "device-b/session-1", "day": "2026-01-02"}]
        split, metadata = group_aware_split(records, group_field="group")
        self.assertEqual(metadata["group_count"], 2)
        self.assertEqual(sum(len(rows) for rows in split.values()), 3)
        self.assertTrue(any(len(rows) == 2 for rows in split.values()))
        time_split, time_metadata = time_block_split(records, block_field="day")
        self.assertEqual(time_metadata["strategy"], "time_block")
        self.assertEqual(sum(len(rows) for rows in time_split.values()), 3)

        registry = ModelSchemaRegistry()
        artifact = ModelArtifactMetadata("activity-v1", FEATURE_SCHEMA_VERSION, "dataset-v1", ("a",), ("idle", "other"), 30, (2,))
        registry.register(artifact, expected_dataset_version="dataset-v1", expected_feature_columns=("a",), expected_label_schema=("idle", "other"), expected_window_seconds=30, expected_prediction_output_shape=(2,))
        with self.assertRaises(ModelCompatibilityError):
            registry.register(artifact, expected_dataset_version="dataset-v2", expected_feature_columns=("a",), expected_label_schema=("idle", "other"), expected_window_seconds=30, expected_prediction_output_shape=(2,))

        with tempfile.TemporaryDirectory() as directory:
            store = CheckpointStore(Path(directory) / "state.json")
            state = ProcessingCheckpoint(FEATURE_SCHEMA_VERSION, {"rotated.kismet": 123}, ("obs-1",))
            store.save(state)
            self.assertEqual(store.load(), state)

    def test_labels_preserve_probability_provenance_and_checkpoint_resume_deduplicates(self):
        label = LabelRecord("window-1", "activity", "manually_reviewed", probabilities={"streaming": 0.75, "browsing": 0.25})
        self.assertEqual(label.probabilities["streaming"], 0.75)
        self.assertEqual(label.label_schema_version, LABEL_SCHEMA_VERSION)
        with self.assertRaises(ValueError):
            LabelRecord("window-1", "activity", "ground_truth", probabilities={"unknown": 1.0})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.kismet"
            packet = _data_blob()
            _create_capture(path, [(1, 0, CLIENT, AP, CLIENT, 2412000, -50, len(packet), 127, packet, "one")])
            extractor = KismetMLExtractor([path])
            first, state = resume_from_checkpoint(extractor, ProcessingCheckpoint(FEATURE_SCHEMA_VERSION, {}))
            second, _ = resume_from_checkpoint(KismetMLExtractor([path]), state)
            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])


if __name__ == "__main__":
    unittest.main()
