"""Auditable real-plan dataset manifests and baseline evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

from .bitmap import load_bitmap
from .evaluation import ANNOTATION_SCHEMA_VERSION, AnnotationError, evaluate_model, load_annotation

DATASET_SCHEMA_VERSION = "stage-4e-dataset-v1"
DATASET_STATUS_INTAKE_PENDING = "intake_pending"
DATASET_STATUS_READY = "ready"
_SPLITS = {"baseline", "holdout"}
_MEDIA_TYPES = {"image/png", "image/jpeg"}
_REVIEW_STATUSES = {"reviewed", "draft"}


class DatasetError(ValueError):
    """Raised when a dataset manifest or referenced artifact is invalid."""


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{path} must be a non-empty string")
    return value


def _sha256(value: Any, path: str) -> str:
    value = _text(value, path).lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DatasetError(f"{path} must be a 64-character hexadecimal SHA-256")
    return value


def _relative_path(value: Any, path: str) -> str:
    value = _text(value, path)
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or value.startswith("~"):
        raise DatasetError(f"{path} must be a relative path without parent traversal")
    if parsed == PurePosixPath(".") or any(part in {"", "."} for part in parsed.parts):
        raise DatasetError(f"{path} must be a normalized relative path")
    return parsed.as_posix()


def _pixel_size(value: Any, path: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise DatasetError(f"{path} must be an object")
    result = {}
    for key in ("width", "height"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise DatasetError(f"{path}.{key} must be a positive integer")
        result[key] = number
    return result


def load_dataset_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a stage 4E real-plan dataset manifest."""
    if not isinstance(document, dict):
        raise DatasetError("dataset manifest must be an object")
    if document.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise DatasetError(f"schema_version must be {DATASET_SCHEMA_VERSION!r}")
    dataset_id = _text(document.get("dataset_id"), "dataset_id")
    status = document.get("status", DATASET_STATUS_INTAKE_PENDING)
    if status not in {DATASET_STATUS_INTAKE_PENDING, DATASET_STATUS_READY}:
        raise DatasetError("status must be intake_pending or ready")
    records = document.get("records")
    if not isinstance(records, list):
        raise DatasetError("records must be an array")
    normalized = []
    seen: set[str] = set()
    source_hashes: set[str] = set()
    for index, record in enumerate(records):
        path = f"records[{index}]"
        if not isinstance(record, dict):
            raise DatasetError(f"{path} must be an object")
        record_id = _text(record.get("id"), f"{path}.id")
        if record_id in seen:
            raise DatasetError(f"records contains duplicate id {record_id!r}")
        seen.add(record_id)
        split = record.get("split")
        if split not in _SPLITS:
            raise DatasetError(f"{path}.split must be baseline or holdout")
        source = record.get("source")
        annotation = record.get("annotation")
        authorization = record.get("authorization")
        if not isinstance(source, dict) or not isinstance(annotation, dict) or not isinstance(authorization, dict):
            raise DatasetError(f"{path} source, annotation and authorization must be objects")
        source_entry = {
            "path": _relative_path(source.get("path"), f"{path}.source.path"),
            "sha256": _sha256(source.get("sha256"), f"{path}.source.sha256"),
        }
        if source_entry["sha256"] in source_hashes:
            raise DatasetError(f"records contains duplicate source SHA-256 for {record_id!r}")
        source_hashes.add(source_entry["sha256"])
        media_type = source.get("media_type")
        if media_type not in _MEDIA_TYPES:
            raise DatasetError(f"{path}.source.media_type must be image/png or image/jpeg")
        source_entry["media_type"] = media_type
        source_entry["pixel_size"] = _pixel_size(source.get("pixel_size"), f"{path}.source.pixel_size")
        annotation_entry = {
            "path": _relative_path(annotation.get("path"), f"{path}.annotation.path"),
            "sha256": _sha256(annotation.get("sha256"), f"{path}.annotation.sha256"),
        }
        if annotation.get("schema_version") != ANNOTATION_SCHEMA_VERSION:
            raise DatasetError(f"{path}.annotation.schema_version must be {ANNOTATION_SCHEMA_VERSION!r}")
        annotation_entry["schema_version"] = ANNOTATION_SCHEMA_VERSION
        review_status = annotation.get("review_status", "draft")
        if review_status not in _REVIEW_STATUSES:
            raise DatasetError(f"{path}.annotation.review_status must be reviewed or draft")
        annotation_entry["review_status"] = review_status
        for role in ("annotator", "reviewer"):
            if role in annotation:
                annotation_entry[role] = _text(annotation[role], f"{path}.annotation.{role}")
        if review_status == "reviewed" and ("annotator" not in annotation or "reviewer" not in annotation):
            raise DatasetError(f"{path}.annotation reviewed records require annotator and reviewer")
        if authorization.get("status") != "authorized":
            raise DatasetError(f"{path}.authorization.status must be authorized")
        authorization_entry = {
            "status": "authorized",
            "reference": _text(authorization.get("reference"), f"{path}.authorization.reference"),
        }
        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            raise DatasetError(f"{path}.provenance must be an object")
        provenance_entry = {"source": _text(provenance.get("source"), f"{path}.provenance.source")}
        prediction = record.get("prediction")
        prediction_entry = None
        if prediction is not None:
            if not isinstance(prediction, dict):
                raise DatasetError(f"{path}.prediction must be an object or null")
            prediction_entry = {
                "path": _relative_path(prediction.get("path"), f"{path}.prediction.path"),
                "sha256": _sha256(prediction.get("sha256"), f"{path}.prediction.sha256"),
            }
        normalized.append({"id": record_id, "split": split, "source": source_entry,
                           "annotation": annotation_entry, "authorization": authorization_entry,
                           "provenance": provenance_entry, "prediction": prediction_entry})
    if status == DATASET_STATUS_READY and not normalized:
        raise DatasetError("ready dataset must contain at least one record")
    return {"schema_version": DATASET_SCHEMA_VERSION, "dataset_id": dataset_id,
            "status": status, "records": normalized}


