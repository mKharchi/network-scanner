from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from database import get_connection

connection = get_connection()
cursor = connection.cursor(dictionary=True)
try:
    cursor.execute(
        """SELECT COLUMN_NAME
           FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sensors'
           ORDER BY ORDINAL_POSITION"""
    )
    print("SENSOR_COLUMNS=", [row["COLUMN_NAME"] for row in cursor.fetchall()])

    cursor.execute(
        """SELECT id, sensor_id, name, status, location_id, x, y, z, last_seen
           FROM sensors ORDER BY id"""
    )
    print("SENSORS=", cursor.fetchall())

    cursor.execute("SELECT COUNT(*) AS count FROM network_device_observations")
    print("OBSERVATION_COUNT=", cursor.fetchone())

    cursor.execute(
        """SELECT c.client_id, nd.id AS device_id,
                  COUNT(o.id) AS observations,
                  SUM(o.sensor_id IS NOT NULL) AS with_sensor,
                  SUM(o.rssi IS NOT NULL) AS with_rssi
           FROM clients c
           LEFT JOIN network_devices nd
             ON REPLACE(UPPER(nd.mac_address), '-', ':') = REPLACE(UPPER(c.mac), '-', ':')
           LEFT JOIN network_device_observations o ON o.device_id = nd.id
           WHERE c.client_id = %s
           GROUP BY c.client_id, nd.id""",
        ("client-e4fd45ba8b96",),
    )
    print("TARGET_LOCALIZATION_DATA=", cursor.fetchall())

    cursor.execute(
        """SELECT c.client_id, c.mac AS client_mac, c.location_id,
                  c.location_assignment_method, c.location_assignment_status,
                  c.location_failure_reason
           FROM clients c WHERE c.client_id = %s""",
        ("client-e4fd45ba8b96",),
    )
    print("TARGET_CLIENT=", cursor.fetchone())

    cursor.execute(
        """SELECT id, mac_address, hostname, last_seen
           FROM network_devices ORDER BY last_seen DESC LIMIT 20"""
    )
    print("RECENT_NETWORK_DEVICES=", cursor.fetchall())

    cursor.execute(
        """SELECT o.device_id, COUNT(*) AS observations,
                  SUM(o.sensor_id IS NOT NULL) AS with_sensor,
                  SUM(o.rssi IS NOT NULL) AS with_rssi
           FROM network_device_observations o
           GROUP BY o.device_id ORDER BY observations DESC LIMIT 20"""
    )
    print("OBSERVATIONS_BY_DEVICE=", cursor.fetchall())

    cursor.execute(
        """SELECT COUNT(*) AS observations,
                  SUM(o.source_client_id IS NOT NULL) AS with_reporter,
                  SUM(cl.location_id IS NOT NULL) AS from_located_reporter,
                  SUM(o.sensor_id IS NOT NULL) AS with_sensor,
                  SUM(o.rssi IS NOT NULL) AS with_rssi
           FROM network_device_observations o
           LEFT JOIN clients cl ON cl.id = o.source_client_id"""
    )
    print("OBSERVATION_REFERENCE_COVERAGE=", cursor.fetchone())
finally:
    cursor.close()
    connection.close()
