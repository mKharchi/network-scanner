"""Aggregate the latest client-reported LAN discoveries once.

The retained server-local discovery helpers are deliberately not called by
this entry point.
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

    print(f"\nClient network reports merged: {len(devices)} device(s) found.")
    print(f"Saved result: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
