import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

from updater import updater


def make_package(app_files, *, version="2.0.0", minimum_updater_version="1.0.0", extra_entries=None):
    manifest_hashes = {
        name: hashlib.sha256(content).hexdigest() for name, content in app_files.items()
    }
    manifest = {
        "version": version,
        "package_type": "client-update",
        "minimum_updater_version": minimum_updater_version,
        "file_hashes": manifest_hashes,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, content in app_files.items():
            archive.writestr(f"app/{name}", content)
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="client-updater-"))
        self.app = self.root / "app"
        self.app.mkdir(parents=True)
        (self.app / "version.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
        (self.app / "old.txt").write_text("remove me", encoding="utf-8")
        self.package = self.root / "client-update-2.0.0.zip"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write_package(self, payload):
        self.package.write_bytes(payload)

    def test_success_replaces_app_as_desired_state(self):
        self.write_package(make_package({"version.json": b'{"version":"2.0.0"}', "new.txt": b"new"}))
        started = []
        result = updater.apply_update(
            self.package,
            client_root=self.root,
            stop_client=lambda: None,
            start_client=lambda: started.append(True),
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertFalse((self.app / "old.txt").exists())
        self.assertEqual((self.app / "new.txt").read_text(), "new")
        self.assertTrue(started)
        self.assertTrue((self.root / "storage" / "updates" / "history" / "1.0.0").is_dir())

    def test_zip_slip_is_rejected_without_touching_app(self):
        self.write_package(make_package({"version.json": b'{"version":"2.0.0"}'}, extra_entries={"../../escape.txt": b"bad"}))
        result = updater.apply_update(self.package, client_root=self.root, stop_client=lambda: None)
        self.assertEqual(result["status"], "UPDATE_FAILED")
        self.assertEqual(result["reason"], "INVALID_PACKAGE")
        self.assertEqual((self.app / "old.txt").read_text(), "remove me")

    def test_dependency_failure_rolls_back(self):
        self.write_package(make_package({"version.json": b'{"version":"2.0.0"}', "requirements.txt": b"broken-package==999"}))
        venv_python = self.root / "venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_bytes(b"fake python")
        pip_commands = []

        def fail_runner(command, **kwargs):
            pip_commands.append(command)
            raise subprocess.CalledProcessError(1, command)

        result = updater.apply_update(
            self.package,
            client_root=self.root,
            stop_client=lambda: None,
            runner=fail_runner,
        )
        self.assertEqual(result["status"], "UPDATE_FAILED")
        self.assertEqual(result["reason"], "DEPENDENCY_INSTALL_FAILED")
        self.assertTrue(result["rolled_back"])
        self.assertTrue((self.app / "old.txt").exists())
        self.assertEqual(json.loads((self.app / "version.json").read_text())["version"], "1.0.0")
        self.assertEqual(len(pip_commands), 1)
        self.assertIn("pip", pip_commands[0])

    def test_missing_python_with_requirements_rolls_back(self):
        self.write_package(make_package({"version.json": b'{"version":"2.0.0"}', "requirements.txt": b"broken-package==999"}))
        with mock.patch.object(updater.sys, "executable", str(self.root / "missing-python.exe")):
            result = updater.apply_update(
                self.package,
                client_root=self.root,
                stop_client=lambda: None,
            )
        self.assertEqual(result["status"], "UPDATE_FAILED")
        self.assertEqual(result["reason"], "DEPENDENCY_INSTALL_FAILED")
        self.assertTrue(result["rolled_back"])
        self.assertEqual(json.loads((self.app / "version.json").read_text())["version"], "1.0.0")

    def test_start_failure_rolls_back(self):
        self.write_package(make_package({"version.json": b'{"version":"2.0.0"}'}))
        start_calls = []
        def fail_start():
            start_calls.append(True)
            if len(start_calls) == 1:
                raise RuntimeError("cannot start")
        result = updater.apply_update(
            self.package,
            client_root=self.root,
            stop_client=lambda: None,
            start_client=fail_start,
        )
        self.assertEqual(result["reason"], "APPLICATION_START_FAILED")
        self.assertTrue(result["rolled_back"])
        self.assertTrue((self.app / "old.txt").exists())


if __name__ == "__main__":
    unittest.main()
