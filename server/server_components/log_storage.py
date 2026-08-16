import json
import os
from datetime import datetime

# Default storage path under server/storage/logs
DEFAULT_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "storage",
    "logs"
)

LOG_STORAGE_DIR = os.getenv("LOG_STORAGE_DIR", DEFAULT_STORAGE_DIR)


def store_log_file(client_id, log_data):
    """
    Store a complete activity-log response as a JSON file.

    Directory structure:
        server/storage/logs/
            client-1/
                2026-08-15_14-30-00.json
            client-2/
                2026-08-15_15-00-00.json

    Returns the absolute or configured relative file path.
    """
    client_dir = os.path.join(LOG_STORAGE_DIR, client_id)
    os.makedirs(client_dir, exist_ok=True)

    generated_at = log_data.get("generated_at")
    if generated_at:
        try:
            timestamp = datetime.fromisoformat(generated_at)
        except ValueError:
            try:
                timestamp = datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                timestamp = datetime.now()
    else:
        timestamp = datetime.now()

    filename = timestamp.strftime("%Y-%m-%d_%H-%M-%S") + ".json"
    file_path = os.path.join(client_dir, filename)

    # Avoid overwriting a log generated at the exact same second
    counter = 1
    while os.path.exists(file_path):
        filename = timestamp.strftime("%Y-%m-%d_%H-%M-%S") + f"_{counter}.json"
        file_path = os.path.join(client_dir, filename)
        counter += 1

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(log_data, file, indent=2, ensure_ascii=False)

    return file_path
