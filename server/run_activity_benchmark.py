"""Benchmark Plan 2 activity models from explicitly labelled traffic windows.

The command reads Phase 0 derived windows and a JSONL label manifest. It never
assigns labels to ambient traffic and never changes authoritative device data.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from server_components.device_activity import (
    ActivityMajorityBaseline,
    ActivityRandomForestClassifier,
    load_labeled_activity_windows,
    split_activity_windows,
)
from server_components.kismet_ml_pipeline import KismetMLDerivedStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", default="server/storage/kismet_ml")
    parser.add_argument("--labels-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-version", default="activity-local-v1")
    args = parser.parse_args()

    store = KismetMLDerivedStore(args.storage_dir)
    windows = store.load_all("traffic_windows")
    label_path = Path(args.labels_jsonl)
    labels = [json.loads(line) for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = load_labeled_activity_windows(windows, labels)
    if not rows:
        raise SystemExit("no explicitly labelled activity windows were found")
    splits, split_metadata = split_activity_windows(rows)
    if not splits["train"]:
        raise SystemExit("activity split has no training windows")

    baseline = ActivityMajorityBaseline().fit(splits["train"])
    classifier = ActivityRandomForestClassifier().fit(splits["train"], dataset_version=args.dataset_version)
    metrics = {}
    for name, members in splits.items():
        if not members:
            continue
        metrics[name] = {
            "majority_baseline": asdict(baseline.evaluate(members)),
            "random_forest": asdict(classifier.evaluate(members)),
        }

    output_dir = Path(args.output_dir)
    artifacts = classifier.save(output_dir)
    report = {
        "status": "benchmark_candidate",
        "production_eligible": False,
        "reason": "controlled labelled sessions and held-out metrics require review",
        "dataset_version": args.dataset_version,
        "window_count": len(rows),
        "label_counts": dict(sorted(Counter(row.label for row in rows).items())),
        "split_counts": {name: len(members) for name, members in splits.items()},
        "split_metadata": split_metadata,
        "metrics": metrics,
        "artifacts": {name: str(path) for name, path in artifacts.items()},
    }
    (output_dir / "benchmark-report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

