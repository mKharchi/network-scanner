"""Tests for client-side action framework helpers."""

import sys
import unittest
from pathlib import Path


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from action_framework import ActionManager, ActionType, normalize_action_name  # noqa: E402


class ClientActionFrameworkTests(unittest.TestCase):
    def test_request_screenshot_alias_maps_to_canonical_action(self):
        self.assertEqual(normalize_action_name("REQUEST_SCREENSHOT"), ActionType.SCREENSHOT.value)

    def test_action_manager_deduplicates_by_action_id(self):
        manager = ActionManager()
        calls = []

        def handler(message, **_context):
            calls.append(message["action_id"])
            return {"status": "ok", "calls": len(calls)}

        manager.register(ActionType.PING.value, handler)

        first = manager.dispatch({"command": "PING", "action_id": "action-1"})
        second = manager.dispatch({"command": "PING", "action_id": "action-1"})

        self.assertEqual(first, {"status": "ok", "calls": 1})
        self.assertEqual(second, {"status": "ok", "calls": 1})
        self.assertEqual(calls, ["action-1"])


if __name__ == "__main__":
    unittest.main()
