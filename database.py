import os
import mysql.connector


def get_connection():

    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv(
            "DB_NAME",
            "network_scanner"
        ),
        user=os.getenv(
            "DB_USER",
            "scanner"
        ),
        password=os.getenv(
            "DB_PASSWORD",
            "scanner_password"
        )
    )
def initiate_db():
    """
    Initialize the MySQL database by executing scripts.sql.
    """

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        with open("scripts.sql", "r", encoding="utf-8") as file:
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

        if connection:
            connection.close()
    """
    Initialize the MySQL database by executing scripts.sql.
    """

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        with open("scripts.sql", "r", encoding="utf-8") as file:
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

        if connection:
            connection.close()
    """
    Initialize the MySQL database by executing scripts.sql.
    """

    connection = None
    cursor = None

    try:
        connection = mysql.connector.connect(
    host=os.getenv("DB_HOST", "mysql"),
    port=int(os.getenv("DB_PORT", 3306)),
    user=os.getenv("DB_USER", "scanner"),
    password=os.getenv("DB_PASSWORD", "scanner_password"),
    database=os.getenv("DB_NAME", "network_scanner"),
)

        cursor = connection.cursor()

        # Read SQL schema
        with open("scripts.sql", "r", encoding="utf-8") as file:
            sql_script = file.read()

        # Execute each statement
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

        if connection:
            connection.close()