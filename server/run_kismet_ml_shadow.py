"""Run one checkpointed Phase 0 Kismet ML shadow-processing cycle.

Suitable for a systemd timer, cron, or a manual backfill.  It never starts or
reconfigures Kismet; capture databases are opened by the processor read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from server_components.kismet_ml_pipeline import KismetMLShadowProcessor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="append", default=None, help="Capture directory or .kismet file; repeatable")
    parser.add_argument("--storage-dir", help="Derived ML storage directory (default: KISMET_ML_STORAGE_DIR or server/storage/kismet_ml)")
    parser.add_argument("--dataset-version", help="Also persist a provenance manifest with this version")
    parser.add_argument("--source-dataset", default="local-kismet")
    parser.add_argument("--capture-environment", default="production")
    parser.add_argument("--label-source-type", default="derived_label")
    parser.add_argument("--split-strategy", default="not-applicable-shadow-processing")
    args = parser.parse_args()

    processor = KismetMLShadowProcessor(args.capture, storage_dir=args.storage_dir)
    result = processor.run_once()
    if args.dataset_version:
        result["dataset_manifest"] = processor.export_dataset_manifest(
            dataset_version=args.dataset_version, source_dataset=args.source_dataset,
            capture_environment=args.capture_environment, label_source_type=args.label_source_type,
            split_strategy=args.split_strategy,
        ).to_dict()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
