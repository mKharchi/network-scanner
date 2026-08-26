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


def list_rogue_devices(min_score: int = 35, conn=None) -> List[Dict[str, Any]]:
    """List all detected rogue candidates or unmanaged devices with elevated risk."""
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
            SELECT d.id AS device_id, d.mac_address, d.ip_address, d.hostname, d.vendor,
                   d.first_seen, d.last_seen,
                   r.rogue_score, r.is_rogue, r.classification, r.risk_level, r.reasons,
                   e.location_id, e.x, e.y, e.z, e.confidence, e.method, e.supporting_sensor_ids,
                   l.label AS location_label, l.floor AS location_floor, l.zone_name, l.is_restricted
            FROM rogue_device_assessments r
            JOIN network_devices d ON d.id = r.device_id
            LEFT JOIN device_location_estimates e ON e.device_id = d.id
            LEFT JOIN locations l ON l.id = e.location_id
            WHERE r.rogue_score >= %s
            ORDER BY r.rogue_score DESC, d.last_seen DESC
            """,
            (min_score,),
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
