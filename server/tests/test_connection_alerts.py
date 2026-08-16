"""Unit tests for Step 2 registration and working-hours alerts.

Run from the repository root:
    python3 server/tests/test_connection_alerts.py

The tests use mock connections only; they never connect to or alter MySQL.
"""

import datetime
import sys
import types
import unittest
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))


# Let the unit tests run even in a minimal Python environment where the
# project's MySQL dependency has not been installed. The database function is
# replaced with mock connections in every test below.
try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components import server_lib


class WorkingHoursCursor:
    def __init__(self, connection):
        self.connection = connection
        self.last_query = ""

    def execute(self, query, params=None):
        self.last_query = query

    def fetchone(self):
        if "TIME_TO_SEC" in self.last_query:
            return self.connection.schedule
        return (self.connection.has_enabled_schedule,)

    def close(self):
        pass


class WorkingHoursConnection:
    def __init__(self, schedule, has_enabled_schedule=True):
        self.schedule = schedule
        self.has_enabled_schedule = has_enabled_schedule

    def cursor(self):
        return WorkingHoursCursor(self)

    def is_connected(self):
        return False


class AlertCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=None):
        self.connection.executed.append((query, params))

    def fetchone(self):
        return (42,)

    def close(self):
        pass


class AlertConnection:
    def __init__(self):
        self.executed = []
        self.committed = False

    def cursor(self):
        return AlertCursor(self)

    def commit(self):
        self.committed = True

    def is_connected(self):
        return False


class ConnectionAlertTests(unittest.TestCase):
    def setUp(self):
        self.original_get_connection = server_lib.get_connection
        self.original_get_status = server_lib.get_working_hours_status

    def tearDown(self):
        server_lib.get_connection = self.original_get_connection
        server_lib.get_working_hours_status = self.original_get_status

    def working_hours_status(self, checked_at, schedule, has_enabled_schedule=True):
        server_lib.get_connection = lambda: WorkingHoursConnection(
            schedule, has_enabled_schedule
        )
        return server_lib.get_working_hours_status(checked_at)

    def test_opening_time_is_inside_working_hours(self):
        # Saturday is weekday 5; 09:30 is the inclusive opening boundary.
        checked_at = datetime.datetime(2026, 8, 15, 9, 30)
        self.assertEqual(
            self.working_hours_status(checked_at, (34200, 64800)),
            server_lib.WORKING_HOURS_WITHIN,
        )

    def test_closing_time_is_outside_working_hours(self):
        # 18:00 is the exclusive closing boundary.
        checked_at = datetime.datetime(2026, 8, 15, 18, 0)
        self.assertEqual(
            self.working_hours_status(checked_at, (34200, 64800)),
            server_lib.WORKING_HOURS_OUTSIDE,
        )

    def test_friday_without_a_schedule_is_outside_working_hours(self):
        # Friday has no row, while the Saturday–Thursday schedule is enabled.
        checked_at = datetime.datetime(2026, 8, 14, 12, 0)
        self.assertEqual(
            self.working_hours_status(checked_at, None, True),
            server_lib.WORKING_HOURS_OUTSIDE,
        )

    def test_all_disabled_working_hours_are_not_a_security_alert(self):
        checked_at = datetime.datetime(2026, 8, 14, 12, 0)
        self.assertEqual(
            self.working_hours_status(checked_at, None, False),
            server_lib.WORKING_HOURS_DISABLED,
        )

    def test_outside_hours_registration_is_saved_as_medium_alert(self):
        connection = AlertConnection()
        server_lib.get_connection = lambda: connection
        server_lib.get_working_hours_status = (
            lambda registered_at: server_lib.WORKING_HOURS_OUTSIDE
        )

        created = server_lib.create_connection_alert(
            {
                "hostname": "workstation-01",
                "mac": "aa:bb:cc:dd:ee:ff",
                "ip": "172.16.1.10",
            },
            datetime.datetime(2026, 8, 14, 18, 0),
        )

        self.assertTrue(created)
        self.assertTrue(connection.committed)
        insert_parameters = connection.executed[-1][1]
        self.assertEqual(
            insert_parameters[1:3],
            ("CONNECTION_OUTSIDE_WORKING_HOURS", "MEDIUM"),
        )


if __name__ == "__main__":
    unittest.main()
