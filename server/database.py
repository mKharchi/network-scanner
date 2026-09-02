import os

try:
    import mysql.connector
except ModuleNotFoundError:
    import types
    mysql_connector = types.ModuleType("mysql.connector")
    mysql_connector.connect = lambda **kwargs: None
    mysql = types.ModuleType("mysql")
    mysql.connector = mysql_connector


def get_connection():
    """
    Establish and return a connection to the MySQL database
    using environment variables with local development fallbacks.
    """
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            database=os.getenv("DB_NAME", "network_scanner"),
            user=os.getenv("DB_USER", "scanner"),
            password=os.getenv("DB_PASSWORD", "scanner_password")
        )
    except Exception:
        return None


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


def _ensure_client_version_columns(cursor):
    """Store the installed network-scanner client version and its last report time."""
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
        "client_version": "VARCHAR(64) NULL",
        "client_version_updated_at": "DATETIME NULL",
    }
    for column_name, definition in columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE clients ADD COLUMN {column_name} {definition}")


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


def _ensure_client_observation_scope_columns(cursor):
    """Persist v2 distributed-capture CIDR assignments across reconnects."""
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
        "observation_scope": "TEXT NULL",
        "observation_scope_updated_at": "DATETIME NULL",
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


def _backfill_observation_sensor_links(cursor):
    """Link historical client observations to their endpoint sensors."""
    cursor.execute(
        """
        UPDATE network_device_observations AS observation
        INNER JOIN sensors AS sensor ON sensor.client_id = observation.source_client_id
        SET observation.sensor_id = sensor.id
        WHERE observation.sensor_id IS NULL
          AND observation.source_client_id IS NOT NULL
        """
    )


def _ensure_device_classification_tables(cursor):
    """Ensure device_classifications and device_labels tables exist."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS device_classifications (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            device_id BIGINT NOT NULL UNIQUE,
            predicted_class VARCHAR(64) NOT NULL,
            confidence DOUBLE NOT NULL,
            model_version VARCHAR(64) NOT NULL,
            source ENUM('ML', 'RULE', 'HUMAN', 'HYBRID') NOT NULL DEFAULT 'ML',
            features_version VARCHAR(32) NOT NULL DEFAULT 'v1',
            evidence TEXT NULL,
            rule_prediction VARCHAR(64) NULL,
            ml_prediction VARCHAR(64) NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
            probabilities TEXT NULL,
            classified_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES network_devices(id) ON DELETE CASCADE,
            INDEX idx_device_classifications_class (predicted_class),
            INDEX idx_device_classifications_confidence (confidence),
            INDEX idx_device_classifications_source (source),
            INDEX idx_device_classifications_status (status)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS device_labels (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            device_id BIGINT NOT NULL,
            label VARCHAR(64) NOT NULL,
            source VARCHAR(32) NOT NULL DEFAULT 'ADMIN',
            confirmed_by VARCHAR(255) NULL,
            notes TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES network_devices(id) ON DELETE CASCADE,
            INDEX idx_device_labels_device (device_id),
            INDEX idx_device_labels_label (label),
            INDEX idx_device_labels_created (created_at)
        )
        """
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
        _ensure_client_observation_scope_columns(cursor)
        _ensure_client_version_columns(cursor)
        _ensure_location_type_column(cursor)
        _ensure_location_spatial_columns(cursor)
        _ensure_observation_spatial_columns(cursor)
        _backfill_observation_sensor_links(cursor)
        _ensure_device_classification_tables(cursor)

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
