"""Tests for machine-global Kismet path defaults."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from server_components.kismet_paths import (
    DEFAULT_KISMET_CAPTURE_ROOT,
    DEFAULT_KISMET_CONF_DIR,
    get_capture_dirs,
    get_conf_dir,
)


class TestKismetPaths(unittest.TestCase):
    def test_defaults_are_fhs_global(self):
        self.assertEqual(DEFAULT_KISMET_CAPTURE_ROOT, Path("/var/lib/kismet/captures"))
        self.assertEqual(DEFAULT_KISMET_CONF_DIR, Path("/etc/kismet"))

    def test_env_override(self):
        with mock.patch.dict(
            "os.environ",
            {"KISMET_CAPTURE_ROOT": "/data/kismet", "KISMET_CAPTURE_DIRS": ""},
            clear=False,
        ):
            dirs = get_capture_dirs()
            self.assertEqual(dirs, [Path("/data/kismet")])

    def test_empty_env_falls_back_to_default(self):
        with mock.patch.dict(
            "os.environ",
            {"KISMET_CAPTURE_ROOT": "", "KISMET_CAPTURE_DIR": "", "KISMET_CAPTURE_DIRS": ""},
            clear=False,
        ):
            self.assertEqual(get_capture_dirs()[0], DEFAULT_KISMET_CAPTURE_ROOT)
            self.assertEqual(get_conf_dir(), DEFAULT_KISMET_CONF_DIR)


if __name__ == "__main__":
    unittest.main()
