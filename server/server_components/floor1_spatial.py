"""Authoritative Floor 1 2D world geometry and coordinate helpers.

The active Floor 1 workflow uses meters in a 2D world.  This module is
intentionally independent from the legacy 3D scene renderer so the frontend
and positioning API share one geometry definition without using z.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

FLOOR_0 = 0
FLOOR_1 = 1
FLOOR_2 = 2

FLOOR1_ELEVATION_METERS = 3.0
# Keep this narrow: a Floor 1 map must not display an estimate from another level.
FLOOR1_ELEVATION_TOLERANCE_METERS = 0.75

FLOOR_ELEVATIONS: Dict[int, float] = {
    0: 0.0,
    1: 3.0,
    2: 6.0,
}

FLOOR_ELEVATION_TOLERANCES: Dict[int, float] = {
    0: 0.75,
    1: 0.75,
    2: 0.75,
}

# World dimensions are meters.  The table edges leave a five-meter open gap
# between the left and right sides: left edge 3.5m, right edge 8.5m.
FLOOR0_GEOMETRY: Dict[str, Any] = {
    "floor": FLOOR_0,
    "units": "meters",
    "width": 12.0,
    "height": 27.0,
    "separation_meters": 5.0,
    "rooms": [],
    "stairs": None,
    "tables": [],
}

FLOOR1_GEOMETRY: Dict[str, Any] = {
    "floor": FLOOR_1,
    "units": "meters",
    "width": 12.0,
    "height": 27.0,
    "separation_meters": 5.0,
    "rooms": [
        {"id": "formation-room-1", "x": 0.5, "y": 0.5, "width": 3.0, "height": 3.5, "label": "Formation Room 1"},
        {"id": "formation-room-2", "x": 8.5, "y": 0.5, "width": 3.0, "height": 3.5, "label": "Formation Room 2"},
    ],
    "stairs": {"id": "stairs-left", "x": 0.5, "y": 5.0, "width": 3.0, "height": 3.0, "label": "Stairs"},
    "tables": [
        {"id": "left-table-2", "aisle": 1, "table": 2, "x": 0.5, "y": 16.0, "width": 3.0, "height": 8.0, "orientation": "vertical"},
        {"id": "right-table-1", "aisle": 2, "table": 1, "x": 8.5, "y": 5.0, "width": 3.0, "height": 8.0, "orientation": "vertical"},
        {"id": "right-table-2", "aisle": 2, "table": 2, "x": 8.5, "y": 16.0, "width": 3.0, "height": 8.0, "orientation": "vertical"},
    ],
}

FLOOR2_GEOMETRY: Dict[str, Any] = {
    "floor": FLOOR_2,
    "units": "meters",
    "width": 12.0,
    "height": 27.0,
    "separation_meters": 5.0,
    "rooms": [
        {"id": "formation-room-1", "x": 0.5, "y": 0.5, "width": 3.0, "height": 3.5, "label": "Formation Room 1"},
        {"id": "formation-room-2", "x": 8.5, "y": 0.5, "width": 3.0, "height": 3.5, "label": "Formation Room 2"},
    ],
    "stairs": {"id": "stairs-left", "x": 0.5, "y": 5.0, "width": 3.0, "height": 3.0, "label": "Stairs"},
    "tables": [],
}

FLOOR_GEOMETRIES: Dict[int, Dict[str, Any]] = {
    0: FLOOR0_GEOMETRY,
    1: FLOOR1_GEOMETRY,
    2: FLOOR2_GEOMETRY,
}

_TABLE_ANCHORS: Dict[Tuple[int, int], Tuple[float, float]] = {
    (1, 2): (2.0, 20.0),
    (2, 1): (10.0, 9.0),
    (2, 2): (10.0, 20.0),
}


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_floor1_elevation(estimate_z: Any) -> bool:
    """Return true only when an estimate is tightly aligned with Floor 1."""
    elevation = _number(estimate_z)
    return elevation is not None and abs(elevation - FLOOR1_ELEVATION_METERS) <= FLOOR1_ELEVATION_TOLERANCE_METERS


def is_floor_elevation(estimate_z: Any, floor: int) -> bool:
    """Return true when an estimate is tightly aligned with the specified floor elevation."""
    elevation = _number(estimate_z)
    target = FLOOR_ELEVATIONS.get(floor, FLOOR1_ELEVATION_METERS)
    tolerance = FLOOR_ELEVATION_TOLERANCES.get(floor, FLOOR1_ELEVATION_TOLERANCE_METERS)
    return elevation is not None and abs(elevation - target) <= tolerance


def slot_world_position(location: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Convert a seeded Floor 1 PC slot to its stable 2D world coordinate."""
    if int(location.get("floor") or 0) != FLOOR_1:
        return None
    aisle = location.get("aisle")
    table = location.get("table", location.get("table_no"))
    column = location.get("column", location.get("row", location.get("row_no")))
    position = location.get("position")
    if None in (aisle, table, column, position):
        return None
    try:
        anchor_x, anchor_y = _TABLE_ANCHORS[(int(aisle), int(table))]
        column_offset = -0.6 if int(column) == 1 else 0.6
        y = anchor_y + (int(position) - 2.5) * 1.25
        return {"x": round(anchor_x + column_offset, 2), "y": round(y, 2)}
    except (KeyError, TypeError, ValueError):
        return None


def reference_payload(location: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    floor = int(location.get("floor") or 0)
    if floor != FLOOR_1:
        return None
    position = slot_world_position(location)
    if position is None or not location.get("client_id"):
        return None
    confidence = _number(location.get("location_confidence"))
    return {
        "client_id": location["client_id"],
        "hostname": location.get("hostname"),
        "location_id": location.get("id"),
        "label": location.get("label"),
        **position,
        "confidence": confidence,
        "verified": bool(location.get("location_verified")),
        "floor": FLOOR_1,
    }


def device_position_payload(device: Dict[str, Any], floor: int = FLOOR_1) -> Optional[Dict[str, Any]]:
    """Return a floor target position using assigned slot geometry or explicit coordinates."""
    pos_x = _number(device.get("x"))
    pos_y = _number(device.get("y"))
    
    if pos_x is not None and pos_y is not None:
        position = {"x": round(pos_x, 2), "y": round(pos_y, 2)}
    else:
        position = slot_world_position(device)

    if position is None:
        return None

    dev_floor = int(device.get("floor") or floor)
    return {
        "floor": dev_floor,
        "device_id": device.get("device_id"),
        "mac_address": device.get("mac_address"),
        "ip_address": device.get("ip_address"),
        "hostname": device.get("hostname"),
        "vendor": device.get("vendor"),
        **position,
        "confidence": _number(device.get("confidence")) or 0.0,
        "method": device.get("method") or "NONE",
        "rogue_score": _number(device.get("rogue_score")) or 0.0,
        "is_rogue": bool(device.get("is_rogue")),
        "risk_level": device.get("risk_level") or "LOW",
        "last_seen": device.get("last_seen"),
        "last_dhcp_observed_at": device.get("last_dhcp_observed_at"),
        "activity_source": device.get("activity_source") or "network_scan",
        "estimate_z": _number(device.get("estimate_z")),
        "elevation_delta_meters": _number(device.get("elevation_delta_meters")),
    }
