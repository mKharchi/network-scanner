"""Database storage repository for Device Classifications and Human Labels."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from database import get_connection
except ImportError:
    from ..database import get_connection

LOGGER = logging.getLogger(__name__)


def save_device_classification(
    device_id: int,
    classification_data: Dict[str, Any],
) -> bool:
    """Insert or update classification result for a device."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        predicted_class = classification_data["predicted_class"]
        confidence = float(classification_data["confidence"])
        model_version = str(classification_data.get("model_version", "device-classifier-v1"))
        source = str(classification_data.get("source", "ML"))
        features_version = str(classification_data.get("features_version", "v1"))
        evidence = json.dumps(classification_data.get("evidence", []))
        rule_pred = classification_data.get("rule_prediction")
        ml_pred = classification_data.get("ml_prediction")
        status = str(classification_data.get("status", "ACTIVE"))
        probs = json.dumps(classification_data.get("probabilities", {}))

        cursor.execute(
            """
            INSERT INTO device_classifications (
                device_id, predicted_class, confidence, model_version,
                source, features_version, evidence, rule_prediction,
                ml_prediction, status, probabilities, classified_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                predicted_class = VALUES(predicted_class),
                confidence = VALUES(confidence),
                model_version = VALUES(model_version),
                source = VALUES(source),
                features_version = VALUES(features_version),
                evidence = VALUES(evidence),
                rule_prediction = VALUES(rule_prediction),
                ml_prediction = VALUES(ml_prediction),
                status = VALUES(status),
                probabilities = VALUES(probabilities),
                classified_at = CURRENT_TIMESTAMP
            """,
            (
                device_id,
                predicted_class,
                confidence,
                model_version,
                source,
                features_version,
                evidence,
                rule_pred,
                ml_pred,
                status,
                probs,
            ),
        )
        connection.commit()
        return True
    except Exception as error:
        LOGGER.warning("Could not save device classification for device_id=%s: %s", device_id, error)
        return False
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def get_device_classification(device_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve the current classification record for a device."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, device_id, predicted_class, confidence, model_version,
                   source, features_version, evidence, rule_prediction,
                   ml_prediction, status, probabilities, classified_at, updated_at
            FROM device_classifications
            WHERE device_id = %s
            """,
            (device_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        # Parse JSON fields safely
        try:
            row["evidence"] = json.loads(row["evidence"]) if row.get("evidence") else []
        except Exception:
            row["evidence"] = []

        try:
            row["probabilities"] = json.loads(row["probabilities"]) if row.get("probabilities") else {}
        except Exception:
            row["probabilities"] = {}

        if isinstance(row.get("classified_at"), datetime):
            row["classified_at"] = row["classified_at"].replace(tzinfo=timezone.utc).isoformat()
        if isinstance(row.get("updated_at"), datetime):
            row["updated_at"] = row["updated_at"].replace(tzinfo=timezone.utc).isoformat()

        return row
    except Exception as error:
        LOGGER.warning("Could not load classification for device_id=%s: %s", device_id, error)
        return None
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def save_human_label(
    device_id: int,
    label: str,
    source: str = "ADMIN",
    confirmed_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> bool:
    """Store verified human ground-truth label for a device."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO device_labels (
                device_id, label, source, confirmed_by, notes, created_at
            )
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (device_id, label, source, confirmed_by, notes),
        )
        connection.commit()
        return True
    except Exception as error:
        LOGGER.warning("Could not save device label for device_id=%s: %s", device_id, error)
        return False
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def get_latest_human_label(device_id: int) -> Optional[Dict[str, Any]]:
    """Get the latest human label assigned to a device."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, device_id, label, source, confirmed_by, notes, created_at
            FROM device_labels
            WHERE device_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (device_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row.get("created_at"), datetime):
            row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()
        return row
    except Exception as error:
        LOGGER.warning("Could not load label for device_id=%s: %s", device_id, error)
        return None
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def get_all_human_labels() -> List[Dict[str, Any]]:
    """Retrieve all human labels for dataset training & validation."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT dl.id, dl.device_id, dl.label, dl.source, dl.confirmed_by, dl.notes, dl.created_at,
                   nd.mac_address, nd.hostname, nd.vendor, nd.ip_address
            FROM device_labels dl
            JOIN network_devices nd ON nd.id = dl.device_id
            ORDER BY dl.created_at DESC
            """
        )
        rows = cursor.fetchall() or []
        for r in rows:
            if isinstance(r.get("created_at"), datetime):
                r["created_at"] = r["created_at"].replace(tzinfo=timezone.utc).isoformat()
        return rows
    except Exception as error:
        LOGGER.warning("Could not load human labels: %s", error)
        return []
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def get_devices_needing_review(limit: int = 50) -> List[Dict[str, Any]]:
    """Find devices with low confidence, status NEEDS_REVIEW, or UNKNOWN classification."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT nd.id AS device_id, nd.mac_address, nd.ip_address, nd.hostname, nd.vendor,
                   dc.predicted_class, dc.confidence, dc.model_version, dc.source,
                   dc.status, dc.rule_prediction, dc.ml_prediction, dc.classified_at
            FROM network_devices nd
            LEFT JOIN device_classifications dc ON dc.device_id = nd.id
            WHERE dc.status = 'NEEDS_REVIEW'
               OR dc.confidence < 0.70
               OR dc.predicted_class = 'UNKNOWN'
               OR dc.id IS NULL
            ORDER BY COALESCE(dc.confidence, 0.0) ASC, nd.last_seen DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall() or []
        for r in rows:
            if isinstance(r.get("classified_at"), datetime):
                r["classified_at"] = r["classified_at"].replace(tzinfo=timezone.utc).isoformat()
        return rows
    except Exception as error:
        LOGGER.warning("Could not load devices needing review: %s", error)
        return []
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def get_classification_summary_statistics() -> Dict[str, Any]:
    """Calculate aggregated classification counts, confidence tiers, and model stats."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # 1. Total devices & classified devices
        cursor.execute("SELECT COUNT(*) AS total_devices FROM network_devices")
        tot_dev = cursor.fetchone()["total_devices"]

        cursor.execute(
            """
            SELECT predicted_class, COUNT(*) AS count
            FROM device_classifications
            GROUP BY predicted_class
            """
        )
        class_counts = {r["predicted_class"]: r["count"] for r in cursor.fetchall() or []}

        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN confidence >= 0.90 THEN 1 ELSE 0 END) AS high_confidence,
                SUM(CASE WHEN confidence >= 0.70 AND confidence < 0.90 THEN 1 ELSE 0 END) AS medium_confidence,
                SUM(CASE WHEN confidence < 0.70 THEN 1 ELSE 0 END) AS low_confidence,
                SUM(CASE WHEN status = 'NEEDS_REVIEW' THEN 1 ELSE 0 END) AS needs_review,
                AVG(confidence) AS avg_confidence
            FROM device_classifications
            """
        )
        conf_row = cursor.fetchone() or {}

        cursor.execute("SELECT COUNT(*) AS total_human_labels FROM device_labels")
        human_labels_count = cursor.fetchone()["total_human_labels"]

        return {
            "total_devices": tot_dev,
            "total_classified": sum(class_counts.values()),
            "class_distribution": class_counts,
            "high_confidence_count": conf_row.get("high_confidence") or 0,
            "medium_confidence_count": conf_row.get("medium_confidence") or 0,
            "low_confidence_count": conf_row.get("low_confidence") or 0,
            "needs_review_count": conf_row.get("needs_review") or 0,
            "average_confidence": round(float(conf_row.get("avg_confidence") or 0.0), 4),
            "human_labels_count": human_labels_count,
            "model_version": "device-classifier-v1",
        }
    except Exception as error:
        LOGGER.warning("Could not calculate classification summary stats: %s", error)
        return {
            "total_devices": 0,
            "total_classified": 0,
            "class_distribution": {},
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
            "needs_review_count": 0,
            "average_confidence": 0.0,
            "human_labels_count": 0,
            "model_version": "device-classifier-v1",
        }
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
