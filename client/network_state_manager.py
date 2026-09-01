"""Compatibility module alias for app.network_state_manager."""
from __future__ import annotations
import sys
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
from app import network_state_manager as _module
sys.modules[__name__] = _module
