"""Serve the dependency-free operator GUI shell on a local HTTP port.

This is intentionally separate from the TCP monitoring-client listener in
``server.py``.  It serves static files only; the `/api/v1` read API described
in ``network_monitoring_gui_data_contracts.md`` will be added in a later
milestone.
"""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


GUI_DIRECTORY = Path(__file__).resolve().parent / "gui"
GUI_HOST = os.getenv("GUI_HOST", "127.0.0.1")
GUI_PORT = int(os.getenv("GUI_PORT", "8080"))


class GuiRequestHandler(SimpleHTTPRequestHandler):
    """Serve static GUI assets and fall back to its single-page entry point."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(GUI_DIRECTORY), **kwargs)

    def do_GET(self):  # noqa: N802 - inherited stdlib method name
        path = self.path.split("?", 1)[0]
        if path == "/" or path.startswith("/#"):
            self.path = "/index.html"
        return super().do_GET()


def main():
    if not GUI_DIRECTORY.is_dir():
        raise RuntimeError(f"GUI directory is missing: {GUI_DIRECTORY}")

    server = ThreadingHTTPServer((GUI_HOST, GUI_PORT), GuiRequestHandler)
    print(f"Network Monitoring GUI available at http://{GUI_HOST}:{GUI_PORT}")
    print("This shell has no API connection yet; monitoring data is unavailable.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GUI server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
