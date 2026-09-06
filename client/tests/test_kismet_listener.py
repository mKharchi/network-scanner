"""Unit tests for Phase 5 Client Kismet Listener."""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

CLIENT_APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(CLIENT_APP_DIR))

from kismet_listener import (
    KISMET_CONNECTED,
    KISMET_LISTENER_STARTING,
    KISMET_OBSERVATION_STORED,
    KismetListener,
)


class KismetListenerUnitTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_kismet_client_"))
        self.kismet_dir = self.test_dir / "kismet"
        self.kismet_dir.mkdir()
        self.db_path = self.kismet_dir / "Kismet-20260906-capture.kismet"
        self._init_sqlite_kismet_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _init_sqlite_kismet_db(self, path: Path):
        con = sqlite3.connect(path)
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE packets (
            ts_sec INT, ts_usec INT, sourcemac TEXT, destmac TEXT, transmac TEXT, signal INT, frequency REAL, packet_len INT, datasource TEXT, hash INT
        )
        """)
        con.commit()
        con.close()

    def _insert_packet(self, ts_sec, src, dst, bssid, signal=-65, hash_val=1001):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            "INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts_sec, 0, src, dst, bssid, signal, 5220000.0, 128, "wlan0mon", hash_val),
        )
        con.commit()
        con.close()

    def test_initial_health_report(self):
        listener = KismetListener(kismet_db_dir=self.kismet_dir)
        health = listener.get_health()
        self.assertEqual(health["listener"], "kismet")
        self.assertEqual(health["status"], "initialized")
        self.assertFalse(health["connected"])
        self.assertEqual(health["events_received"], 0)
        self.assertEqual(health["observations_stored"], 0)
        self.assertIsNone(health["last_error"])

    def test_find_latest_database(self):
        listener = KismetListener(kismet_db_dir=self.kismet_dir)
        found = listener.find_latest_database()
        self.assertEqual(found, self.db_path)

    def test_poll_new_observations_parses_records(self):
        now_epoch = int(time.time())
        self._insert_packet(now_epoch, "AA:BB:CC:DD:EE:01", "FF:FF:FF:FF:FF:FF", "AA:BB:CC:DD:EE:01", -60, hash_val=2001)
        self._insert_packet(now_epoch + 1, "AA:BB:CC:DD:EE:01", "11:22:33:44:55:66", "AA:BB:CC:DD:EE:01", -55, hash_val=2002)

        received_callback = []
        listener = KismetListener(
            kismet_db_dir=self.kismet_dir,
            observation_callback=lambda obs: received_callback.append(obs),
        )
        listener._last_processed_timestamp = now_epoch - 10

        obs = listener.poll_new_observations(self.db_path)
        self.assertEqual(len(obs), 2)
        self.assertEqual(obs[0]["source_mac"], "AA:BB:CC:DD:EE:01")
        self.assertEqual(obs[0]["signal_dbm"], -60)
        self.assertEqual(len(received_callback), 2)

        health = listener.get_health()
        self.assertEqual(health["events_received"], 2)
        self.assertEqual(health["observations_stored"], 2)
        self.assertIsNotNone(health["last_event"])

    def test_duplicate_packets_deduplicated_by_hash(self):
        now_epoch = int(time.time())
        self._insert_packet(now_epoch, "AA:BB:CC:DD:EE:01", "FF:FF:FF:FF:FF:FF", "AA:BB:CC:DD:EE:01", -60, hash_val=3001)

        listener = KismetListener(kismet_db_dir=self.kismet_dir)
        listener._last_processed_timestamp = now_epoch - 10

        obs1 = listener.poll_new_observations(self.db_path)
        self.assertEqual(len(obs1), 1)

        # Polling again with the same packet in DB does not duplicate
        obs2 = listener.poll_new_observations(self.db_path)
        self.assertEqual(len(obs2), 0)

    def test_start_and_stop_lifecycle(self):
        listener = KismetListener(
            kismet_db_dir=self.kismet_dir,
            poll_interval_seconds=0.1,
        )
        listener.start()
        self.assertTrue(listener._thread.is_alive())
        time.sleep(0.2)
        health = listener.get_health()
        self.assertTrue(health["connected"])
        self.assertEqual(health["status"], "active")

        listener.stop()
        self.assertIsNone(listener._thread)
        health_after = listener.get_health()
        self.assertEqual(health_after["status"], "stopped")
        self.assertFalse(health_after["connected"])

    def test_idempotent_start_does_not_create_duplicate_thread(self):
        listener = KismetListener(
            kismet_db_dir=self.kismet_dir,
            poll_interval_seconds=0.1,
        )
        listener.start()
        thread_1 = listener._thread
        self.assertIsNotNone(thread_1)

        # Second start() call should be a no-op and keep existing thread
        listener.start()
        self.assertIs(listener._thread, thread_1)
        listener.stop()

    def test_idempotent_stop_can_be_called_multiple_times(self):
        listener = KismetListener(
            kismet_db_dir=self.kismet_dir,
            poll_interval_seconds=0.1,
        )
        listener.start()
        listener.stop()
        # Second stop() call must not raise any error
        listener.stop()
        self.assertEqual(listener.get_health()["status"], "stopped")

    def test_lifecycle_states_and_health(self):
        from kismet_listener import STATE_NOT_STARTED, STATE_RUNNING, STATE_STOPPED
        listener = KismetListener(kismet_db_dir=self.kismet_dir, poll_interval_seconds=0.05)
        self.assertEqual(listener.state, STATE_NOT_STARTED)
        self.assertEqual(listener.get_health()["state"], STATE_NOT_STARTED)

        listener.start()
        time.sleep(0.15)
        self.assertEqual(listener.state, STATE_RUNNING)
        self.assertEqual(listener.get_health()["state"], STATE_RUNNING)

        listener.stop()
        self.assertEqual(listener.state, STATE_STOPPED)
        self.assertEqual(listener.get_health()["state"], STATE_STOPPED)

    def test_reconnection_when_database_appears(self):
        empty_dir = self.test_dir / "empty_kismet"
        empty_dir.mkdir()
        listener = KismetListener(kismet_db_dir=empty_dir, poll_interval_seconds=0.05)
        listener.start()
        time.sleep(0.1)
        self.assertFalse(listener.get_health()["connected"])

        # Now create database in directory
        new_db = empty_dir / "capture.kismet"
        self._init_sqlite_kismet_db(new_db)
        time.sleep(0.15)
        self.assertTrue(listener.get_health()["connected"])
        listener.stop()


if __name__ == "__main__":
    unittest.main()
