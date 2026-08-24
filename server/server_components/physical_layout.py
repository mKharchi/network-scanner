"""Group stored locations into the center floor layout.

The frontend renders this tree; it must not invent aisles, tables, columns, or seats.
"""

from __future__ import annotations

from typing import Any, Dict, List

from server_components.center_layout import (
    LOCATION_TYPE_AISLE,
    LOCATION_TYPE_FLOOR,
    LOCATION_TYPE_FORMATION_ROOM,
    LOCATION_TYPE_PC_POSITION,
    LOCATION_TYPE_STAIRS,
    LOCATION_TYPE_TABLE,
)


def _sort_key(value: Any) -> tuple:
    return (value is None, value if value is not None else 0)


def _location_type(location: Dict[str, Any]) -> str:
    explicit = location.get("location_type")
    if explicit:
        return explicit
    if all(location.get(field) is None for field in ("aisle", "table", "row", "column", "position")):
        if location.get("zone_type") in {LOCATION_TYPE_FORMATION_ROOM, "conference_room"}:
            return LOCATION_TYPE_FORMATION_ROOM
        return LOCATION_TYPE_FLOOR
    return LOCATION_TYPE_PC_POSITION


def _without_client(location: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(location)
    item.pop("client_id", None)
    item.pop("client_state", None)
    item.pop("health", None)
    item.pop("health_status", None)
    item.pop("hostname", None)
    return item


def _column_number(location: Dict[str, Any]) -> Any:
    if location.get("column") is not None:
        return location.get("column")
    return location.get("row")


def build_floor_layout(locations: List[Dict[str, Any]], floor: int) -> Dict[str, Any]:
    """Return rooms and aisle/table/column stations for one floor."""
    hide_clients = floor == 0
    rooms: List[Dict[str, Any]] = []
    stairs_by_aisle: Dict[Any, Dict[str, Any]] = {}
    aisle_map: Dict[Any, Dict[Any, Dict[Any, List[Dict[str, Any]]]]] = {}

    for location in locations:
        if location.get("floor") != floor:
            continue
        station = _without_client(location) if hide_clients else dict(location)
        kind = _location_type(station)
        if kind in {LOCATION_TYPE_FLOOR, LOCATION_TYPE_AISLE, LOCATION_TYPE_TABLE}:
            continue
        if kind == LOCATION_TYPE_FORMATION_ROOM:
            rooms.append(station)
            continue
        if kind == LOCATION_TYPE_STAIRS:
            stairs_by_aisle[station.get("aisle")] = station
            continue
        if kind != LOCATION_TYPE_PC_POSITION:
            continue
        aisle_map.setdefault(station.get("aisle"), {}).setdefault(
            station.get("table"), {}
        ).setdefault(_column_number(station), []).append(station)

    rooms.sort(key=lambda item: (item.get("zone_name") or "", item.get("label") or ""))
    aisle_numbers = set(aisle_map) | set(stairs_by_aisle)
    aisles = []
    for aisle_no in sorted(aisle_numbers, key=_sort_key):
        tables = []
        table_numbers = set(aisle_map.get(aisle_no, {}))
        stairs = stairs_by_aisle.get(aisle_no)
        if stairs is not None:
            table_numbers.add(stairs.get("table") if stairs.get("table") is not None else 1)
        for table_no in sorted(table_numbers, key=_sort_key):
            if stairs is not None and table_no == (stairs.get("table") if stairs.get("table") is not None else 1):
                tables.append(
                    {
                        "table": table_no,
                        "kind": "stairs",
                        "label": stairs.get("label"),
                        "location": stairs,
                        "columns": [],
                        "rows": [],
                    }
                )
                continue
            columns = []
            for column_no in sorted(aisle_map.get(aisle_no, {}).get(table_no, {}), key=_sort_key):
                stations = sorted(
                    aisle_map[aisle_no][table_no][column_no],
                    key=lambda item: _sort_key(item.get("position")),
                )
                columns.append({"column": column_no, "row": column_no, "stations": stations})
            tables.append({
                "table": table_no,
                "kind": "table",
                "columns": columns,
                "rows": columns,
            })
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
