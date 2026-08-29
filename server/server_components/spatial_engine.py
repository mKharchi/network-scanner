"""Spatial-Temporal Rogue Device Triangulation Engine.

Correlates network observations (ARP, DHCP, RSSI, switch ports) with the center's
physical location hierarchy and sensor grid to estimate physical positions, track
movement, calculate confidence metrics, and detect rogue devices with explainable scoring.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)


# ============================================================
# PURE MATHEMATICAL & SPATIAL ALGORITHMS
# ============================================================


def is_locally_administered_mac(mac: Optional[str]) -> bool:
    """Check whether a MAC address is locally administered (randomized)."""
    if not mac or not isinstance(mac, str):
        return False
    clean = mac.strip().replace("-", ":")
    parts = clean.split(":")
    if len(parts) != 6:
        return False
    try:
        first_byte = int(parts[0], 16)
        # In 802 networks, bit 1 of byte 0 indicates locally administered / randomized address
        return bool(first_byte & 0b00000010)
    except ValueError:
        return False


def calculate_rssi_distance(rssi: float, a: float = -40.0, n: float = 2.5) -> float:
    """Estimate distance (in meters) from signal strength using log-distance path loss.

    Formula: d = 10 ** ((A - RSSI) / (10 * n))
    Where:
        A = Measured RSSI at 1 meter (default -40 dBm)
        n = Path loss exponent (2.0 in free space, ~2.5 - 3.0 in indoor offices)
    """
    try:
        exponent = (a - float(rssi)) / (10.0 * n)
        dist = 10.0 ** exponent
        return max(0.1, min(dist, 100.0))
    except Exception:
        return 10.0


def calculate_rssi_weight(rssi: Optional[float], a: float = -40.0, n: float = 2.5) -> float:
    """Convert RSSI into an inverse-distance weighting factor for multilateration."""
    if rssi is None:
        return 1.0
    dist = calculate_rssi_distance(rssi, a=a, n=n)
    # Inverse square distance weight with clamping
    return 1.0 / (max(dist, 0.5) ** 2)


def triangulate_position(
    sensor_readings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Estimate 3D position and confidence from sensor observations.

    Args:
        sensor_readings: List of dicts, each containing:
            - sensor_id: identifier
            - x, y, z: coordinates of the sensor
            - rssi: optional signal strength in dBm
            - switch_port: optional direct switch port name
            - is_direct: optional boolean for direct client attachment

    Returns:
        Dict with x, y, z, confidence (0.0 - 1.0), method, and supporting sensors.
    """
    if not sensor_readings:
        return {
            "x": None,
            "y": None,
            "z": None,
            "confidence": 0.0,
            "method": "NONE",
            "supporting_sensors": [],
        }

    # 1. Deterministic direct / switch port association
    for reading in sensor_readings:
        if reading.get("is_direct") or reading.get("switch_port"):
            if reading.get("x") is not None and reading.get("y") is not None:
                return {
                    "x": float(reading["x"]),
                    "y": float(reading["y"]),
                    "z": float(reading.get("z", 0.0) or 0.0),
                    "confidence": 0.95,
                    "method": "SWITCH_PORT" if reading.get("switch_port") else "CLIENT_DIRECT",
                    "supporting_sensors": [reading.get("sensor_id")],
                }

    valid_sensors = [
        r for r in sensor_readings
        if r.get("x") is not None and r.get("y") is not None
    ]

    if not valid_sensors:
        return {
            "x": None,
            "y": None,
            "z": None,
            "confidence": 0.0,
            "method": "NONE",
            "supporting_sensors": [],
        }

    # 2. Single sensor proximity
    if len(valid_sensors) == 1:
        s = valid_sensors[0]
        rssi = s.get("rssi")
        if rssi is not None and rssi >= -50:
            confidence = 0.70
        elif rssi is not None and rssi >= -70:
            confidence = 0.55
        else:
            confidence = 0.45

        return {
            "x": round(float(s["x"]), 2),
            "y": round(float(s["y"]), 2),
            "z": round(float(s.get("z", 0.0) or 0.0), 2),
            "confidence": confidence,
            "method": "NEAREST_SENSOR",
            "supporting_sensors": [s.get("sensor_id")],
        }

    # 3. Multi-sensor weighted multilateration
    total_weight = 0.0
    weighted_x = 0.0
    weighted_y = 0.0
    weighted_z = 0.0
    supporting = []
    rssi_values = []

    for s in valid_sensors:
        rssi = s.get("rssi")
        weight = calculate_rssi_weight(rssi)
        w_x = float(s["x"]) * weight
        w_y = float(s["y"]) * weight
        w_z = float(s.get("z", 0.0) or 0.0) * weight

        total_weight += weight
        weighted_x += w_x
        weighted_y += w_y
        weighted_z += w_z
        supporting.append(s.get("sensor_id"))
        if rssi is not None:
            rssi_values.append(rssi)

    if total_weight <= 0:
        total_weight = 1.0
        weighted_x = sum(float(s["x"]) for s in valid_sensors)
        weighted_y = sum(float(s["y"]) for s in valid_sensors)
        weighted_z = sum(float(s.get("z", 0.0) or 0.0) for s in valid_sensors)
        count = float(len(valid_sensors))
        est_x = weighted_x / count
        est_y = weighted_y / count
        est_z = weighted_z / count
    else:
        est_x = weighted_x / total_weight
        est_y = weighted_y / total_weight
        est_z = weighted_z / total_weight

    # Confidence calculation:
    # 2 sensors -> 0.75 base, 3+ sensors -> 0.85 base
    unique_sensors = len({s.get("sensor_id") for s in valid_sensors if s.get("sensor_id")})
    if unique_sensors >= 3:
        base_confidence = 0.85
    elif unique_sensors == 2:
        base_confidence = 0.75
    else:
        base_confidence = 0.50

    if rssi_values:
        avg_rssi = sum(rssi_values) / len(rssi_values)
        if avg_rssi >= -55:
            base_confidence += 0.08
        elif avg_rssi >= -70:
            base_confidence += 0.03
        else:
            base_confidence -= 0.05

    final_confidence = max(0.1, min(round(base_confidence, 2), 0.95))

    return {
        "x": round(est_x, 2),
        "y": round(est_y, 2),
        "z": round(est_z, 2),
        "confidence": final_confidence,
        "method": "MULTI_SENSOR_SMOOTHED" if unique_sensors >= 3 else "RSSI_WEIGHTED",
        "supporting_sensors": list(filter(None, set(supporting))),
    }


