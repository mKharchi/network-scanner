"""Train and report the Phase 1 fingerprint benchmark candidate.

This produces an experiment artifact only.  It does not register the model for
production identity linking and does not mutate authoritative device records.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from server_components.device_fingerprinting import (
    FingerprintEvaluation,
    PairwiseFingerprintClassifier,
    build_pair_records,
    evaluate_similarity,
    fingerprint_similarity,
    split_fingerprint_examples,
)
from server_components.fingerprint_dataset import load_mendeley_profiles


def _evaluate_randomized_pairs(examples, scorer, threshold):
    """Evaluate same-device pairs whose profile MAC sets are disjoint."""
    by_id = {example.profile_id: example for example in examples}
    selected = []
    for pair in build_pair_records(examples):
        if not pair.label_same_device:
            continue
        left = set(by_id[pair.left_profile_id].feature_vector.observed_macs)
        right = set(by_id[pair.right_profile_id].feature_vector.observed_macs)
        if left and right and left.isdisjoint(right):
            selected.append(pair)
    tp = sum(scorer(by_id[p.left_profile_id].feature_vector, by_id[p.right_profile_id].feature_vector) >= threshold for p in selected)
    fn = len(selected) - tp
    return FingerprintEvaluation(
        threshold, tp, 0, fn, 0,
        1.0 if tp else 0.0, tp / len(selected) if selected else 0.0,
        1.0 if tp else 0.0, 0.0, fn / len(selected) if selected else 0.0,
    )


def _changed_mac_pair_count(examples):
    by_id = {example.profile_id: example for example in examples}
    count = 0
    for pair in build_pair_records(examples):
        if not pair.label_same_device:
            continue
        left = set(by_id[pair.left_profile_id].feature_vector.observed_macs)
        right = set(by_id[pair.right_profile_id].feature_vector.observed_macs)
        count += bool(left and right and left.isdisjoint(right))
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-version", default="mendeley-2024-v2")
    args = parser.parse_args()
    dataset_root, output_dir = Path(args.dataset_root), Path(args.output_dir)
    examples = [profile for profile, _metadata in load_mendeley_profiles(dataset_root)]
    splits, split_metadata = split_fingerprint_examples(examples)
    classifier = PairwiseFingerprintClassifier().fit(splits["train"], dataset_version=args.dataset_version)
    metrics = {}
    for split, rows in splits.items():
        if not rows or len({example.physical_device_guid for example in rows}) <= 1:
            continue
        metrics[split] = {
            "similarity_baseline": {
                str(threshold): asdict(evaluate_similarity(rows, threshold=threshold))
                for threshold in (0.5, 0.7, 0.8, 0.9)
            },
            "random_forest": {
                str(threshold): asdict(classifier.evaluate(rows, threshold=threshold))
                for threshold in (0.5, 0.7, 0.8, 0.9)
            },
            "same_device_changed_mac": {
                "pair_count": _changed_mac_pair_count(rows),
                "similarity_baseline": {
                    str(threshold): asdict(_evaluate_randomized_pairs(
                        rows, lambda left, right: fingerprint_similarity(left, right)[0], threshold,
                    )) for threshold in (0.5, 0.7, 0.8, 0.9)
                },
                "random_forest": {
                    str(threshold): asdict(_evaluate_randomized_pairs(rows, classifier.score, threshold))
                    for threshold in (0.5, 0.7, 0.8, 0.9)
                },
            },
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = classifier.save(output_dir)
    report = {
        "status": "benchmark_candidate",
        "production_eligible": False,
        "reason": "held-out metrics require review before shadow deployment",
        "dataset_version": args.dataset_version,
        "profile_count": len(examples),
        "device_count": len({example.physical_device_guid for example in examples}),
        "observation_count": sum(len(example.feature_vector.source_observation_ids) for example in examples),
        "split_metadata": split_metadata,
        "split_counts": {name: len(rows) for name, rows in splits.items()},
        "metrics": metrics,
        "artifact": {name: str(path) for name, path in artifact_paths.items()},
    }
    (output_dir / "benchmark-report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
