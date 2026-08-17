"""IEEE MA-S / MA-M / MA-L lookup helpers.

Provides a safe loader for the bundled CSV files and a vendor lookup
that tries the most specific assignment first (MA-S -> MA-M -> MA-L/OUI).
"""

from pathlib import Path
import csv
import re
import os
from typing import Dict

IEEE_DATABASE_DIR = Path(__file__).resolve().parent / "data" / "ieee"


def _normalise_prefix(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().upper()
    value = re.sub(r"[^0-9A-F]", "", value)
    return value or None


def _load_ieee_csv(path: Path) -> Dict[str, str]:
    entries: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            for row in reader:
                if not row:
                    continue
                # Skip header rows that begin with 'Registry' or similar
                first = str(row[0]).strip().lower()
                if first.startswith("registry"):
                    continue

                # Assignment/prefix is usually column 1 (index 1)
                if len(row) < 2:
                    continue
                prefix = _normalise_prefix(row[1])
                if not prefix:
                    continue

                # Organization is typically the next column; find first non-empty
                organization = None
                for value in row[2:]:
                    if isinstance(value, str) and value.strip():
                        organization = value.strip()
                        break
                if not organization and len(row) >= 3:
                    # Fallback: use column 2 if nothing else
                    organization = row[2].strip()

                if organization:
                    entries[prefix] = organization
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError):
        return {}
    return entries


_CACHED_DB = None


def load_oui_database(force_reload: bool = False):
    """Load bundled MA-S, MA-M and MA-L databases from client/data/ieee.

    Returns a dict with keys: 'mas', 'mam', 'oui'. Each value is a mapping
    from hexadecimal prefix (no separators, uppercase) to organization string.
    """
    global _CACHED_DB
    if _CACHED_DB is not None and not force_reload:
        return _CACHED_DB

    mas = _load_ieee_csv(IEEE_DATABASE_DIR / "mas.csv")
    mam = _load_ieee_csv(IEEE_DATABASE_DIR / "mam.csv")
    oui = _load_ieee_csv(IEEE_DATABASE_DIR / "mal.csv")

    _CACHED_DB = {"mas": mas, "mam": mam, "oui": oui}
    return _CACHED_DB


def get_vendor(mac_address: str, database) -> str | None:
    """Return the most specific IEEE assignment for a MAC address.

    Expects `mac_address` as any reasonable MAC string (colon, dash or
    plain hex). `database` is the structure returned by `load_oui_database()`.
    """
    if not isinstance(mac_address, str):
        return None
    mac = re.sub(r"[^0-9A-Fa-f]", "", mac_address).upper()
    if len(mac) != 12:
        return None

    lookup_order = (("mas", 9), ("mam", 7), ("oui", 6))
    for db_name, prefix_len in lookup_order:
        table = database.get(db_name, {}) if isinstance(database, dict) else {}
        prefix = mac[:prefix_len]
        vendor = table.get(prefix)
        if vendor:
            return vendor
    return None
