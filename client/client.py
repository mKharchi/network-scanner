"""Compatibility launcher for the refactored client application."""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app import client as _module
sys.modules[__name__] = _module

if __name__ == "__main__":
    _module.start_client(agent_role="combined")
