"""Launch the network client in the signed-in user's Windows session.

This entry point is intended for Task Scheduler's "At log on" trigger.  It
runs as the interactive user, so activity collection uses that user's browser
profiles and Windows Recent folder instead of the LocalSystem service profile.
"""

import os
from pathlib import Path


CLIENT_DIR = Path(__file__).resolve().parent
os.chdir(CLIENT_DIR)

from client import start_client  # noqa: E402  (set the working directory first)


if __name__ == "__main__":
    start_client(agent_role="interactive")
