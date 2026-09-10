"""Phase 1 — Packet filter policy for Kismet unicast-filter/probe-scanner.

Defines a single, testable predicate that classifies every parsed 802.11
packet row into KEEP or DROP with an explicit reason string.  The policy is:

- Data frames with a unicast destination  → KEEP  (useful client telemetry)
- Data frames with broadcast/multicast    → DROP  (duplicated data traffic)
- Management: Probe Request               → KEEP  (required for fingerprinting,
                                                   regardless of destination)
- Management: all other subtypes          → DROP  (not needed here)
- Control frames                          → DROP  (RF noise)
- Extension / unknown type                → DROP
- Malformed / unparseable                 → DROP

This module imports only from the standard library and from the canonical
server-side parsers.  It never copies packet payloads or opens SQLite files.
"""

from __future__ import annotations

import sys
import os
from enum import Enum
from typing import Any, Dict, NamedTuple, Optional

# ---------------------------------------------------------------------------
# Import canonical helpers from the server package.  When this tool is invoked
# from the repository root with ``python -m tools.kismet_probe_scanner`` the
# server/ directory is on sys.path via the path setup in __main__.py.
# ---------------------------------------------------------------------------
_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SERVER_DIR))

from server_components.kismet_ml_foundation import parse_80211_packet  # noqa: E402
from server_components.kismet_service import (  # noqa: E402
    normalize_mac,
    destination_kind,
)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

FILTER_VERSION = "kismet-filter-v1"

# Data subtypes that carry application payload and are worth retaining if their
# destination is unicast.
_UNICAST_DATA_SUBTYPES = {"Data", "QoS Data"}

# Management subtypes that are always retained because they are needed for the
# fingerprinting pipeline.  Probe Requests may be broadcast-destined; that is
# intentional and does NOT cause a DROP.
_KEEP_MANAGEMENT_SUBTYPES = {"Probe Request"}

# Control subtypes treated as pure RF noise and dropped unconditionally.
_CONTROL_NOISE_SUBTYPES = {"ACK", "CTS", "RTS", "Block Ack", "Block Ack Request", "CF-End", "PS-Poll"}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class Decision(str, Enum):
    KEEP = "KEEP"
    DROP = "DROP"


class FilterResult(NamedTuple):
    """Immutable decision for a single parsed packet row."""

    decision: Decision
    reason: str
    frame_type: Optional[str]
    frame_subtype: Optional[str]
    destination_kind: Optional[str]  # broadcast | multicast | unicast | unknown


# ---------------------------------------------------------------------------
# Core predicate
# ---------------------------------------------------------------------------

def classify_packet(
    packet: Any,
    *,
    dlt: Any,
    source_mac: Any = None,
    destination_mac: Any = None,
    transmitter_mac: Any = None,
) -> FilterResult:
    """Classify one raw packet row using the unicast-filter/probe policy.

    Parameters
    ----------
    packet:
        Raw bytes from the Kismet ``packets.packet`` column (may be None or
        empty for malformed rows).
    dlt:
        Link-layer DLT value from the same row.
    source_mac, destination_mac, transmitter_mac:
        Kismet column values used as fallbacks inside ``parse_80211_packet``.

    Returns
    -------
    FilterResult
        Always returns a result; never raises for invalid input.
    """
    if not isinstance(packet, (bytes, bytearray, memoryview)) or not packet:
        return FilterResult(
            decision=Decision.DROP,
            reason="malformed: empty or non-bytes packet payload",
            frame_type=None,
            frame_subtype=None,
            destination_kind=None,
        )

    parsed = parse_80211_packet(
        packet,
        dlt=dlt,
        source_mac=source_mac,
        destination_mac=destination_mac,
        transmitter_mac=transmitter_mac,
    )

    if not parsed:
        return FilterResult(
            decision=Decision.DROP,
            reason="malformed: parse_80211_packet returned None",
            frame_type=None,
            frame_subtype=None,
            destination_kind=None,
        )

    ftype: str = parsed.get("frame_type", "")
    fsubtype: str = parsed.get("frame_subtype", "")
    norm_dest = normalize_mac(parsed.get("destination_mac"))
    dest_kind = destination_kind(norm_dest)

    # ------------------------------------------------------------------ Data
    if ftype == "Data":
        if dest_kind == "unicast":
            return FilterResult(
                decision=Decision.KEEP,
                reason="data frame with unicast destination",
                frame_type=ftype,
                frame_subtype=fsubtype,
                destination_kind=dest_kind,
            )
        return FilterResult(
            decision=Decision.DROP,
            reason=f"data frame with {dest_kind} destination (duplicated client traffic)",
            frame_type=ftype,
            frame_subtype=fsubtype,
            destination_kind=dest_kind,
        )

    # ------------------------------------------------------ Management frames
    if ftype == "Management":
        if fsubtype in _KEEP_MANAGEMENT_SUBTYPES:
            return FilterResult(
                decision=Decision.KEEP,
                reason=f"management frame: {fsubtype} (fingerprinting required)",
                frame_type=ftype,
                frame_subtype=fsubtype,
                destination_kind=dest_kind,
            )
        return FilterResult(
            decision=Decision.DROP,
            reason=f"management frame: {fsubtype} (not needed by standalone scanner)",
            frame_type=ftype,
            frame_subtype=fsubtype,
            destination_kind=dest_kind,
        )

    # -------------------------------------------------------- Control frames
    if ftype == "Control":
        return FilterResult(
            decision=Decision.DROP,
            reason=f"control frame noise: {fsubtype}",
            frame_type=ftype,
            frame_subtype=fsubtype,
            destination_kind=dest_kind,
        )

    # ---------------------------------------- Extension / unknown frame type
    return FilterResult(
        decision=Decision.DROP,
        reason=f"unrecognised or extension frame type: {ftype}/{fsubtype}",
        frame_type=ftype,
        frame_subtype=fsubtype,
        destination_kind=dest_kind,
    )


def classify_parsed(parsed: Dict[str, Any]) -> FilterResult:
    """Classify a packet that has already been parsed by ``parse_80211_packet``.

    Useful in scanner hot-paths where the parse result is already available.

    Parameters
    ----------
    parsed:
        The dict returned by ``parse_80211_packet``.  Must not be None.
    """
    ftype: str = parsed.get("frame_type", "")
    fsubtype: str = parsed.get("frame_subtype", "")
    norm_dest = normalize_mac(parsed.get("destination_mac"))
    dest_kind = destination_kind(norm_dest)

    if ftype == "Data":
        if dest_kind == "unicast":
            return FilterResult(Decision.KEEP, "data frame with unicast destination", ftype, fsubtype, dest_kind)
        return FilterResult(Decision.DROP, f"data frame with {dest_kind} destination (duplicated client traffic)", ftype, fsubtype, dest_kind)

    if ftype == "Management":
        if fsubtype in _KEEP_MANAGEMENT_SUBTYPES:
            return FilterResult(Decision.KEEP, f"management frame: {fsubtype} (fingerprinting required)", ftype, fsubtype, dest_kind)
        return FilterResult(Decision.DROP, f"management frame: {fsubtype} (not needed by standalone scanner)", ftype, fsubtype, dest_kind)

    if ftype == "Control":
        return FilterResult(Decision.DROP, f"control frame noise: {fsubtype}", ftype, fsubtype, dest_kind)

    return FilterResult(Decision.DROP, f"unrecognised or extension frame type: {ftype}/{fsubtype}", ftype, fsubtype, dest_kind)
