"""Group stored locations into the center floor layout.

The frontend renders this tree; it must not invent aisles, tables, rows, or seats.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _sort_key(value: Any) -> tuple:
    return (value is None, value if value is not None else 0)


def _is_room(location: Dict[str, Any]) -> bool:
    return all(location.get(field) is None for field in ("aisle", "table", "row", "position"))


def _without_client(location: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(location)
    item.pop("client_id", None)
    item.pop("client_state", None)
    item.pop("health", None)
    item.pop("health_status", None)
    return item


def build_floor_layout(locations: List[Dict[str, Any]], floor: int) -> Dict[str, Any]:
    """Return rooms and aisle/table/row stations for one floor."""
    hide_clients = floor == 0
    rooms: List[Dict[str, Any]] = []
    aisle_map: Dict[Any, Dict[Any, Dict[Any, List[Dict[str, Any]]]]] = {}

    for location in locations:
        if location.get("floor") != floor:
            continue
        station = _without_client(location) if hide_clients else dict(location)
        if _is_room(station):
            rooms.append(station)
            continue
        aisle_map.setdefault(station.get("aisle"), {}).setdefault(
            station.get("table"), {}
        ).setdefault(station.get("row"), []).append(station)

    rooms.sort(key=lambda item: (item.get("zone_name") or "", item.get("label") or ""))
    aisles = []
    for aisle_no in sorted(aisle_map, key=_sort_key):
        tables = []
        for table_no in sorted(aisle_map[aisle_no], key=_sort_key):
            rows = []
            for row_no in sorted(aisle_map[aisle_no][table_no], key=_sort_key):
                stations = sorted(
                    aisle_map[aisle_no][table_no][row_no],
                    key=lambda item: _sort_key(item.get("position")),
                )
                rows.append({"row": row_no, "stations": stations})
            tables.append({"table": table_no, "rows": rows})
        aisles.append({"aisle": aisle_no, "tables": tables})

    return {
        "floor": floor,
        "rooms": rooms,
        "aisles": aisles,
        "shows_clients": not hide_clients,
    }


def available_floors(locations: List[Dict[str, Any]]) -> List[int]:
    floors = sorted({int(item["floor"]) for item in locations if item.get("floor") is not None})
    if 0 not in floors:
        floors = [0, *floors]
    return floors