def dataset_manifest_hash(document: dict[str, Any]) -> str:
    """Return the stable hash used to identify a normalized dataset manifest."""
    normalized = load_dataset_manifest(document)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise DatasetError(f"{label} must contain a JSON object")
    return value


def _artifact(root: Path, relative: str, expected_sha256: str, label: str) -> tuple[Path, bytes]:
    raw_path = root / relative
    if raw_path.is_symlink():
        raise DatasetError(f"{label} must not be a symlink: {relative}")
    path = raw_path.resolve()
    try:
        path.relative_to(root)
        data = path.read_bytes()
    except DatasetError:
        raise
    except (OSError, ValueError) as exc:
        raise DatasetError(f"{label} cannot be read: {relative}") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise DatasetError(f"{label} SHA-256 mismatch: expected {expected_sha256}, got {actual}")
    return path, data


def inspect_dataset(root: str | Path, document: dict[str, Any]) -> dict[str, Any]:
    """Verify source and annotation artifacts without running recognition."""
    manifest = load_dataset_manifest(document)
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise DatasetError(f"dataset root does not exist: {root}")
    records = []
    for record in manifest["records"]:
        source_path, source_bytes = _artifact(root_path, record["source"]["path"], record["source"]["sha256"],
                                               f"source {record['id']}")
        try:
            asset = load_bitmap(source_bytes, source_path.name)
        except ValueError as exc:
            raise DatasetError(f"source {record['id']} is not a supported bitmap: {exc}") from exc
        actual_size = {"width": asset.width, "height": asset.height}
        expected_media_type = record["source"].get("media_type")
        if expected_media_type is not None and expected_media_type != asset.media_type:
            raise DatasetError(f"source {record['id']} media_type mismatch")
        expected_size = record["source"].get("pixel_size")
        if expected_size is not None and expected_size != actual_size:
            raise DatasetError(f"source {record['id']} pixel_size mismatch")
        annotation_path, _annotation_bytes = _artifact(root_path, record["annotation"]["path"],
                                                       record["annotation"]["sha256"], f"annotation {record['id']}")
        annotation = load_annotation(_read_json(annotation_path, f"annotation {record['id']}"))
        if annotation["asset_sha256"] != record["source"]["sha256"]:
            raise DatasetError(f"annotation {record['id']} asset_sha256 does not match source")
        if annotation["pixel_size"] != actual_size:
            raise DatasetError(f"annotation {record['id']} pixel_size does not match source")
        prediction = record.get("prediction")
        prediction_info = None
        if prediction is not None:
            prediction_path, prediction_bytes = _artifact(root_path, prediction["path"], prediction["sha256"],
                                                           f"prediction {record['id']}")
            _read_json(prediction_path, f"prediction {record['id']}")
            prediction_info = {"path": prediction["path"], "bytes": len(prediction_bytes)}
        records.append({"id": record["id"], "split": record["split"], "source_path": record["source"]["path"],
                        "annotation_path": record["annotation"]["path"], "pixel_size": actual_size,
                        "annotation_review_status": record["annotation"]["review_status"],
                        "prediction": prediction_info})
    return {"dataset_id": manifest["dataset_id"], "status": manifest["status"],
            "record_count": len(records), "records": records,
            "ready": bool(records) and all(item["prediction"] is not None
                                           and item["annotation_review_status"] == "reviewed"
                                           for item in records)}


