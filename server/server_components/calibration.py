"""Calibration comparisons between automatic estimates and confirmed positions."""

from __future__ import annotations

import math
from statistics import fmean
from typing import Any, Dict, Iterable, List, Optional


def _number(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def extract_estimated_coordinates(evidence: Any) -> Optional[Dict[str, float]]:
    """Extract coordinates stored by the localization engine in assignment evidence."""
    if isinstance(evidence, str):
        import json

        try:
            evidence = json.loads(evidence)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(evidence, dict):
        return None
    coordinates = evidence.get("calculated_coordinates") or evidence.get("coordinates")
    if not isinstance(coordinates, dict):
        return None
    values = {axis: _number(coordinates.get(axis)) for axis in ("x", "y", "z")}
    if values["x"] is None or values["y"] is None:
        return None
    return {axis: float(value or 0.0) for axis, value in values.items()}


def compare_calibration_record(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compare an estimated coordinate with the confirmed physical location."""
    estimated = extract_estimated_coordinates(record.get("evidence"))
    actual = {
        axis: _number(record.get(f"actual_{axis}", record.get(axis)))
        for axis in ("x", "y", "z")
    }
    if estimated is None or actual["x"] is None or actual["y"] is None:
        return None
    actual_coords = {axis: float(value or 0.0) for axis, value in actual.items()}
    delta = {axis: actual_coords[axis] - estimated[axis] for axis in ("x", "y", "z")}
    return {
        "client_id": record.get("client_id"),
        "hostname": record.get("hostname"),
        "history_id": record.get("history_id", record.get("id")),
        "location_id": record.get("location_id"),
        "location_label": record.get("location_label", record.get("label")),
        "assignment_method": record.get("assignment_method"),
        "assignment_status": record.get("assignment_status"),
        "verified": bool(record.get("verified")),
        "assigned_at": record.get("assigned_at"),
        "estimated": estimated,
        "actual": actual_coords,
        "error": {
            "dx": delta["x"],
            "dy": delta["y"],
            "dz": delta["z"],
            "distance": math.sqrt(sum(value * value for value in delta.values())),
        },
    }


def build_calibration_report(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    comparisons = [item for record in records if (item := compare_calibration_record(record))]
    if comparisons:
        mean_error = {
            axis: fmean(item["error"][f"d{axis}"] for item in comparisons)
            for axis in ("x", "y", "z")
        }
        mean_distance = fmean(item["error"]["distance"] for item in comparisons)
    else:
        mean_error = {axis: 0.0 for axis in ("x", "y", "z")}
        mean_distance = 0.0
    systematic = any(abs(value) >= 0.5 for value in mean_error.values())
    return {
        "sample_count": len(comparisons),
        "comparisons": comparisons,
        "summary": {
            "mean_error": mean_error,
            "mean_distance": mean_distance,
            "systematic_transformation_signal": systematic,
            "interpretation": (
                "Consistent axis offset detected; validate coordinate transformation."
                if systematic
                else "No systematic axis offset detected in the available samples."
            ),
        },
    }
