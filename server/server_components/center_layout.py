"""Canonical training-center geometry and idempotent location seeding.

The physical structure is known in advance. Administrators assign clients to
seeded PC positions; they should not create floors, aisles, tables, or seats
by hand.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


LOCATION_TYPE_FLOOR = "floor"
LOCATION_TYPE_FORMATION_ROOM = "formation_room"
LOCATION_TYPE_AISLE = "aisle"
LOCATION_TYPE_TABLE = "table"
LOCATION_TYPE_STAIRS = "stairs"
LOCATION_TYPE_PC_POSITION = "pc_position"

ASSIGNABLE_LOCATION_TYPES = {LOCATION_TYPE_PC_POSITION}

COLUMNS_PER_TABLE = (1, 2)
POSITIONS_PER_COLUMN = (1, 2, 3, 4)

# Floor → aisle → stairs flag and table numbers. Table 1 is omitted wherever
# stairs occupy that slot (Floor 1 / Aisle 1).
CENTER_LAYOUT = {
    0: {"rooms": [], "aisles": {}},
    1: {
        "rooms": ["Formation Room 1", "Formation Room 2"],
        "aisles": {
            1: {"stairs": True, "tables": [2]},
            2: {"stairs": False, "tables": [1, 2]},
        },
    },
    2: {
        "rooms": ["Formation Room 1", "Formation Room 2"],
        "aisles": {
            1: {"stairs": False, "tables": [1, 2]},
            2: {"stairs": False, "tables": [1, 2]},
        },
    },
}


def _record(
    *,
    floor: int,
    location_type: str,
    label: str,
    zone_type: str,
    zone_name: Optional[str] = None,
    aisle: Optional[int] = None,
    table: Optional[int] = None,
    column: Optional[int] = None,
    position: Optional[int] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    z: Optional[float] = None,
    is_restricted: bool = False,
) -> Dict[str, Any]:
    return {
        "floor": floor,
        "location_type": location_type,
        "zone_type": zone_type,
        "zone_name": zone_name,
        "aisle": aisle,
        "table": table,
        "row": column,
        "column": column,
        "position": position,
        "label": label,
        "x": x,
        "y": y,
        "z": z,
        "is_restricted": is_restricted,
    }


def generate_center_locations() -> List[Dict[str, Any]]:
    """Return the complete center structure with spatial coordinates without touching the database."""
    records: List[Dict[str, Any]] = []
    for floor, spec in CENTER_LAYOUT.items():
        floor_z = float(floor * 3.0)
        records.append(
            _record(
                floor=floor,
                location_type=LOCATION_TYPE_FLOOR,
                label=f"F{floor}",
                zone_type=LOCATION_TYPE_FLOOR,
                x=15.0,
                y=15.0,
                z=floor_z,
                is_restricted=False,
            )
        )
        for room_index, room_name in enumerate(spec.get("rooms") or [], start=1):
            room_x = 5.0 if room_index == 1 else 25.0
            room_y = 5.0
            records.append(
                _record(
                    floor=floor,
                    location_type=LOCATION_TYPE_FORMATION_ROOM,
                    label=f"F{floor}-Room-{room_index}",
                    zone_type=LOCATION_TYPE_FORMATION_ROOM,
                    zone_name=room_name,
                    x=room_x,
                    y=room_y,
                    z=floor_z,
                    is_restricted=True,
                )
            )
        for aisle_no, aisle_spec in (spec.get("aisles") or {}).items():
            aisle_x = float(aisle_no * 10.0)
            records.append(
                _record(
                    floor=floor,
                    location_type=LOCATION_TYPE_AISLE,
                    label=f"F{floor}-A{aisle_no}",
                    zone_type="training",
                    aisle=aisle_no,
                    x=aisle_x,
                    y=15.0,
                    z=floor_z,
                    is_restricted=False,
                )
            )
            if aisle_spec.get("stairs"):
                records.append(
                    _record(
                        floor=floor,
                        location_type=LOCATION_TYPE_STAIRS,
                        label=f"F{floor}-A{aisle_no}-Stairs",
                        zone_type="training",
                        aisle=aisle_no,
                        table=1,
                        x=aisle_x,
                        y=8.0,
                        z=floor_z,
                        is_restricted=False,
                    )
                )
            for table_no in aisle_spec.get("tables") or []:
                table_y = 8.0 if table_no == 1 else 20.0
                records.append(
                    _record(
                        floor=floor,
                        location_type=LOCATION_TYPE_TABLE,
                        label=f"F{floor}-A{aisle_no}-T{table_no}",
                        zone_type="training",
                        aisle=aisle_no,
                        table=table_no,
                        x=aisle_x,
                        y=table_y,
                        z=floor_z,
                        is_restricted=False,
                    )
                )
                for column in COLUMNS_PER_TABLE:
                    col_y_offset = -1.5 if column == 1 else 1.5
                    for position in POSITIONS_PER_COLUMN:
                        pos_x = aisle_x - 1.5 + float(position - 1) * 1.0
                        pos_y = table_y + col_y_offset
                        records.append(
                            _record(
                                floor=floor,
                                location_type=LOCATION_TYPE_PC_POSITION,
                                label=f"F{floor}-A{aisle_no}-T{table_no}-C{column}-P{position}",
                                zone_type="training",
                                aisle=aisle_no,
                                table=table_no,
                                column=column,
                                position=position,
                                x=round(pos_x, 2),
                                y=round(pos_y, 2),
                                z=floor_z,
                                is_restricted=False,
                            )
                        )
    return records


def pc_position_records(records: Optional[Iterable[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    source = list(records) if records is not None else generate_center_locations()
    return [item for item in source if item["location_type"] == LOCATION_TYPE_PC_POSITION]


def layout_counts(records: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    source = list(records) if records is not None else generate_center_locations()
    pc_positions = pc_position_records(source)
    by_floor: Dict[int, int] = {}
    for item in pc_positions:
        by_floor[item["floor"]] = by_floor.get(item["floor"], 0) + 1
    type_counts: Dict[str, int] = {}
    for item in source:
        type_counts[item["location_type"]] = type_counts.get(item["location_type"], 0) + 1
    return {
        "total_records": len(source),
        "pc_positions": len(pc_positions),
        "pc_positions_by_floor": by_floor,
        "type_counts": type_counts,
    }


def _insert_location(cursor, record: Dict[str, Any]) -> bool:
    cursor.execute("SELECT id FROM locations WHERE label = %s", (record["label"],))
    row = cursor.fetchone()
    if row:
        cursor.execute(
            """UPDATE locations
               SET x = COALESCE(x, %s),
                   y = COALESCE(y, %s),
                   z = COALESCE(z, %s),
                   is_restricted = %s
               WHERE id = %s""",
            (
                record.get("x"),
                record.get("y"),
                record.get("z"),
                1 if record.get("is_restricted") else 0,
                row[0],
            ),
        )
        return False
    cursor.execute(
        """INSERT INTO locations
           (floor, zone_type, zone_name, aisle, table_no, row_no, position, label, location_type, x, y, z, is_restricted)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            record["floor"],
            record["zone_type"],
            record.get("zone_name"),
            record.get("aisle"),
            record.get("table"),
            record.get("column"),
            record.get("position"),
            record["label"],
            record["location_type"],
            record.get("x"),
            record.get("y"),
            record.get("z"),
            1 if record.get("is_restricted") else 0,
        ),
    )
    return True


def seed_center_layout(conn=None) -> Dict[str, int]:
    """Insert missing center records. Safe to run repeatedly."""
    from database import get_connection

    owns_connection = conn is None
    if owns_connection:
        conn = get_connection()
        if not conn:
            raise ValueError("Database unavailable.")
    cursor = conn.cursor()
    created = 0
    try:
        for record in generate_center_locations():
            if _insert_location(cursor, record):
                created += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        if owns_connection:
            conn.close()
    counts = layout_counts()
    return {
        "created": created,
        "pc_positions": counts["pc_positions"],
        "skipped": counts["total_records"] - created,
    }
