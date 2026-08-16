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
