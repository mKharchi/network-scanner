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
    parser.add_argument("--windows-jsonl", help="Derived TrafficWindow JSONL; bypasses the SQLite store")
    parser.add_argument("--labels-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-version", default="activity-local-v1")
    args = parser.parse_args()

    if args.windows_jsonl:
        windows = [
            json.loads(line)
            for line in Path(args.windows_jsonl).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
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

    # A second tabular model is useful as a sanity check, but the Random
    # Forest remains the v1 artifact used by runtime inference.
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier

        features, columns = ActivityRandomForestClassifier._matrix(splits["train"])
        gradient = HistGradientBoostingClassifier(random_state=42, max_iter=160)
        gradient.fit(features, [row.label for row in splits["train"]])
        gradient_metrics = {}
        for name, members in splits.items():
            if not members:
                continue
            matrix = [[row.feature_vector.feature_values.get(column, 0.0) for column in columns] for row in members]
            predicted = gradient.predict(matrix)
            from server_components.device_activity import _evaluate_predictions
            gradient_metrics[name] = asdict(_evaluate_predictions([row.label for row in members], list(predicted)))
        for name in gradient_metrics:
            metrics[name]["hist_gradient_boosting"] = gradient_metrics[name]
    except (ImportError, ValueError) as error:
        gradient_error = str(error)
    else:
        gradient_error = None

    output_dir = Path(args.output_dir)
    split_label_counts = {
        name: dict(sorted(Counter(row.label for row in members).items()))
        for name, members in splits.items()
    }
    split_capture_counts = {
        name: len({row.capture_session for row in members})
        for name, members in splits.items()
    }
    all_labels = sorted(set(row.label for row in rows))
    missing_classes = {
        name: sorted(set(all_labels) - set(Counter(row.label for row in members)))
        for name, members in splits.items()
    }
    artifacts = classifier.save(
        output_dir,
        artifact_metadata={
            "training_capture_count": len({row.capture_session for row in splits["train"]}),
            "split_strategy": split_metadata,
        },
    )
    report = {
        "status": "benchmark_candidate",
        "production_eligible": False,
        "reason": "controlled labelled sessions and held-out metrics require review",
        "dataset_version": args.dataset_version,
        "window_count": len(rows),
        "label_counts": dict(sorted(Counter(row.label for row in rows).items())),
        "split_counts": {name: len(members) for name, members in splits.items()},
        "split_capture_counts": split_capture_counts,
        "split_label_counts": split_label_counts,
        "classes_missing_from_split": missing_classes,
        "split_metadata": split_metadata,
        "metrics": metrics,
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "hist_gradient_boosting": {"available": gradient_error is None, "error": gradient_error},
    }
    (output_dir / "benchmark-report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
