"""CLI: python seed_center_layout.py

Idempotently inserts the training-center floors, rooms, aisles, tables,
stairs, and 56 PC positions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(SERVER_DIRECTORY, ".env"))
except ImportError:
    pass

from database import initiate_db  # noqa: E402
from server_components.center_layout import layout_counts, seed_center_layout  # noqa: E402


def main() -> int:
    initiate_db()
    result = seed_center_layout()
    counts = layout_counts()
    print(
        f"Seed complete: created={result['created']} skipped={result['skipped']} "
        f"pc_positions={counts['pc_positions']} "
        f"by_floor={counts['pc_positions_by_floor']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
