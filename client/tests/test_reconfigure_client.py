"""Unit tests for RECONFIGURE_CLIENT env patching and validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from client_lib import (
    _handle_reconfigure_client,
    _read_env_file,
    _validate_reconfigure_parameters,
    _write_env_file,
    consume_reconnect_request,
    request_client_reconnect,
)


class TestReconfigureEnvPatch(unittest.TestCase):
    def test_write_env_preserves_unrelated_keys_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# keep me\nSERVER_IP=10.0.0.1\nSERVER_PORT=5000\nOTHER=stay\n",
                encoding="utf-8",
            )
            kv, lines = _read_env_file(env_path)
            _write_env_file(env_path, kv, lines, {"SERVER_IP": "10.0.0.5"})
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("# keep me", text)
            self.assertIn("SERVER_IP=10.0.0.5", text)
            self.assertIn("SERVER_PORT=5000", text)
            self.assertIn("OTHER=stay", text)

    def test_validate_rejects_bad_ip_and_port(self):
        self.assertIsNotNone(_validate_reconfigure_parameters({"SERVER_IP": "not an ip!!"}))
        self.assertIsNotNone(_validate_reconfigure_parameters({"SERVER_PORT": "99999"}))
        params = {"SERVER_IP": "10.0.0.5", "SERVER_PORT": "5000"}
        self.assertIsNone(_validate_reconfigure_parameters(params))
        self.assertEqual(params["SERVER_IP"], "10.0.0.5")

    def test_reconnect_event_latches_once(self):
        consume_reconnect_request()
        request_client_reconnect()
        self.assertTrue(consume_reconnect_request())
        self.assertFalse(consume_reconnect_request())

    def test_handler_soft_reconnect_for_server_ip(self):
        consume_reconnect_request()
        with tempfile.TemporaryDirectory() as tmp:
            client_root = Path(tmp)
            app_dir = client_root / "app"
            app_dir.mkdir()
            config_dir = client_root / "config"
            config_dir.mkdir()
            env_path = config_dir / ".env"
            env_path.write_text("SERVER_IP=192.168.1.1\nFOO=bar\n", encoding="utf-8")

            fake_file = app_dir / "client_lib.py"
            fake_file.write_text("# test\n", encoding="utf-8")

            with mock.patch("client_lib.__file__", str(fake_file)):
                # Avoid spawning a real restart path; SERVER_IP-only is soft.
                result = _handle_reconfigure_client(
                    {"args": {"SERVER_IP": "10.0.0.9", "command_id": "abc"}}
                )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["reconnect_mode"], "soft")
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("SERVER_IP=10.0.0.9", text)
            self.assertIn("FOO=bar", text)
            self.assertTrue(consume_reconnect_request())

    def test_handler_rejects_unknown_keys(self):
        result = _handle_reconfigure_client({"args": {"EVIL": "1"}})
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("Rejected", result["error"])


if __name__ == "__main__":
    unittest.main()
