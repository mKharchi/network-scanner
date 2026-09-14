# UI Workflow

Open **Wi-Fi Probes** from the Network navigation, or use **View global probe activity** in a device's Kismet investigation panel.

1. Start with a 15-minute lookback and all MACs.
2. Turn on the **Randomized only** filter to inspect locally administered source addresses.
3. Filter to a channel/BSSID when running a controlled capture.
4. Select a row to inspect decoded, payload-safe metadata.
5. Review candidate groups; matching groups share rate/IE/capability patterns without using MAC addresses in the signature.
6. Export the filtered JSON or CSV for review; use the manifest tool only after confirming the real physical-device label.

An empty table does not prove a device lacks probes. It can mean the capture was on another channel, the device did not scan in the window, or the selected filter is too narrow.