def evaluate_dataset(root: str | Path, document: dict[str, Any], iou_threshold: float = 0.95) -> dict[str, Any]:
    """Evaluate every manifest record with a prediction artifact."""
    if isinstance(iou_threshold, bool) or not isinstance(iou_threshold, (int, float)) or not math.isfinite(iou_threshold):
        raise DatasetError("iou_threshold must be a finite number")
    manifest = load_dataset_manifest(document)
    if not manifest["records"]:
        raise DatasetError("cannot evaluate an empty dataset")
    root_path = Path(root).resolve()
    results = []
    for record in manifest["records"]:
        if record["annotation"]["review_status"] != "reviewed":
            raise DatasetError(f"record {record['id']} annotation is not reviewed")
        inspect_dataset(root_path, {**manifest, "records": [record]})
        prediction = record.get("prediction")
        if prediction is None:
            raise DatasetError(f"record {record['id']} has no prediction artifact")
        prediction_path, prediction_bytes = _artifact(root_path, prediction["path"], prediction["sha256"],
                                                      f"prediction {record['id']}")
        model = _read_json(prediction_path, f"prediction {record['id']}")
        annotation_path = root_path / record["annotation"]["path"]
        annotation = _read_json(annotation_path, f"annotation {record['id']}")
        try:
            metrics = evaluate_model(model, annotation, iou_threshold)
        except AnnotationError as exc:
            raise DatasetError(f"record {record['id']} evaluation failed: {exc}") from exc
        results.append({"id": record["id"], "split": record["split"], "metrics": metrics,
                        "prediction_bytes": len(prediction_bytes)})
    matched = sum(item["metrics"]["rooms"]["matched_count"] for item in results)
    predicted = sum(item["metrics"]["rooms"]["predicted_count"] for item in results)
    truth = sum(item["metrics"]["rooms"]["truth_count"] for item in results)
    precision = matched / predicted if predicted else 0.0
    recall = matched / truth if truth else 0.0
    return {"schema_version": DATASET_SCHEMA_VERSION, "dataset_id": manifest["dataset_id"],
            "record_count": len(results), "rooms": {"predicted_count": predicted, "truth_count": truth,
            "matched_count": matched, "precision": round(precision, 6), "recall": round(recall, 6),
            "f1": round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0,
            "iou_threshold": iou_threshold}, "records": results}
