import hashlib
import json

import pytest
from ingest import (
    DatasetError,
    dataset_manifest_hash,
    evaluate_dataset,
    inspect_dataset,
    load_dataset_manifest,
)
from PIL import Image


def _annotation(source_sha):
    return {"schema_version": "stage-4e-annotation-v1", "asset_sha256": source_sha,
            "pixel_size": {"width": 20, "height": 20},
            "rooms": [{"id": "room-1", "rect": [0, 0, 10, 10]}],
            "walls": [], "openings": []}


def _write_dataset(tmp_path, prediction=True):
    image_path = tmp_path / "sources" / "plan.png"
    annotation_path = tmp_path / "annotations" / "plan.json"
    image_path.parent.mkdir()
    annotation_path.parent.mkdir()
    image = Image.new("RGB", (20, 20), "white")
    image.save(image_path, format="PNG")
    source_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
    annotation_path.write_text(json.dumps(_annotation(source_sha)), encoding="utf-8")
    annotation_sha = hashlib.sha256(annotation_path.read_bytes()).hexdigest()
    record = {"id": "plan-1", "split": "baseline",
              "source": {"path": "sources/plan.png", "sha256": source_sha, "media_type": "image/png",
                          "pixel_size": {"width": 20, "height": 20}},
              "annotation": {"path": "annotations/plan.json", "sha256": annotation_sha,
                             "schema_version": "stage-4e-annotation-v1",
                             "review_status": "reviewed", "annotator": "annotator-001", "reviewer": "reviewer-001"},
              "authorization": {"status": "authorized", "reference": "consent-001"},
              "provenance": {"source": "authorized_upload"}}
    if prediction:
        model = {"source": {"sha256": source_sha},
                 "ingest": {"pixel_size": {"width": 20, "height": 20}, "mm_per_pixel": 10},
                 "rooms": [{"id": "room-1", "rect": [0, 0, 100, 100]}]}
        prediction_path = tmp_path / "predictions" / "plan.json"
        prediction_path.parent.mkdir()
        prediction_path.write_text(json.dumps(model), encoding="utf-8")
        record["prediction"] = {"path": "predictions/plan.json",
                                 "sha256": hashlib.sha256(prediction_path.read_bytes()).hexdigest()}
    return {"schema_version": "stage-4e-dataset-v1", "dataset_id": "real-baseline-v1",
            "status": "ready" if prediction else "intake_pending", "records": [record]}


def test_manifest_rejects_traversal_and_non_authorized_records(tmp_path):
    document = _write_dataset(tmp_path, prediction=False)
    document["records"][0]["source"]["path"] = "../plan.png"
    with pytest.raises(DatasetError, match="relative path"):
        load_dataset_manifest(document)


def test_inspect_dataset_verifies_hashes_annotation_and_pixel_size(tmp_path):
    document = _write_dataset(tmp_path, prediction=True)
    inventory = inspect_dataset(tmp_path, document)
    assert inventory["ready"] is True
    assert inventory["records"][0]["pixel_size"] == {"width": 20, "height": 20}


def test_evaluate_dataset_aggregates_rooms(tmp_path):
    document = _write_dataset(tmp_path, prediction=True)
    result = evaluate_dataset(tmp_path, document)
    assert result["rooms"] == {"predicted_count": 1, "truth_count": 1, "matched_count": 1,
                                "precision": 1.0, "recall": 1.0, "f1": 1.0, "iou_threshold": 0.95}


def test_empty_dataset_is_explicitly_pending_and_not_evaluable(tmp_path):
    document = {"schema_version": "stage-4e-dataset-v1", "dataset_id": "pending",
                "status": "intake_pending", "records": []}
    assert inspect_dataset(tmp_path, document)["ready"] is False
    with pytest.raises(DatasetError, match="empty dataset"):
        evaluate_dataset(tmp_path, document)


def test_manifest_hash_is_stable_and_source_sha_cannot_be_counted_twice(tmp_path):
    document = _write_dataset(tmp_path, prediction=True)
    assert dataset_manifest_hash(document) == dataset_manifest_hash(json.loads(json.dumps(document)))
    duplicate = json.loads(json.dumps(document["records"][0]))
    duplicate["id"] = "plan-2"
    document["records"].append(duplicate)
    with pytest.raises(DatasetError, match="duplicate source SHA-256"):
        load_dataset_manifest(document)
