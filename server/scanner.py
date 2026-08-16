"""Run a one-off, server-local LAN discovery scan.

This convenience entry point delegates to the server discovery module so the
standalone utility and the server menu use the same implementation.
"""

from server_components.network_discovery import (
    NetworkDiscoveryError,
    configure_logging,
    run_manual_scan,
)


def main():
    configure_logging()
    try:
        context, devices, result_path = run_manual_scan()
    except NetworkDiscoveryError as error:
        print(f"Network discovery failed: {error}")
        return 1

    print(f"\nNetwork discovery completed: {len(devices)} device(s) found.")
    print(f"Saved result: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