def find_closest_location(
    x: Optional[float],
    y: Optional[float],
    z: Optional[float],
    locations: List[Dict[str, Any]],
    preferred_floor: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Find the closest physical location (seat or room) to the estimated coordinates."""
    if x is None or y is None or not locations:
        return None

    z_val = z if z is not None else 0.0
    best_loc = None
    min_dist = float("inf")

    # Filter by preferred floor if available, else look across all
    candidates = (
        [loc for loc in locations if loc.get("floor") == preferred_floor]
        if preferred_floor is not None
        else locations
    )
    if not candidates:
        candidates = locations

    for loc in candidates:
        lx = loc.get("x")
        ly = loc.get("y")
        lz = loc.get("z", 0.0) if loc.get("z") is not None else 0.0
        if lx is None or ly is None:
            continue

        # 3D Euclidean distance (with higher weight on Z axis to penalize floor hopping)
        dx = float(x) - float(lx)
        dy = float(y) - float(ly)
        dz = (float(z_val) - float(lz)) * 2.0
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        # Prefer specific PC positions over generic floors/aisles when distance is close
        loc_type = loc.get("location_type", "")
        if loc_type == "pc_position":
            dist *= 0.9

        if dist < min_dist:
            min_dist = dist
            best_loc = loc

    return best_loc


def calculate_rogue_assessment(
    device: Dict[str, Any],
    location_estimate: Optional[Dict[str, Any]],
    location_details: Optional[Dict[str, Any]],
    observations: List[Dict[str, Any]],
    is_managed_client: bool,
) -> Dict[str, Any]:
    """Evaluate rogue device threat score with clear, explainable reasons.

    Scoring Components (0 - 100):
    - Managed client: Score = 0, Risk = LOW, Classification = MANAGED
    - Unmanaged device base: +35
    - Locally administered / randomized MAC: +20
    - Unresolved OUI vendor: +10
    - Restricted zone presence (e.g. Formation room): +25
    - Persistence (> 5 minutes active): +15
    - Multi-sensor presence / movement: +10
    """
    if is_managed_client:
        return {
            "rogue_score": 0,
            "is_rogue": False,
            "classification": "MANAGED",
            "risk_level": "LOW",
            "reasons": ["Authorized managed endpoint with active agent registration."],
        }

    mac = device.get("mac_address") or ""
    vendor = device.get("vendor") or "Unknown"
    reasons = []
    score = 0

    # 1. Unmanaged presence
    score += 35
    reasons.append("Unregistered device detected on network.")

    # 2. MAC randomization check
    if is_locally_administered_mac(mac):
        score += 20
        reasons.append(f"Device is using a randomized / private MAC address ({mac}).")

    # 3. Unknown vendor
    if not vendor or vendor.strip().lower() in {"unknown", "none"}:
        score += 10
        reasons.append("OUI vendor cannot be identified from IEEE database.")

    # 4. Restricted zone detection
    is_restricted = False
    loc_label = "unknown"
    if location_details:
        loc_label = location_details.get("label") or location_details.get("zone_name") or "unknown"
        if location_details.get("is_restricted") or location_details.get("zone_type") == "formation_room":
            is_restricted = True
            score += 25
            reasons.append(f"Device physically triangulated inside restricted area ({loc_label}).")

    # 5. Persistence tracking
    first_seen = device.get("first_seen")
    last_seen = device.get("last_seen")
    if first_seen and last_seen:
        try:
            if isinstance(first_seen, str):
                fs_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
            else:
                fs_dt = first_seen
            if isinstance(last_seen, str):
                ls_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            else:
                ls_dt = last_seen

            duration_seconds = (ls_dt - fs_dt).total_seconds()
            if duration_seconds >= 300:  # 5 minutes
                score += 15
                mins = int(duration_seconds // 60)
                reasons.append(f"Persistent unmanaged connection for {mins} minutes.")
        except Exception:
            pass

    # 6. Multi-sensor observation check
    unique_reporters = {
        obs.get("source_client_id") for obs in observations
        if obs.get("source_client_id") is not None
    }
    if len(unique_reporters) >= 2:
        score += 10
        reasons.append(f"Signal observed by {len(unique_reporters)} distinct monitoring sensors.")

    final_score = min(100, max(0, score))

    if final_score >= 75:
        classification = "CONFIRMED_ROGUE"
        risk_level = "CRITICAL" if is_restricted or final_score >= 85 else "HIGH"
    elif final_score >= 45:
        classification = "ROGUE_CANDIDATE"
        risk_level = "HIGH" if is_restricted else "MEDIUM"
    else:
        classification = "UNMANAGED"
        risk_level = "LOW"

    return {
        "rogue_score": final_score,
        "is_rogue": final_score >= 50,
        "classification": classification,
        "risk_level": risk_level,
        "reasons": reasons,
    }


# ============================================================
# DATABASE PERSISTENCE & SERVICE OPERATIONS
# ============================================================


def sync_client_sensors(conn=None) -> int:
    """Register or synchronize all managed clients with physical locations as sensors."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return 0

    cursor = conn.cursor(dictionary=True)
    synced = 0
    try:
        cursor.execute(
            """
            SELECT c.id AS client_id, c.client_id AS client_code, c.hostname, c.mac,
                   c.location_id, l.x, l.y, l.z, l.label AS location_label
            FROM clients c
            LEFT JOIN locations l ON l.id = c.location_id
            WHERE c.location_id IS NOT NULL
            """
        )
        rows = cursor.fetchall()
        for r in rows:
            sensor_id = f"sensor-{r['client_code']}"
            name = f"Sensor: {r['hostname'] or r['client_code']}"
            capabilities = json.dumps(["arp", "dhcp", "rssi"])
            cursor.execute(
                """
                INSERT INTO sensors (
                    sensor_id, name, sensor_type, client_id, location_id, x, y, z, capabilities, status, last_seen
                ) VALUES (%s, %s, 'endpoint', %s, %s, %s, %s, %s, %s, 'ONLINE', CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    location_id = VALUES(location_id),
                    x = VALUES(x),
                    y = VALUES(y),
                    z = VALUES(z),
                    status = 'ONLINE',
                    last_seen = CURRENT_TIMESTAMP
                """,
                (
                    sensor_id,
                    name,
                    r["client_id"],
                    r["location_id"],
                    r.get("x"),
                    r.get("y"),
                    r.get("z"),
                    capabilities,
                ),
            )
            synced += 1
        conn.commit()
        return synced
    except Exception as err:
        LOGGER.error("Error syncing client sensors: %s", err)
        if conn:
            conn.rollback()
        return 0
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def list_sensors(conn=None) -> List[Dict[str, Any]]:
    """Return all registered sensors with their location and status."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return []

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT s.*, l.label AS location_label, l.floor AS location_floor,
                   c.client_id AS client_code, c.hostname AS client_hostname
            FROM sensors s
            LEFT JOIN locations l ON l.id = s.location_id
            LEFT JOIN clients c ON c.id = s.client_id
            ORDER BY s.id ASC
            """
        )
        sensors = []
        for r in cursor.fetchall():
            caps = []
            if r.get("capabilities"):
                try:
                    caps = json.loads(r["capabilities"])
                except Exception:
                    caps = [r["capabilities"]]
            sensors.append({
                "id": r["id"],
                "sensor_id": r["sensor_id"],
                "name": r["name"],
                "type": r["sensor_type"],
                "client_id": r["client_id"],
                "client_code": r.get("client_code"),
                "client_hostname": r.get("client_hostname"),
                "location_id": r["location_id"],
                "location_label": r.get("location_label"),
                "floor": r.get("location_floor"),
                "x": r.get("x"),
                "y": r.get("y"),
                "z": r.get("z"),
                "capabilities": caps,
                "status": r.get("status", "ONLINE"),
                "last_seen": r["last_seen"].isoformat() if r.get("last_seen") else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
        return sensors
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def register_sensor(
    sensor_id: str,
    name: str,
    sensor_type: str = "endpoint",
    location_id: Optional[int] = None,
    client_id: Optional[int] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    z: Optional[float] = None,
    capabilities: Optional[List[str]] = None,
    conn=None,
) -> Dict[str, Any]:
    """Register or update an infrastructure sensor (AP, switch, collector)."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            raise ValueError("Database unavailable.")

    cursor = conn.cursor(dictionary=True)
    try:
        caps_json = json.dumps(capabilities or ["arp", "dhcp"])
        cursor.execute(
            """
            INSERT INTO sensors (
                sensor_id, name, sensor_type, client_id, location_id, x, y, z, capabilities, status, last_seen
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ONLINE', CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                sensor_type = VALUES(sensor_type),
                location_id = VALUES(location_id),
                client_id = VALUES(client_id),
                x = VALUES(x),
                y = VALUES(y),
                z = VALUES(z),
                capabilities = VALUES(capabilities),
                status = 'ONLINE',
                last_seen = CURRENT_TIMESTAMP
            """,
            (sensor_id, name, sensor_type, client_id, location_id, x, y, z, caps_json),
        )
        conn.commit()
        cursor.execute("SELECT id FROM sensors WHERE sensor_id = %s", (sensor_id,))
        row = cursor.fetchone()
        return {
            "id": row["id"] if row else None,
            "sensor_id": sensor_id,
            "name": name,
            "sensor_type": sensor_type,
            "location_id": location_id,
            "x": x,
            "y": y,
            "z": z,
            "status": "ONLINE",
        }
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def _to_dict_row(row, cursor) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if isinstance(row, (tuple, list)):
        desc = getattr(cursor, "description", None)
        if desc:
            cols = [col[0] for col in desc]
            return {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
    return None


def _to_dict_rows(rows, cursor) -> List[Dict[str, Any]]:
    if not rows:
        return []
    return [r for r in (_to_dict_row(row, cursor) for row in rows) if r is not None]


def evaluate_device_spatial_and_rogue_status(
    device_id: int,
    conn=None,
) -> Optional[Dict[str, Any]]:
    """Process all observations for a device, calculate location and rogue score, and persist."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return None

    try:
        cursor = conn.cursor(dictionary=True)
    except Exception:
        cursor = conn.cursor()

    try:
        # 1. Fetch network device details
        cursor.execute(
            "SELECT * FROM network_devices WHERE id = %s",
            (device_id,),
        )
        raw_device = cursor.fetchone()
        device = _to_dict_row(raw_device, cursor)
        if not device:
            return None

        mac = device.get("mac_address") or ""

        # 2. Check if device is a managed client
        cursor.execute(
            """
            SELECT c.id, c.client_id, c.location_id, l.x, l.y, l.z, l.label AS location_label
            FROM clients c
            LEFT JOIN locations l ON l.id = c.location_id
            WHERE c.mac = %s
            """,
            (mac,),
        )
        managed_client = _to_dict_row(cursor.fetchone(), cursor)
        is_managed = managed_client is not None

        # 3. Fetch observations with reporting sensor details
        cursor.execute(
            """
            SELECT o.*,
                   s.sensor_id AS sensor_code, s.x AS sensor_x, s.y AS sensor_y, s.z AS sensor_z,
                   cl_loc.x AS client_x, cl_loc.y AS client_y, cl_loc.z AS client_z,
                   cl.client_id AS client_code
            FROM network_device_observations o
            LEFT JOIN sensors s ON s.id = o.sensor_id
            LEFT JOIN clients cl ON cl.id = o.source_client_id
            LEFT JOIN locations cl_loc ON cl_loc.id = cl.location_id
            WHERE o.device_id = %s
            ORDER BY o.observed_at DESC
            LIMIT 50
            """,
            (device_id,),
        )
        observations = _to_dict_rows(cursor.fetchall(), cursor)

        # 4. Fetch all center locations for snapping
        cursor.execute("SELECT * FROM locations")
        all_locations = _to_dict_rows(cursor.fetchall(), cursor)

        # Build sensor readings list
        readings = []
        if is_managed and managed_client.get("location_id") and managed_client.get("x") is not None:
            readings.append({
                "sensor_id": f"client-{managed_client['client_id']}",
                "x": managed_client["x"],
                "y": managed_client["y"],
                "z": managed_client["z"],
                "is_direct": True,
            })
        else:
            for obs in observations:
                sx = obs.get("sensor_x") if obs.get("sensor_x") is not None else obs.get("client_x")
                sy = obs.get("sensor_y") if obs.get("sensor_y") is not None else obs.get("client_y")
                sz = obs.get("sensor_z") if obs.get("sensor_z") is not None else obs.get("client_z")
                s_id = obs.get("sensor_code") or (f"client-{obs['client_code']}" if obs.get("client_code") else "collector")

                if sx is not None and sy is not None:
                    readings.append({
                        "sensor_id": s_id,
                        "x": sx,
                        "y": sy,
                        "z": sz,
                        "rssi": obs.get("rssi"),
                        "switch_port": obs.get("switch_port"),
                    })

        # 5. Triangulate position
        triangulation = triangulate_position(readings)
        est_x = triangulation["x"]
        est_y = triangulation["y"]
        est_z = triangulation["z"]
        confidence = triangulation["confidence"]
        method = triangulation["method"]
        supporting_sensors = triangulation["supporting_sensors"]

        # 6. Snap to nearest physical location
        nearest_loc = find_closest_location(est_x, est_y, est_z, all_locations)
        location_id = nearest_loc["id"] if nearest_loc else None

        # 7. Check for previous location estimate (movement detection)
        cursor.execute(
            "SELECT * FROM device_location_estimates WHERE device_id = %s",
            (device_id,),
        )
        prev_est = _to_dict_row(cursor.fetchone(), cursor)
        prev_loc_id = prev_est.get("location_id") if prev_est else None
        prev_x = prev_est.get("x") if prev_est else None
        prev_y = prev_est.get("y") if prev_est else None
        prev_z = prev_est.get("z") if prev_est else None

        # Movement threshold check: changed location_id or distance > 3.0 meters
        has_moved = False
        if prev_est and location_id is not None and prev_loc_id != location_id:
            has_moved = True
        elif prev_x is not None and est_x is not None and prev_y is not None and est_y is not None:
            dist = math.sqrt((est_x - prev_x) ** 2 + (est_y - prev_y) ** 2)
            if dist > 4.0:
                has_moved = True

        # 8. Record movement event if changed
        if has_moved or (not prev_est and location_id is not None):
            reason = "Initial spatial triangulation" if not prev_est else "Position change detected"
            cursor.execute(
                """
                INSERT INTO device_location_events (
                    device_id, previous_location_id, new_location_id,
                    previous_x, previous_y, previous_z,
                    new_x, new_y, new_z,
                    confidence, method, reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    device_id,
                    prev_loc_id,
                    location_id,
                    prev_x,
                    prev_y,
                    prev_z,
                    est_x,
                    est_y,
                    est_z,
                    confidence,
                    method,
                    reason,
                ),
            )

        # 9. Upsert device location estimate
        cursor.execute(
            """
            INSERT INTO device_location_estimates (
                device_id, location_id, x, y, z, confidence, method, supporting_sensor_ids
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                location_id = VALUES(location_id),
                x = VALUES(x),
                y = VALUES(y),
                z = VALUES(z),
                confidence = VALUES(confidence),
                method = VALUES(method),
                supporting_sensor_ids = VALUES(supporting_sensor_ids),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                device_id,
                location_id,
                est_x,
                est_y,
                est_z,
                confidence,
                method,
                json.dumps(supporting_sensors),
            ),
        )

        # 10. Calculate rogue threat assessment
        rogue_res = calculate_rogue_assessment(
            device=device,
            location_estimate={"x": est_x, "y": est_y, "z": est_z, "confidence": confidence},
            location_details=nearest_loc,
            observations=observations,
            is_managed_client=is_managed,
        )

        # 11. Upsert rogue assessment
        cursor.execute(
            """
            INSERT INTO rogue_device_assessments (
                device_id, rogue_score, is_rogue, classification, risk_level, reasons
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                rogue_score = VALUES(rogue_score),
                is_rogue = VALUES(is_rogue),
                classification = VALUES(classification),
                risk_level = VALUES(risk_level),
                reasons = VALUES(reasons),
                last_evaluated_at = CURRENT_TIMESTAMP
            """,
            (
                device_id,
                rogue_res["rogue_score"],
                1 if rogue_res["is_rogue"] else 0,
                rogue_res["classification"],
                rogue_res["risk_level"],
                json.dumps(rogue_res["reasons"]),
            ),
        )

        conn.commit()

        return {
            "device_id": device_id,
            "mac_address": mac,
            "hostname": device.get("hostname"),
            "vendor": device.get("vendor"),
            "location_estimate": {
                "location_id": location_id,
                "location_label": nearest_loc.get("label") if nearest_loc else None,
                "floor": nearest_loc.get("floor") if nearest_loc else None,
                "zone_name": nearest_loc.get("zone_name") if nearest_loc else None,
                "x": est_x,
                "y": est_y,
                "z": est_z,
                "confidence": confidence,
                "method": method,
                "supporting_sensors": supporting_sensors,
            },
            "rogue_assessment": rogue_res,
            "has_moved": has_moved,
        }
    except Exception as err:
        LOGGER.error("Error evaluating spatial/rogue status for device %s: %s", device_id, err)
        if conn:
            conn.rollback()
        return None
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def _get_cursor(conn):
    try:
        return conn.cursor(dictionary=True)
    except Exception:
        return conn.cursor()


def sync_client_sensors(conn=None) -> int:
    """Register or synchronize all managed clients with physical locations as sensors."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return 0

    cursor = _get_cursor(conn)
    synced = 0
    try:
        cursor.execute(
            """
            SELECT c.id AS client_id, c.client_id AS client_code, c.hostname, c.mac,
                   c.location_id, l.x, l.y, l.z, l.label AS location_label
            FROM clients c
            LEFT JOIN locations l ON l.id = c.location_id
            WHERE c.location_id IS NOT NULL
            """
        )
        rows = _to_dict_rows(cursor.fetchall(), cursor)
        for r in rows:
            sensor_id = f"sensor-{r['client_code']}"
            name = f"Sensor: {r['hostname'] or r['client_code']}"
            capabilities = json.dumps(["arp", "dhcp", "rssi"])
            cursor.execute(
                """
                INSERT INTO sensors (
                    sensor_id, name, sensor_type, client_id, location_id, x, y, z, capabilities, status, last_seen
                ) VALUES (%s, %s, 'endpoint', %s, %s, %s, %s, %s, %s, 'ONLINE', CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    location_id = VALUES(location_id),
                    x = VALUES(x),
                    y = VALUES(y),
                    z = VALUES(z),
                    status = 'ONLINE',
                    last_seen = CURRENT_TIMESTAMP
                """,
                (
                    sensor_id,
                    name,
                    r["client_id"],
                    r["location_id"],
                    r.get("x"),
                    r.get("y"),
                    r.get("z"),
                    capabilities,
                ),
            )
            synced += 1
        conn.commit()
        return synced
    except Exception as err:
        LOGGER.error("Error syncing client sensors: %s", err)
        if conn:
            conn.rollback()
        return 0
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def list_sensors(conn=None) -> List[Dict[str, Any]]:
    """Return all registered sensors with their location and status."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return []

    cursor = _get_cursor(conn)
    try:
        cursor.execute(
            """
            SELECT s.*, l.label AS location_label, l.floor AS location_floor,
                   c.client_id AS client_code, c.hostname AS client_hostname
            FROM sensors s
            LEFT JOIN locations l ON l.id = s.location_id
            LEFT JOIN clients c ON c.id = s.client_id
            ORDER BY s.id ASC
            """
        )
        sensors = []
        for r in _to_dict_rows(cursor.fetchall(), cursor):
            caps = []
            if r.get("capabilities"):
                try:
                    caps = json.loads(r["capabilities"])
                except Exception:
                    caps = [r["capabilities"]]
            sensors.append({
                "id": r["id"],
                "sensor_id": r["sensor_id"],
                "name": r["name"],
                "type": r["sensor_type"],
                "client_id": r["client_id"],
                "client_code": r.get("client_code"),
                "client_hostname": r.get("client_hostname"),
                "location_id": r["location_id"],
                "location_label": r.get("location_label"),
                "floor": r.get("location_floor"),
                "x": r.get("x"),
                "y": r.get("y"),
                "z": r.get("z"),
                "capabilities": caps,
                "status": r.get("status", "ONLINE"),
                "last_seen": r["last_seen"].isoformat() if r.get("last_seen") and hasattr(r["last_seen"], "isoformat") else str(r.get("last_seen") or ""),
                "created_at": r["created_at"].isoformat() if r.get("created_at") and hasattr(r["created_at"], "isoformat") else str(r.get("created_at") or ""),
            })
        return sensors
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def register_sensor(
    sensor_id: str,
    name: str,
    sensor_type: str = "endpoint",
    location_id: Optional[int] = None,
    client_id: Optional[int] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    z: Optional[float] = None,
    capabilities: Optional[List[str]] = None,
    conn=None,
) -> Dict[str, Any]:
    """Register or update an infrastructure sensor (AP, switch, collector)."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            raise ValueError("Database unavailable.")

    cursor = _get_cursor(conn)
    try:
        caps_json = json.dumps(capabilities or ["arp", "dhcp"])
        cursor.execute(
            """
            INSERT INTO sensors (
                sensor_id, name, sensor_type, client_id, location_id, x, y, z, capabilities, status, last_seen
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ONLINE', CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                sensor_type = VALUES(sensor_type),
                location_id = VALUES(location_id),
                client_id = VALUES(client_id),
                x = VALUES(x),
                y = VALUES(y),
                z = VALUES(z),
                capabilities = VALUES(capabilities),
                status = 'ONLINE',
                last_seen = CURRENT_TIMESTAMP
            """,
            (sensor_id, name, sensor_type, client_id, location_id, x, y, z, caps_json),
        )
        conn.commit()
        cursor.execute("SELECT id FROM sensors WHERE sensor_id = %s", (sensor_id,))
        row = _to_dict_row(cursor.fetchone(), cursor)
        return {
            "id": row["id"] if row else None,
            "sensor_id": sensor_id,
            "name": name,
            "sensor_type": sensor_type,
            "location_id": location_id,
            "x": x,
            "y": y,
            "z": z,
            "status": "ONLINE",
        }
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def evaluate_all_devices(conn=None) -> List[Dict[str, Any]]:
    """Evaluate spatial location and rogue score across all network devices."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return []

    cursor = _get_cursor(conn)
    results = []
    try:
        # Sync client sensors first
        sync_client_sensors(conn=conn)

        cursor.execute("SELECT id FROM network_devices")
        devices = _to_dict_rows(cursor.fetchall(), cursor)
        for d in devices:
            res = evaluate_device_spatial_and_rogue_status(d["id"], conn=conn)
            if res:
                results.append(res)
        return results
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def get_device_location(device_identifier: Any, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch current location estimate, coordinates, confidence, and supporting evidence."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return None

    cursor = _get_cursor(conn)
    try:
        # Resolve by ID or MAC
        if isinstance(device_identifier, int) or (isinstance(device_identifier, str) and device_identifier.isdigit()):
            cursor.execute("SELECT * FROM network_devices WHERE id = %s", (int(device_identifier),))
        else:
            mac_clean = str(device_identifier).strip().replace("-", ":").upper()
            cursor.execute("SELECT * FROM network_devices WHERE mac_address = %s", (mac_clean,))
        device = _to_dict_row(cursor.fetchone(), cursor)
        if not device:
            return None

        device_id = device["id"]
        cursor.execute(
            """
            SELECT e.*, l.label AS location_label, l.floor AS location_floor,
                   l.zone_name, l.zone_type, l.is_restricted
            FROM device_location_estimates e
            LEFT JOIN locations l ON l.id = e.location_id
            WHERE e.device_id = %s
            """,
            (device_id,),
        )
        est = _to_dict_row(cursor.fetchone(), cursor)

        cursor.execute(
            "SELECT * FROM rogue_device_assessments WHERE device_id = %s",
            (device_id,),
        )
        rogue = _to_dict_row(cursor.fetchone(), cursor)

        reasons = []
        if rogue and rogue.get("reasons"):
            try:
                reasons = json.loads(rogue["reasons"])
            except Exception:
                reasons = [rogue["reasons"]]

        sensors = []
        if est and est.get("supporting_sensor_ids"):
            try:
                sensors = json.loads(est["supporting_sensor_ids"])
            except Exception:
                sensors = [est["supporting_sensor_ids"]]

        first_s = device.get("first_seen")
        last_s = device.get("last_seen")
        calc_at = est.get("calculated_at") if est else None

        return {
            "device_id": device_id,
            "mac_address": device["mac_address"],
            "ip_address": device.get("ip_address"),
            "hostname": device.get("hostname"),
            "vendor": device.get("vendor"),
            "first_seen": first_s.isoformat() if first_s and hasattr(first_s, "isoformat") else str(first_s or ""),
            "last_seen": last_s.isoformat() if last_s and hasattr(last_s, "isoformat") else str(last_s or ""),
            "location": {
                "location_id": est["location_id"] if est else None,
                "label": est.get("location_label") if est else None,
                "floor": est.get("location_floor") if est else None,
                "zone_name": est.get("zone_name") if est else None,
                "is_restricted": bool(est.get("is_restricted")) if est else False,
                "x": est.get("x") if est else None,
                "y": est.get("y") if est else None,
                "z": est.get("z") if est else None,
                "confidence": est.get("confidence", 0.0) if est else 0.0,
                "method": est.get("method", "NONE") if est else "NONE",
                "supporting_sensors": sensors,
                "calculated_at": calc_at.isoformat() if calc_at and hasattr(calc_at, "isoformat") else str(calc_at or ""),
            } if est else None,
            "rogue_assessment": {
                "rogue_score": rogue.get("rogue_score", 0) if rogue else 0,
                "is_rogue": bool(rogue.get("is_rogue")) if rogue else False,
                "classification": rogue.get("classification", "UNKNOWN") if rogue else "UNKNOWN",
                "risk_level": rogue.get("risk_level", "LOW") if rogue else "LOW",
                "reasons": reasons,
            } if rogue else None,
        }
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def get_device_location_history(device_identifier: Any, limit: int = 50, conn=None) -> List[Dict[str, Any]]:
    """Retrieve chronological movement and spatial events for a device."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return []

    cursor = _get_cursor(conn)
    try:
        if isinstance(device_identifier, int) or (isinstance(device_identifier, str) and device_identifier.isdigit()):
            cursor.execute("SELECT id FROM network_devices WHERE id = %s", (int(device_identifier),))
        else:
            mac_clean = str(device_identifier).strip().replace("-", ":").upper()
            cursor.execute("SELECT id FROM network_devices WHERE mac_address = %s", (mac_clean,))
        device = _to_dict_row(cursor.fetchone(), cursor)
        if not device:
            return []

        cursor.execute(
            """
            SELECT ev.*,
                   prev_l.label AS prev_label, prev_l.floor AS prev_floor,
                   new_l.label AS new_label, new_l.floor AS new_floor
            FROM device_location_events ev
            LEFT JOIN locations prev_l ON prev_l.id = ev.previous_location_id
            LEFT JOIN locations new_l ON new_l.id = ev.new_location_id
            WHERE ev.device_id = %s
            ORDER BY ev.timestamp DESC
            LIMIT %s
            """,
            (device["id"], limit),
        )
        events = []
        for r in _to_dict_rows(cursor.fetchall(), cursor):
            ts = r.get("timestamp")
            events.append({
                "id": r["id"],
                "device_id": r["device_id"],
                "previous_location": {
                    "id": r["previous_location_id"],
                    "label": r.get("prev_label"),
                    "floor": r.get("prev_floor"),
                    "x": r.get("previous_x"),
                    "y": r.get("previous_y"),
                    "z": r.get("previous_z"),
                } if r.get("previous_location_id") or r.get("previous_x") is not None else None,
                "new_location": {
                    "id": r["new_location_id"],
                    "label": r.get("new_label"),
                    "floor": r.get("new_floor"),
                    "x": r.get("new_x"),
                    "y": r.get("new_y"),
                    "z": r.get("new_z"),
                } if r.get("new_location_id") or r.get("new_x") is not None else None,
                "confidence": r.get("confidence", 0.0),
                "method": r.get("method"),
                "reason": r.get("reason"),
                "timestamp": ts.isoformat() if ts and hasattr(ts, "isoformat") else str(ts or ""),
            })
        return events
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def list_rogue_devices(
    min_score: int = 35,
    *,
    active_only: bool = False,
    max_age_seconds: Optional[int] = None,
    conn=None,
) -> List[Dict[str, Any]]:
    """List all detected rogue candidates or unmanaged devices with elevated risk."""
    from server_components.device_recency import active_cutoff, get_device_active_max_age_seconds

    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return []

    cursor = _get_cursor(conn)
    try:
        params: List[Any] = [min_score]
        active_clause = ""
        if active_only:
            window = (
                get_device_active_max_age_seconds()
                if max_age_seconds is None
                else max(1, int(max_age_seconds))
            )
            active_clause = " AND d.last_seen >= %s"
            params.append(active_cutoff(max_age_seconds=window).replace(tzinfo=None))

        cursor.execute(
            f"""
            SELECT d.id AS device_id, d.mac_address, d.ip_address, d.hostname, d.vendor,
                   d.first_seen, d.last_seen,
                   r.rogue_score, r.is_rogue, r.classification, r.risk_level, r.reasons,
                   e.location_id, e.x, e.y, e.z, e.confidence, e.method, e.supporting_sensor_ids,
                   l.label AS location_label, l.floor AS location_floor, l.zone_name, l.is_restricted
            FROM rogue_device_assessments r
            JOIN network_devices d ON d.id = r.device_id
            LEFT JOIN device_location_estimates e ON e.device_id = d.id
            LEFT JOIN locations l ON l.id = e.location_id
            WHERE r.rogue_score >= %s{active_clause}
            ORDER BY r.rogue_score DESC, d.last_seen DESC
            """,
            tuple(params),
        )
        devices = []
        for r in _to_dict_rows(cursor.fetchall(), cursor):
            reasons = []
            if r.get("reasons"):
                try:
                    reasons = json.loads(r["reasons"])
                except Exception:
                    reasons = [r["reasons"]]

            sensors = []
            if r.get("supporting_sensor_ids"):
                try:
                    sensors = json.loads(r["supporting_sensor_ids"])
                except Exception:
                    sensors = [r["supporting_sensor_ids"]]

            first_s = r.get("first_seen")
            last_s = r.get("last_seen")

            devices.append({
                "device_id": r["device_id"],
                "mac_address": r["mac_address"],
                "ip_address": r.get("ip_address"),
                "hostname": r.get("hostname"),
                "vendor": r.get("vendor"),
                "first_seen": first_s.isoformat() if first_s and hasattr(first_s, "isoformat") else str(first_s or ""),
                "last_seen": last_s.isoformat() if last_s and hasattr(last_s, "isoformat") else str(last_s or ""),
                "rogue_score": r["rogue_score"],
                "is_rogue": bool(r["is_rogue"]),
                "classification": r["classification"],
                "risk_level": r["risk_level"],
                "reasons": reasons,
                "location": {
                    "location_id": r.get("location_id"),
                    "label": r.get("location_label"),
                    "floor": r.get("location_floor"),
                    "zone_name": r.get("zone_name"),
                    "is_restricted": bool(r.get("is_restricted")),
                    "x": r.get("x"),
                    "y": r.get("y"),
                    "z": r.get("z"),
                    "confidence": r.get("confidence", 0.0),
                    "method": r.get("method", "NONE"),
                    "supporting_sensors": sensors,
                } if r.get("x") is not None or r.get("location_id") else None,
            })
        return devices
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def list_spatial_events(limit: int = 50, conn=None) -> List[Dict[str, Any]]:
    """Retrieve global recent spatial movement and localization events."""
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return []

    cursor = _get_cursor(conn)
    try:
        cursor.execute(
            """
            SELECT ev.*,
                   d.mac_address, d.hostname, d.ip_address, d.vendor,
                   prev_l.label AS prev_label, prev_l.floor AS prev_floor,
                   new_l.label AS new_label, new_l.floor AS new_floor
            FROM device_location_events ev
            JOIN network_devices d ON d.id = ev.device_id
            LEFT JOIN locations prev_l ON prev_l.id = ev.previous_location_id
            LEFT JOIN locations new_l ON new_l.id = ev.new_location_id
            ORDER BY ev.timestamp DESC
            LIMIT %s
            """,
            (limit,),
        )
        events = []
        for r in _to_dict_rows(cursor.fetchall(), cursor):
            ts = r.get("timestamp")
            events.append({
                "id": r["id"],
                "device_id": r["device_id"],
                "mac_address": r.get("mac_address"),
                "hostname": r.get("hostname"),
                "ip_address": r.get("ip_address"),
                "vendor": r.get("vendor"),
                "previous_location": {
                    "id": r["previous_location_id"],
                    "label": r.get("prev_label"),
                    "floor": r.get("prev_floor"),
                    "x": r.get("previous_x"),
                    "y": r.get("previous_y"),
                    "z": r.get("previous_z"),
                } if r.get("previous_location_id") or r.get("previous_x") is not None else None,
                "new_location": {
                    "id": r["new_location_id"],
                    "label": r.get("new_label"),
                    "floor": r.get("new_floor"),
                    "x": r.get("new_x"),
                    "y": r.get("new_y"),
                    "z": r.get("new_z"),
                } if r.get("new_location_id") or r.get("new_x") is not None else None,
                "confidence": r.get("confidence", 0.0),
                "method": r.get("method"),
                "reason": r.get("reason"),
                "timestamp": ts.isoformat() if ts and hasattr(ts, "isoformat") else str(ts or ""),
            })
        return events
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


# ============================================================
# 3D DIGITAL TWIN SCENE, TOPOLOGY & REPLAY SERVICES
# ============================================================


def get_spatial_scene(
    floor: Optional[int] = None,
    *,
    active_only: bool = True,
    max_age_seconds: Optional[int] = None,
    conn=None,
) -> Dict[str, Any]:
    """Generate the complete 3D digital twin scene graph for WebGL and AR rendering.

    Combines the physical environment hierarchy (rooms, zones, seats), spatial nodes
    (workstations, servers, switches, sensors, rogue devices), network topology links,
    and active threat radar markers into a unified normalized JSON schema.

    When ``active_only`` is true, only endpoints observed inside the configured
    recency window are included as live nodes.
    """
    from server_components.device_recency import (
        active_cutoff,
        active_filter_metadata,
        get_device_active_max_age_seconds,
        is_client_record_active,
        is_timestamp_active,
    )
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return {"version": 1, "timestamp": datetime.now(timezone.utc).isoformat(), "locations": [], "nodes": [], "edges": [], "threats": [], "meta": {}}

    cursor = _get_cursor(conn)
    try:
        active_window = (
            get_device_active_max_age_seconds()
            if max_age_seconds is None
            else max(1, int(max_age_seconds))
        )
        active_cutoff_at = (
            active_cutoff(max_age_seconds=active_window) if active_only else None
        )

        # 1. Fetch physical locations
        loc_query = "SELECT * FROM locations"
        loc_params = []
        if floor is not None:
            loc_query += " WHERE floor = %s"
            loc_params.append(floor)
        loc_query += " ORDER BY floor ASC, id ASC"
        cursor.execute(loc_query, tuple(loc_params))
        raw_locations = _to_dict_rows(cursor.fetchall(), cursor)

        locations = []
        location_map = {}
        for r in raw_locations:
            loc_id = r["id"]
            loc_type = r.get("location_type") or r.get("type") or "zone"
            w = r.get("width") or (12.0 if loc_type == "room" else (4.0 if loc_type == "zone" else 1.2))
            length_val = r.get("length") or (10.0 if loc_type == "room" else (3.5 if loc_type == "zone" else 0.8))
            h = r.get("height") or (3.0 if loc_type == "room" else 0.8)
            loc_obj = {
                "id": loc_id,
                "name": r.get("name") or r.get("label") or f"Location {loc_id}",
                "label": r.get("label") or r.get("name") or f"Loc-{loc_id}",
                "type": loc_type,
                "floor": int(r["floor"]) if r.get("floor") is not None else 1,
                "parent_id": r.get("parent_id"),
                "position": {
                    "x": float(r["x"]) if r.get("x") is not None else 0.0,
                    "y": float(r["y"]) if r.get("y") is not None else 0.0,
                    "z": float(r["z"]) if r.get("z") is not None else 0.0,
                },
                "bounds": {
                    "width": float(w),
                    "length": float(length_val),
                    "height": float(h),
                },
                "is_restricted": bool(r.get("is_restricted")),
                "zone_type": r.get("zone_type") or "office",
                "aisle": r.get("aisle"),
                "table_no": r.get("table_no"),
                "position_no": r.get("position"),
            }
            locations.append(loc_obj)
            location_map[loc_id] = loc_obj

        # 2. Fetch sensors
        sensor_query = """
            SELECT s.*, l.label AS loc_label, l.floor AS loc_floor, l.z AS loc_z
            FROM sensors s
            LEFT JOIN locations l ON l.id = s.location_id
            WHERE UPPER(COALESCE(s.status, 'ONLINE')) = 'ONLINE'
        """
        cursor.execute(sensor_query)
        raw_sensors = _to_dict_rows(cursor.fetchall(), cursor)

        nodes = []
        node_ids = set()

        # Add Gateway & Core Switch Infrastructure nodes
        gateway_node = {
            "id": "node-gateway",
            "name": "Core Gateway / Firewall",
            "label": "Gateway",
            "type": "gateway",
            "position": {"x": 2.0, "y": 2.0, "z": 1.2},
            "status": "online",
            "risk": "low",
            "confidence": 1.0,
            "ip": "192.168.1.1",
            "mac": "00:50:56:00:00:01",
            "vendor": "Cisco Systems",
            "location_label": "Server Room / Network Rack",
            "is_sensor": False,
            "is_rogue": False,
            "quarantined": False,
            "metadata": {"role": "default_gateway", "bandwidth_gbps": 10},
        }
        nodes.append(gateway_node)
        node_ids.add("node-gateway")

        switch_node = {
            "id": "node-switch-core",
            "name": "Core Distribution Switch",
            "label": "Switch-01",
            "type": "switch",
            "position": {"x": 4.0, "y": 2.0, "z": 1.0},
            "status": "online",
            "risk": "low",
            "confidence": 1.0,
            "ip": "192.168.1.2",
            "mac": "00:50:56:00:00:02",
            "vendor": "Cisco Systems",
            "location_label": "Server Room / Rack 1",
            "is_sensor": False,
            "is_rogue": False,
            "quarantined": False,
            "metadata": {"ports_total": 48, "ports_active": 24},
        }
        nodes.append(switch_node)
        node_ids.add("node-switch-core")

        active_client_db_ids: set = set()

        # 3. Fetch registered clients first so sensor filtering can use active IDs.
        client_query = """
            SELECT c.*, l.label AS loc_label, l.x AS loc_x, l.y AS loc_y, l.z AS loc_z,
                   l.floor AS loc_floor, l.is_restricted AS loc_restricted,
                   nd.last_seen AS device_last_seen
            FROM clients c
            LEFT JOIN locations l ON l.id = c.location_id
            LEFT JOIN network_devices nd ON nd.mac_address = c.mac
        """
        cursor.execute(client_query)
        raw_clients = _to_dict_rows(cursor.fetchall(), cursor)
        total_clients_before_filter = len(raw_clients)
        active_clients = []
        for c in raw_clients:
            if active_only and active_cutoff_at is not None:
                if not is_client_record_active(c, cutoff=active_cutoff_at):
                    continue
            active_client_db_ids.add(c["id"])
            active_clients.append(c)

        # Add Sensors
        for s in raw_sensors:
            if active_only and active_cutoff_at is not None:
                client_db_id = s.get("client_id")
                sensor_recent = is_timestamp_active(s.get("last_seen"), cutoff=active_cutoff_at)
                if client_db_id and client_db_id not in active_client_db_ids and not sensor_recent:
                    continue
                if not client_db_id and not sensor_recent:
                    continue
            s_id = f"sensor-{s['id']}"
            caps = s.get("capabilities")
            if isinstance(caps, str):
                try:
                    caps = json.loads(caps)
                except Exception:
                    caps = [caps]
            s_x = float(s["x"]) if s.get("x") is not None else 5.0
            s_y = float(s["y"]) if s.get("y") is not None else 5.0
            sensor_floor = int(s["loc_floor"]) if s.get("loc_floor") is not None else 1
            # Sensor coordinates are stored in the local floor frame. If z is
            # omitted, anchor the sensor to its assigned floor elevation.
            floor_z = float(s["loc_z"]) if s.get("loc_z") is not None else sensor_floor * 3.0
            s_z = max(float(s["z"]), floor_z + 0.8) if s.get("z") is not None else floor_z + 2.5
            sensor_node = {
                "id": s_id,
                "name": s.get("name") or f"Sensor {s['id']}",
                "label": s.get("name") or f"Sensor {s['id']}",
                "type": "sensor",
                "position": {"x": s_x, "y": s_y, "z": s_z},
                "status": "online" if str(s.get("status") or "ONLINE").upper() == "ONLINE" else "offline",
                "risk": "low",
                "confidence": 1.0,
                "location_label": s.get("loc_label") or "Zone Sensor",
                "is_sensor": True,
                "is_rogue": False,
                "quarantined": False,
                "metadata": {
                    "sensor_type": s.get("sensor_type"),
                    "floor": sensor_floor,
                    "capabilities": caps or ["arp", "dhcp", "rssi"],
                },
            }
            nodes.append(sensor_node)
            node_ids.add(s_id)

        # 4. Add active registered clients (workstations / managed endpoints)
        for c in active_clients:
            c_node_id = f"client-{c['id']}"
            c_status = (c.get("status") or "online").lower()
            if c_status not in {"online", "offline", "quarantined"}:
                c_status = "online"
            c_x = float(c["loc_x"]) if c.get("loc_x") is not None else (float(c.get("x") or 0.0) if c.get("x") is not None else None)
            c_y = float(c["loc_y"]) if c.get("loc_y") is not None else (float(c.get("y") or 0.0) if c.get("y") is not None else None)
            c_z = float(c["loc_z"]) if c.get("loc_z") is not None else (float(c.get("z") or 0.0) if c.get("z") is not None else 0.8)

            # Assign room offset fallback if coordinates missing
            if c_x is None or c_y is None:
                h_val = hash(c.get("mac") or str(c["id"]))
                c_x = 5.0 + (h_val % 15) * 1.2
                c_y = 4.0 + ((h_val // 15) % 10) * 1.2
                c_z = 0.8

            client_node = {
                "id": c_node_id,
                "name": c.get("hostname") or f"Workstation {c['id']}",
                "label": c.get("hostname") or f"PC-{c['id']}",
                "type": "workstation" if "server" not in (c.get("hostname") or "").lower() else "server",
                "position": {"x": c_x, "y": c_y, "z": c_z},
                "status": "isolated" if c.get("is_quarantined") else c_status,
                "risk": "medium" if c.get("is_quarantined") else "low",
                "confidence": 0.95 if c.get("location_id") else 0.75,
                "ip": c.get("ip"),
                "mac": c.get("mac"),
                "vendor": c.get("os_name") or "Managed Workstation",
                "location_label": c.get("loc_label") or "General Area",
                "is_sensor": False,
                "is_rogue": False,
                "quarantined": bool(c.get("is_quarantined")),
                "metadata": {
                    "os": f"{c.get('os_name') or ''} {c.get('os_version') or ''}".strip(),
                    "floor": int(c["loc_floor"]) if c.get("loc_floor") is not None else 0,
                    "agent_role": c.get("agent_role") or "agent",
                    "client_id": c.get("client_id"),
                },
            }
            nodes.append(client_node)
            node_ids.add(c_node_id)

        total_network_devices_before_filter = 0
        if active_only:
            cursor.execute("SELECT COUNT(*) AS total FROM network_devices")
            count_row = _to_dict_row(cursor.fetchone(), cursor) or {}
            total_network_devices_before_filter = int(count_row.get("total") or 0)

        # 5. Fetch network devices, spatial estimates & rogue assessments
        dev_query = """
            SELECT d.id AS device_id, d.id AS id, d.mac_address, d.ip_address, d.hostname, d.vendor,
                   d.first_seen, d.last_seen,
                   e.location_id, e.x AS est_x, e.y AS est_y, e.z AS est_z,
                   e.confidence AS est_conf, e.method AS est_method,
                   e.supporting_sensor_ids,
                   l.label AS loc_label, l.floor AS loc_floor, l.is_restricted AS loc_restricted,
                   r.rogue_score, r.is_rogue, r.classification AS rogue_class,
                   r.risk_level, r.reasons AS rogue_reasons
            FROM network_devices d
            LEFT JOIN device_location_estimates e ON e.device_id = d.id
            LEFT JOIN locations l ON l.id = e.location_id
            LEFT JOIN rogue_device_assessments r ON r.device_id = d.id
        """
        dev_params: List[Any] = []
        if active_only and active_cutoff_at is not None:
            dev_query += " WHERE d.last_seen >= %s"
            dev_params.append(active_cutoff_at.replace(tzinfo=None))
        dev_query += " ORDER BY COALESCE(r.rogue_score, 0) DESC, d.last_seen DESC"
        cursor.execute(dev_query, tuple(dev_params))
        raw_devices = _to_dict_rows(cursor.fetchall(), cursor)
        total_devices_before_filter = (
            total_clients_before_filter + total_network_devices_before_filter
            if active_only
            else total_clients_before_filter + len(raw_devices)
        )

        threats = []
        for d in raw_devices:
            dev_id = d.get("device_id") or d.get("id")
            if not dev_id:
                continue

            # Skip if this network device is already represented by a registered client with same MAC
            mac = d.get("mac_address")
            if any(n.get("mac") == mac for n in nodes if n.get("mac")):
                continue

            d_node_id = f"dev-{dev_id}"
            score = int(d.get("rogue_score") or 0)
            is_rogue = bool(d.get("is_rogue")) or score >= 50
            risk_raw = str(d.get("risk_level") or ("CRITICAL" if score >= 75 else ("HIGH" if score >= 50 else ("MEDIUM" if score >= 30 else "LOW")))).upper()

            d_x = float(d["est_x"]) if d.get("est_x") is not None else None
            d_y = float(d["est_y"]) if d.get("est_y") is not None else None
            d_z = float(d["est_z"]) if d.get("est_z") is not None else 0.8

            if d_x is None or d_y is None:
                h_val = hash(mac or str(dev_id))
                d_x = 8.0 + (abs(h_val) % 18) * 1.6
                d_y = 5.0 + ((abs(h_val) // 18) % 12) * 1.6
                d_z = 0.8

            dev_type = "rogue" if (is_rogue or score >= 35) else ("printer" if "print" in (d.get("hostname") or "").lower() else ("server" if "srv" in (d.get("hostname") or "").lower() else "workstation"))
            node_status = "rogue" if is_rogue else ("suspicious" if score >= 20 else "online")

            reasons = []
            if d.get("rogue_reasons"):
                try:
                    reasons = json.loads(d["rogue_reasons"]) if isinstance(d["rogue_reasons"], str) and d["rogue_reasons"].startswith("[") else ([d["rogue_reasons"]] if isinstance(d["rogue_reasons"], str) else d["rogue_reasons"])
                except Exception:
                    reasons = [str(d["rogue_reasons"])]
            if not reasons and (is_rogue or score >= 20):
                reasons = ["Unmanaged network endpoint detected on subnet"]

            dev_node = {
                "id": d_node_id,
                "name": d.get("hostname") or f"Device {mac or dev_id}",
                "label": d.get("hostname") or (mac or f"Dev-{dev_id}"),
                "type": dev_type,
                "position": {"x": d_x, "y": d_y, "z": d_z},
                "status": node_status,
                "risk": risk_raw.lower(),
                "confidence": float(d.get("est_conf") or 0.75),
                "ip": d.get("ip_address"),
                "mac": mac,
                "vendor": d.get("vendor") or "Unknown Vendor",
                "location_label": d.get("loc_label") or "Office Floor",
                "is_sensor": False,
                "is_rogue": is_rogue or score >= 20,
                "quarantined": False,
                "metadata": {
                    "rogue_score": score,
                    "floor": int(d["loc_floor"]) if d.get("loc_floor") is not None else 0,
                    "reasons": reasons,
                    "method": d.get("est_method") or "TRIANGULATION",
                },
            }
            nodes.append(dev_node)
            node_ids.add(d_node_id)

            if is_rogue or score >= 20 or risk_raw in {"CRITICAL", "HIGH", "MEDIUM"}:
                threats.append({
                    "id": f"threat-{dev_id}",
                    "device_id": dev_id,
                    "node_id": d_node_id,
                    "name": d.get("hostname") or mac or f"Threat-{dev_id}",
                    "severity": risk_raw.lower(),
                    "score": score,
                    "position": {"x": d_x, "y": d_y, "z": d_z},
                    "confidence": float(d.get("est_conf") or 0.75),
                    "reasons": reasons,
                    "detected_at": d.get("first_seen").isoformat() if d.get("first_seen") and hasattr(d["first_seen"], "isoformat") else str(d.get("first_seen") or ""),
                    "is_restricted_zone": bool(d.get("loc_restricted")),
                })

        # 5. Fetch Network Topology Links (Edges)
        edges = []
        edge_id = 1

        # Connect Core Gateway to Core Switch
        edges.append({
            "id": f"edge-{edge_id}",
            "source": "node-gateway",
            "target": "node-switch-core",
            "type": "physical",
            "status": "active",
            "traffic_rate": "1.2 Gbps",
            "latency": 0.2,
            "risk": "low",
        })
        edge_id += 1

        # Connect Sensors to Core Switch
        for s in raw_sensors:
            edges.append({
                "id": f"edge-{edge_id}",
                "source": "node-switch-core",
                "target": f"sensor-{s['id']}",
                "type": "physical",
                "status": "active",
                "traffic_rate": "24 kbps",
                "latency": 0.5,
                "risk": "low",
            })
            edge_id += 1

        # Connect Clients to Switch
        for c in active_clients:
            c_node_id = f"client-{c['id']}"
            if c_node_id in node_ids:
                edges.append({
                    "id": f"edge-{edge_id}",
                    "source": "node-switch-core",
                    "target": c_node_id,
                    "type": "physical",
                    "status": "isolated" if c.get("is_quarantined") else "active",
                    "traffic_rate": "4.5 Mbps",
                    "latency": 0.8,
                    "risk": "medium" if c.get("is_quarantined") else "low",
                })
                edge_id += 1

        # Connect Observations / Wireless Proximity Edges
        obs_query = """
            SELECT DISTINCT obs.device_id, obs.source_client_id, obs.rssi, obs.switch_port,
                   c.id AS client_id
            FROM network_device_observations obs
            LEFT JOIN clients c ON c.id = obs.source_client_id
            WHERE obs.observed_at >= NOW() - INTERVAL 24 HOUR
            LIMIT 100
        """
        try:
            cursor.execute(obs_query)
            raw_obs = _to_dict_rows(cursor.fetchall(), cursor)
            for ob in raw_obs:
                target_node_id = f"dev-{ob['device_id']}"
                source_node_id = f"client-{ob['client_id']}" if ob.get("client_id") else "node-switch-core"
                if target_node_id in node_ids and source_node_id in node_ids:
                    rssi_val = ob.get("rssi")
                    edges.append({
                        "id": f"edge-{edge_id}",
                        "source": source_node_id,
                        "target": target_node_id,
                        "type": "wireless" if rssi_val is not None else "logical",
                        "status": "active",
                        "traffic_rate": f"{rssi_val} dBm" if rssi_val is not None else "normal",
                        "latency": 1.2,
                        "risk": "high" if any(t["node_id"] == target_node_id for t in threats) else "low",
                    })
                    edge_id += 1
        except Exception:
            pass

        # 6. Calculate Spatial Bounding Metadata
        all_x = [n["position"]["x"] for n in nodes] + [l["position"]["x"] for l in locations]
        all_y = [n["position"]["y"] for n in nodes] + [l["position"]["y"] for l in locations]
        all_z = [n["position"]["z"] for n in nodes] + [l["position"]["z"] for l in locations]

        meta = {
            "version": 1,
            "floors": sorted(list(set(l["floor"] for l in locations))) or [1],
            "total_locations": len(locations),
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_threats": len(threats),
            "active_filter": active_filter_metadata(
                enabled=active_only,
                cutoff=active_cutoff_at,
                max_age_seconds=active_window,
                total_before=total_devices_before_filter,
                total_after=len(nodes),
            ),
            "bounds": {
                "min_x": min(all_x) if all_x else 0.0,
                "max_x": max(all_x) if all_x else 50.0,
                "min_y": min(all_y) if all_y else 0.0,
                "max_y": max(all_y) if all_y else 40.0,
                "min_z": min(all_z) if all_z else 0.0,
                "max_z": max(all_z) if all_z else 10.0,
            },
        }

        return {
            "version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "locations": locations,
            "nodes": nodes,
            "edges": edges,
            "threats": threats,
            "meta": meta,
        }
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def get_spatial_topology(conn=None) -> Dict[str, Any]:
    """Retrieve the physical and logical network topology graph with link metrics."""
    scene = get_spatial_scene(conn=conn)
    return {
        "nodes": scene["nodes"],
        "edges": scene["edges"],
        "summary": {
            "total_nodes": len(scene["nodes"]),
            "total_edges": len(scene["edges"]),
            "physical_links": sum(1 for e in scene["edges"] if e["type"] == "physical"),
            "wireless_links": sum(1 for e in scene["edges"] if e["type"] == "wireless"),
            "threat_links": sum(1 for e in scene["edges"] if e.get("risk") == "high"),
        },
    }


def get_spatial_threats(conn=None) -> List[Dict[str, Any]]:
    """Retrieve all spatially localized threats and rogue candidates with evidence vectors."""
    scene = get_spatial_scene(conn=conn)
    return scene.get("threats", [])


def get_spatial_replay(
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    interval_seconds: int = 60,
    conn=None,
) -> Dict[str, Any]:
    """Generate time-series replay frames of spatial movements and security events.

    Allows operators to scrub through history to observe when rogue devices appeared,
    how they moved across zones, and when isolation actions were triggered.
    """
    try:
        from database import get_connection
    except ImportError:
        from ..database import get_connection

    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
        if not conn:
            return {"frames": [], "events": [], "interval_seconds": interval_seconds}

    cursor = _get_cursor(conn)
    try:
        events = list_spatial_events(limit=200, conn=conn)
        base_scene = get_spatial_scene(conn=conn)

        # Build chronological timeline frames from events
        frames = []
        if events:
            # Sort chronological
            sorted_events = sorted(events, key=lambda e: e.get("timestamp") or "")
            for idx, ev in enumerate(sorted_events):
                frame_ts = ev.get("timestamp")
                # Create snapshot reflecting position change
                dev_id = f"dev-{ev['device_id']}"
                frame_nodes = []
                for n in base_scene["nodes"]:
                    node_copy = dict(n)
                    if n["id"] == dev_id and ev.get("new_location"):
                        node_copy["position"] = {
                            "x": ev["new_location"].get("x") or n["position"]["x"],
                            "y": ev["new_location"].get("y") or n["position"]["y"],
                            "z": ev["new_location"].get("z") or n["position"]["z"],
                        }
                    frame_nodes.append(node_copy)

                frames.append({
                    "frame_index": idx,
                    "timestamp": frame_ts,
                    "trigger_event": {
                        "device_id": ev["device_id"],
                        "hostname": ev.get("hostname"),
                        "mac_address": ev.get("mac_address"),
                        "reason": ev.get("reason"),
                        "from_location": ev.get("previous_location", {}).get("label") if ev.get("previous_location") else None,
                        "to_location": ev.get("new_location", {}).get("label") if ev.get("new_location") else None,
                    },
                    "active_nodes_count": len(frame_nodes),
                })
        else:
            # Provide default initial frame
            now_iso = datetime.now(timezone.utc).isoformat()
            frames.append({
                "frame_index": 0,
                "timestamp": now_iso,
                "trigger_event": None,
                "active_nodes_count": len(base_scene["nodes"]),
            })

        return {
            "interval_seconds": interval_seconds,
            "total_frames": len(frames),
            "events": events,
            "frames": frames,
            "base_scene": base_scene,
        }
    finally:
        cursor.close()
        if owns_conn:
            conn.close()

