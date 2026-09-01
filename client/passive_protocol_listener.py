"""Compatibility module alias for app.passive_protocol_listener."""
from __future__ import annotations
import sys
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
from app import passive_protocol_listener as _module
sys.modules[__name__] = _module
