"""Validated screenshot file and metadata persistence for managed clients."""

from __future__ import annotations

import base64
import binascii
import os
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _validate_png_bytes(image_bytes: bytes) -> None:
    """Validate PNG signature, chunk framing, CRCs, and an IHDR header."""
    if not image_bytes.startswith(PNG_SIGNATURE):
        raise ValueError("Screenshot payload is not a valid PNG image.")
    offset = len(PNG_SIGNATURE)
    saw_header = False
    saw_data = False
    saw_end = False
    while offset < len(image_bytes):
        if offset + 12 > len(image_bytes):
            raise ValueError("Screenshot payload is not a valid PNG image.")
        chunk_length = struct.unpack(">I", image_bytes[offset : offset + 4])[0]
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(image_bytes):
            raise ValueError("Screenshot payload is not a valid PNG image.")
        chunk_type = image_bytes[offset + 4 : offset + 8]
        chunk_data = image_bytes[offset + 8 : offset + 8 + chunk_length]
        expected_crc = struct.unpack(">I", image_bytes[offset + 8 + chunk_length : chunk_end])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise ValueError("Screenshot payload is not a valid PNG image.")
        if chunk_type == b"IHDR":
            if chunk_length != 13:
                raise ValueError("Screenshot payload is not a valid PNG image.")
            saw_header = True
        if chunk_type == b"IDAT":
            saw_data = True
        if chunk_type == b"IEND":
            saw_end = True
            if chunk_end != len(image_bytes):
                raise ValueError("Screenshot payload is not a valid PNG image.")
            break
        offset = chunk_end
    if not saw_header or not saw_data or not saw_end:
        raise ValueError("Screenshot payload is not a valid PNG image.")


DEFAULT_STORAGE_DIR = Path(__file__).resolve().parents[1] / "storage" / "screenshots"
SCREENSHOT_STORAGE_DIR = Path(os.getenv("SCREENSHOT_STORAGE_DIR", str(DEFAULT_STORAGE_DIR)))
MAX_SCREENSHOT_BYTES = max(1, int(os.getenv("SCREENSHOT_MAX_FILE_BYTES", str(8 * 1024 * 1024))))
PNG_MIME_TYPE = "image/png"


def _safe_component(value: str) -> str:
    return "".join(character for character in str(value) if character.isalnum() or character in "-_")[:100] or "unknown"


def decode_and_validate_png(encoded_image: str) -> bytes:
    """Decode and verify a bounded PNG payload before writing it to storage."""
    if not isinstance(encoded_image, str):
        raise ValueError("Screenshot image payload is missing.")
    try:
        image_bytes = base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Screenshot image payload is not valid base64.") from error
    if not image_bytes or len(image_bytes) > MAX_SCREENSHOT_BYTES:
        raise ValueError("Screenshot image exceeds the configured size limit.")
    _validate_png_bytes(image_bytes)
    return image_bytes


def store_screenshot(client_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and store a screenshot under ``storage/screenshots/<client>/``."""
    image_bytes = decode_and_validate_png(data.get("image_base64"))
    captured_at = data.get("captured_at") or datetime.now(timezone.utc).isoformat()
    filename = _safe_component(data.get("filename", "screenshot"))
    if not filename.endswith(".png"):
        filename = f"{filename}.png"
    command_id = _safe_component(data.get("command_id", ""))
    if command_id and command_id not in filename:
        filename = f"{Path(filename).stem}-{command_id[:12]}.png"

    client_dir = SCREENSHOT_STORAGE_DIR / _safe_component(client_id)
    client_dir.mkdir(parents=True, exist_ok=True)
    file_path = client_dir / filename
    suffix = 1
    while file_path.exists():
        file_path = client_dir / f"{Path(filename).stem}-{suffix}.png"
        suffix += 1
    file_path.write_bytes(image_bytes)

    return {
        "filename": file_path.name,
        "storage_path": str(file_path),
        "mime_type": PNG_MIME_TYPE,
        "file_size": len(image_bytes),
        "captured_at": captured_at,
        "device_name": data.get("device_name") or "unknown-device",
        "command_id": data.get("command_id"),
    }
