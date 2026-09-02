"""Unit tests for scope_filter module (v2 Phase 3)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from scope_filter import ScopeFilter, load_scope_config, save_scope_config


class TestScopeFilter(unittest.TestCase):
    def test_fail_open_when_no_scope_assigned(self):
        sf = ScopeFilter([])
        self.assertFalse(sf.is_configured)
        self.assertTrue(sf.keep("8.8.8.8", "1.1.1.1"))
        self.assertTrue(sf.keep(None, None))

    def test_keeps_when_src_in_scope(self):
        sf = ScopeFilter(["172.16.2.0/26"])
        self.assertTrue(sf.is_configured)
        self.assertTrue(sf.keep("172.16.2.10", "8.8.8.8"))

    def test_keeps_when_dst_in_scope(self):
        sf = ScopeFilter(["172.16.2.0/26"])
        self.assertTrue(sf.keep("8.8.8.8", "172.16.2.10"))

    def test_drops_when_neither_in_scope(self):
        sf = ScopeFilter(["172.16.2.0/26"])
        self.assertFalse(sf.keep("8.8.8.8", "1.1.1.1"))

    def test_drops_when_ips_missing(self):
        sf = ScopeFilter(["172.16.2.0/26"])
        self.assertFalse(sf.keep(None, None))

    def test_invalid_cidr_ignored(self):
        sf = ScopeFilter(["not-a-cidr", "172.16.2.0/26"])
        self.assertTrue(sf.keep("172.16.2.10", "8.8.8.8"))

    def test_set_scope_hot_applies_and_can_restore_fail_open(self):
        sf = ScopeFilter([])
        self.assertTrue(sf.keep("8.8.8.8", "1.1.1.1"))
        sf.set_scope(["172.16.2.0/26"])
        self.assertTrue(sf.is_configured)
        self.assertFalse(sf.keep("8.8.8.8", "1.1.1.1"))
        self.assertTrue(sf.keep("8.8.8.8", "172.16.2.9"))
        sf.set_scope([])
        self.assertFalse(sf.is_configured)
        self.assertTrue(sf.keep("8.8.8.8", "1.1.1.1"))

    def test_multiple_cidrs(self):
        sf = ScopeFilter(["172.16.2.0/26", "10.0.0.0/8"])
        self.assertTrue(sf.keep("10.1.2.3", "8.8.8.8"))
        self.assertFalse(sf.keep("192.168.1.1", "8.8.8.8"))

    def test_keep_observation_dict(self):
        sf = ScopeFilter(["172.16.2.0/26"])
        self.assertTrue(sf.keep_observation({"src_ip": "172.16.2.5", "dst_ip": "8.8.8.8"}))
        self.assertFalse(sf.keep_observation({"src_ip": "8.8.8.8", "dst_ip": "1.1.1.1"}))
        self.assertFalse(sf.keep_observation({}))  # no IPs present -> dropped when scope is configured
        self.assertTrue(sf.keep_observation(None))  # non-dict input -> safe default (keep)


class TestScopeConfigPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_scope_config_")
        self.config_path = Path(self.temp_dir) / "scope_config.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load_round_trip(self):
        save_scope_config(["172.16.2.0/26", "10.0.0.0/8"], path=self.config_path)
        loaded = load_scope_config(self.config_path)
        self.assertEqual(loaded, ["172.16.2.0/26", "10.0.0.0/8"])

    def test_load_missing_file_returns_empty(self):
        missing_path = Path(self.temp_dir) / "does_not_exist.json"
        self.assertEqual(load_scope_config(missing_path), [])

    def test_from_env_or_file_uses_env_override(self):
        with patch.dict("os.environ", {"NETWORK_OBSERVATION_SCOPE": "172.16.2.0/26, 10.0.0.0/8"}):
            sf = ScopeFilter.from_env_or_file(config_path=self.config_path)
            self.assertTrue(sf.is_configured)
            self.assertTrue(sf.keep("10.1.1.1", "8.8.8.8"))

    def test_from_env_or_file_falls_back_to_config_file(self):
        save_scope_config(["192.168.1.0/24"], path=self.config_path)
        with patch.dict("os.environ", {}, clear=True):
            sf = ScopeFilter.from_env_or_file(config_path=self.config_path)
            self.assertTrue(sf.keep("192.168.1.5", "8.8.8.8"))


if __name__ == "__main__":
    unittest.main()
