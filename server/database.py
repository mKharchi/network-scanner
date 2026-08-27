import os
import mysql.connector


def get_connection():
    """
    Establish and return a connection to the MySQL database
    using environment variables with local development fallbacks.
    """
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "network_scanner"),
        user=os.getenv("DB_USER", "scanner"),
        password=os.getenv("DB_PASSWORD", "scanner_password")
    )


def _ensure_network_device_metadata_columns(cursor):
    """Add client-enriched metadata columns for installations with older schema."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'network_devices'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    for column_name in ("hostname", "vendor"):
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE network_devices ADD COLUMN {column_name} VARCHAR(255) NULL"
            )


def _ensure_client_location_column(cursor):
    """Add the nullable location relationship to installations with older schema."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'clients'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    if "location_id" not in existing_columns:
        cursor.execute("ALTER TABLE clients ADD COLUMN location_id INT NULL")


def _ensure_client_location_assignment_columns(cursor):
    """Hybrid auto/manual assignment metadata on the current client location."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'clients'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    columns = {
        "location_assignment_method": "VARCHAR(16) NULL",
        "location_assignment_status": "VARCHAR(16) NULL",
        "location_confidence": "DOUBLE NULL",
        "location_verified": "BOOLEAN NOT NULL DEFAULT FALSE",
        "location_assigned_at": "DATETIME NULL",
        "location_assigned_by": "VARCHAR(255) NULL",
        "location_last_calculated_at": "DATETIME NULL",
        "location_source": "VARCHAR(64) NULL",
        "location_evidence": "TEXT NULL",
        "location_failure_reason": "VARCHAR(255) NULL",
    }
    for column_name, definition in columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE clients ADD COLUMN {column_name} {definition}")


def _ensure_client_location_history_assignment_columns(cursor):
    """Preserve assignment method/confidence evidence on the audit trail."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'client_location_history'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    columns = {
        "assignment_method": "VARCHAR(16) NULL",
        "assignment_status": "VARCHAR(16) NULL",
        "confidence": "DOUBLE NULL",
        "verified": "BOOLEAN NOT NULL DEFAULT FALSE",
        "source": "VARCHAR(64) NULL",
        "evidence": "TEXT NULL",
    }
    for column_name, definition in columns.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE client_location_history ADD COLUMN {column_name} {definition}"
            )


def _ensure_client_health_columns(cursor):
    """Store the last health snapshot used by the center visualization."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'clients'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    columns = {
        "health_cpu_percent": "DOUBLE NULL",
        "health_memory_percent": "DOUBLE NULL",
        "health_disk_percent": "DOUBLE NULL",
        "health_updated_at": "DATETIME NULL",
    }
    for column_name, definition in columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE clients ADD COLUMN {column_name} {definition}")


def _ensure_location_type_column(cursor):
    """Add location_type and physical layout hierarchy columns to locations."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'locations'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    columns = {
        "location_type": "VARCHAR(32) NOT NULL DEFAULT 'pc_position'",
        "aisle": "INT NULL",
        "table_no": "INT NULL",
        "row_no": "INT NULL",
        "position": "INT NULL",
        "label": "VARCHAR(64) NOT NULL DEFAULT ''",
    }
    for column_name, definition in columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE locations ADD COLUMN {column_name} {definition}")


def _ensure_location_spatial_columns(cursor):
    """Add spatial coordinates and hierarchy columns to locations."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'locations'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    columns = {
        "parent_id": "INT NULL",
        "x": "DOUBLE NULL",
        "y": "DOUBLE NULL",
        "z": "DOUBLE NULL",
        "is_restricted": "BOOLEAN NOT NULL DEFAULT FALSE",
        "metadata": "TEXT NULL",
    }
    for column_name, definition in columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE locations ADD COLUMN {column_name} {definition}")


def _ensure_observation_spatial_columns(cursor):
    """Add spatial sensor and signal columns to network_device_observations."""
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'network_device_observations'
        """
    )
    existing_columns = {row[0] for row in cursor.fetchall()}
    columns = {
        "sensor_id": "INT NULL",
        "rssi": "INT NULL",
        "switch_port": "VARCHAR(64) NULL",
        "raw_data": "TEXT NULL",
    }
    for column_name, definition in columns.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE network_device_observations ADD COLUMN {column_name} {definition}"
            )


def initiate_db():
    """
    Initialize the MySQL database schema by executing scripts.sql.
    """
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Locate scripts.sql relative to this file or current working directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sql_path = os.path.join(current_dir, "scripts.sql")
        if not os.path.exists(sql_path):
            sql_path = "scripts.sql"

        with open(sql_path, "r", encoding="utf-8") as file:
            sql_script = file.read()

        for statement in sql_script.split(";"):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)

        _ensure_network_device_metadata_columns(cursor)
        _ensure_client_location_column(cursor)
        _ensure_client_location_assignment_columns(cursor)
        _ensure_client_location_history_assignment_columns(cursor)
        _ensure_client_health_columns(cursor)
        _ensure_location_type_column(cursor)
        _ensure_location_spatial_columns(cursor)
        _ensure_observation_spatial_columns(cursor)

        connection.commit()
        try:
            from server_components.center_layout import seed_center_layout

            seed_result = seed_center_layout(connection)
            print(
                "Center layout seed: "
                f"{seed_result['created']} new records, "
                f"{seed_result['pc_positions']} PC positions."
            )
        except Exception as seed_error:
            print(f"Center layout seed skipped: {seed_error}")

        print("Database initialized successfully.")

    except mysql.connector.Error as error:
        print(f"Database initialization failed: {error}")

    except FileNotFoundError:
        print("scripts.sql not found.")

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
