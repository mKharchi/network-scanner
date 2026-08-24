"""Central physical-neighbor rules derived from the location hierarchy.

The frontend must consume these classifications instead of guessing adjacency.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


SAME_ROW = "same_row"
SAME_TABLE = "same_table"
NEIGHBORING_TABLE = "neighboring_table"
SAME_ZONE = "same_zone"

RELATIONSHIP_RANK = {
    SAME_ROW: 0,
    SAME_TABLE: 1,
    NEIGHBORING_TABLE: 2,
    SAME_ZONE: 3,
}


def _coord(location: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if location.get(key) is not None:
            return location.get(key)
    return None


def location_coords(location: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "floor": location.get("floor"),
        "zone_type": location.get("zone_type"),
        "zone_name": location.get("zone_name"),
        "aisle": _coord(location, "aisle"),
        "table": _coord(location, "table", "table_no"),
        "row": _coord(location, "column", "row", "row_no"),
        "position": _coord(location, "position"),
    }


def _has_training_grid(coords: Dict[str, Any]) -> bool:
    return all(coords[key] is not None for key in ("aisle", "table", "row", "position"))


def classify_physical_neighbor(
    origin: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Optional[Tuple[str, int]]:
    """Return (relationship, distance) or None if the candidate is not a neighbor."""
    origin_coords = location_coords(origin)
    candidate_coords = location_coords(candidate)

    if origin_coords["floor"] != candidate_coords["floor"]:
        return None
    if origin_coords["zone_type"] != candidate_coords["zone_type"]:
        return None
    if origin_coords["zone_name"] != candidate_coords["zone_name"]:
        return None

    if _has_training_grid(origin_coords) and _has_training_grid(candidate_coords):
        same_aisle = origin_coords["aisle"] == candidate_coords["aisle"]
        same_table = origin_coords["table"] == candidate_coords["table"]
        same_row = origin_coords["row"] == candidate_coords["row"]
        same_position = origin_coords["position"] == candidate_coords["position"]

        if same_aisle and same_table and same_row:
            if same_position:
                return None
            return SAME_ROW, abs(candidate_coords["position"] - origin_coords["position"])

        if same_aisle and same_table and same_position:
            return SAME_TABLE, abs(candidate_coords["row"] - origin_coords["row"])

        if (
            same_aisle
            and same_row
            and same_position
            and abs(candidate_coords["table"] - origin_coords["table"]) == 1
        ):
            return NEIGHBORING_TABLE, abs(candidate_coords["table"] - origin_coords["table"])

        return None

    if not _has_training_grid(origin_coords) and not _has_training_grid(candidate_coords):
        return SAME_ZONE, 1

    return None


def neighbor_sort_key(item: Dict[str, Any]) -> Tuple[int, int, str]:
    relationship = item.get("relationship") or SAME_ZONE
    return (
        RELATIONSHIP_RANK.get(relationship, 99),
        int(item.get("distance") or 0),
        str(item.get("client_id") or ""),
    )
