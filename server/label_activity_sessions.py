"""Create window-level activity labels from explicit timed sessions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from server_components.device_activity import label_windows_from_sessions
from server_components.kismet_ml_pipeline import KismetMLDerivedStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", default="server/storage/kismet_ml")
    parser.add_argument("--sessions-jsonl", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    store = KismetMLDerivedStore(args.storage_dir)
    sessions = [json.loads(line) for line in Path(args.sessions_jsonl).read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = label_windows_from_sessions(store.load_all("traffic_windows"), sessions)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in labels), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": "ok", "label_count": len(labels), "label_counts": dict(Counter(row["label"] for row in labels)), "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

