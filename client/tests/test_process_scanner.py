"""Unit tests for the forbidden-process log scanner."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

dotenv_module = types.ModuleType("dotenv")
dotenv_module.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_module)

from process_scanner import scan_for_forbidden_processes  # noqa: E402
import client as client_module  # noqa: E402


class ForbiddenProcessScannerTests(unittest.TestCase):
    @patch("process_scanner.psutil.process_iter")
    def test_log_and_running_process_matching_is_normalized(self, mock_process_iter):
        log_data = {
            "activity": [
                {
                    "time": "2026-08-23 10:15:00",
                    "type": "Browser Search",
                    "detail": "User searched for Discord",
                },
                {
                    "time": "2026-08-23 10:20:00",
                    "type": "Browser Search",
                    "detail": "User searched for mydiscordhelper",
                },
            ]
        }
        forbidden_processes = [
            {
                "process_name": "discord",
                "severity": "HIGH",
                "description": "Unauthorized chat client",
            }
        ]

        false_positive = MagicMock()
        false_positive.info = {
            "pid": 101,
            "name": "mydiscordhelper.exe",
            "exe": r"C:\\Apps\\mydiscordhelper.exe",
        }
        exact_match = MagicMock()
        exact_match.info = {
            "pid": 202,
            "name": "Discord.exe",
            "exe": r"C:\\Apps\\Discord.exe",
        }
        mock_process_iter.return_value = [false_positive, exact_match]

        alerts, _ = scan_for_forbidden_processes(log_data, forbidden_processes, set())

        self.assertGreaterEqual(len(alerts), 2)
        self.assertTrue(any(alert.get("log_source") == "Browser Search" for alert in alerts))
        self.assertTrue(any(alert.get("log_source") == "process_list" for alert in alerts))
        self.assertFalse(
            any(
                "mydiscordhelper" in str(alert.get("description", "")).lower()
                or "mydiscordhelper" in str(alert.get("detected_process_name", "")).lower()
                for alert in alerts
            )
        )

    def test_background_scanner_uses_startup_then_ten_minute_periodic_scan(self):
        stop_event = MagicMock()
        stop_event.is_set.return_value = False
        stop_event.wait.side_effect = [False, True]

        with patch.object(
            client_module, "run_forbidden_activity_scan", return_value=[]
        ) as run_scan:
            client_module.background_scanner(object(), stop_event=stop_event)

        self.assertEqual(run_scan.call_count, 2)
        self.assertEqual(run_scan.call_args_list[0].args[1], "1d")
        self.assertEqual(run_scan.call_args_list[1].args[1], "1h")

    @patch("process_scanner.psutil.process_iter")
    def test_browser_activity_terminates_active_browser(self, mock_process_iter):
        browser = MagicMock()
        browser.info = {
            "pid": 303,
            "name": "chrome.exe",
            "exe": r"C:\\Chrome\\chrome.exe",
            "cmdline": ["chrome.exe"],
        }
        mock_process_iter.return_value = [browser]

        alerts, _ = scan_for_forbidden_processes(
            {
                "activity": [{
                    "time": "2026-08-23 10:15:00",
                    "type": "Browser History",
                    "detail": "Discord",
                }]
            },
            [{"process_name": "discord", "severity": "HIGH"}],
            set(),
            enforce=True,
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["action"], "BROWSER_TERMINATED")
        self.assertEqual(alerts[0]["enforcement"][0]["pid"], 303)
        browser.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
