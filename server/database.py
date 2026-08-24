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
        _ensure_client_health_columns(cursor)

        connection.commit()
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
