"""Deterministic evaluation helpers for stage 4E bitmap annotations."""

from __future__ import annotations

import math
from typing import Any

ANNOTATION_SCHEMA_VERSION = "stage-4e-annotation-v1"


class AnnotationError(ValueError):
    """Raised when an evaluation annotation violates the frozen contract."""


def _finite(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AnnotationError(f"{path} must be a finite number")
    return float(value)


def _id(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnnotationError(f"{path} must be a non-empty string")
    return value


def _rect(value: Any, path: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise AnnotationError(f"{path} must be [x, y, width, height]")
    rect = [_finite(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if rect[2] <= 0 or rect[3] <= 0:
        raise AnnotationError(f"{path} width and height must be > 0")
    return rect


def _unique_ids(items: list[dict[str, Any]], path: str) -> None:
    ids = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise AnnotationError(f"{path}[{index}] must be an object")
        ids.append(_id(item.get("id"), f"{path}[{index}].id"))
    if len(ids) != len(set(ids)):
        raise AnnotationError(f"{path} contains duplicate ids")


def load_annotation(document: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a stage 4E ground-truth annotation document."""
    if not isinstance(document, dict):
        raise AnnotationError("annotation must be an object")
    if document.get("schema_version") != ANNOTATION_SCHEMA_VERSION:
        raise AnnotationError(f"schema_version must be {ANNOTATION_SCHEMA_VERSION!r}")
    asset_sha256 = _id(document.get("asset_sha256"), "asset_sha256").lower()
    if len(asset_sha256) != 64 or any(character not in "0123456789abcdef" for character in asset_sha256.lower()):
        raise AnnotationError("asset_sha256 must be a 64-character hexadecimal SHA-256")
    pixel_size = document.get("pixel_size")
    if not isinstance(pixel_size, dict):
        raise AnnotationError("pixel_size must be an object")
    width = _finite(pixel_size.get("width"), "pixel_size.width")
    height = _finite(pixel_size.get("height"), "pixel_size.height")
    if width <= 0 or height <= 0:
        raise AnnotationError("pixel_size width and height must be > 0")

    rooms = document.get("rooms")
    walls = document.get("walls")
    openings = document.get("openings")
    if not all(isinstance(items, list) for items in (rooms, walls, openings)):
        raise AnnotationError("rooms, walls and openings must be arrays")
    _unique_ids(rooms, "rooms")
    _unique_ids(walls, "walls")
    _unique_ids(openings, "openings")
    normalized_rooms = []
    for index, room in enumerate(rooms):
        if not isinstance(room, dict):
            raise AnnotationError(f"rooms[{index}] must be an object")
        normalized_rooms.append({"id": _id(room.get("id"), f"rooms[{index}].id"),
                                 "rect": _rect(room.get("rect"), f"rooms[{index}].rect")})
    normalized_walls = []
    wall_ids = set()
    for index, wall in enumerate(walls):
        if not isinstance(wall, dict):
            raise AnnotationError(f"walls[{index}] must be an object")
        wall_id = _id(wall.get("id"), f"walls[{index}].id")
        axis = wall.get("axis")
        if not isinstance(axis, str) or axis not in {"h", "v"}:
            raise AnnotationError(f"walls[{index}].axis must be 'h' or 'v'")
        normalized_walls.append({"id": wall_id, "axis": axis,
                                 "x": _finite(wall.get("x"), f"walls[{index}].x"),
                                 "y": _finite(wall.get("y"), f"walls[{index}].y"),
                                 "length": _finite(wall.get("length"), f"walls[{index}].length")})
        if normalized_walls[-1]["length"] <= 0:
            raise AnnotationError(f"walls[{index}].length must be > 0")
        wall_ids.add(wall_id)
    normalized_openings = []
    for index, opening in enumerate(openings):
        if not isinstance(opening, dict):
            raise AnnotationError(f"openings[{index}] must be an object")
        kind = opening.get("kind")
        if not isinstance(kind, str) or kind not in {"door", "window", "passage"}:
            raise AnnotationError(f"openings[{index}].kind must be door, window or passage")
        host = _id(opening.get("host_wall_id"), f"openings[{index}].host_wall_id")
        if host not in wall_ids:
            raise AnnotationError(f"openings[{index}].host_wall_id references unknown wall")
        offset = _finite(opening.get("offset"), f"openings[{index}].offset")
        opening_width = _finite(opening.get("width"), f"openings[{index}].width")
        if offset < 0 or opening_width <= 0:
            raise AnnotationError(f"openings[{index}] offset and width are invalid")
        normalized_openings.append({"id": _id(opening.get("id"), f"openings[{index}].id"),
                                    "host_wall_id": host, "kind": kind,
                                    "offset": offset, "width": opening_width})
    return {"schema_version": ANNOTATION_SCHEMA_VERSION, "asset_sha256": asset_sha256,
            "pixel_size": {"width": width, "height": height}, "rooms": normalized_rooms,
            "walls": normalized_walls, "openings": normalized_openings}


def rect_iou(left: list[float], right: list[float]) -> float:
    """Return intersection-over-union for [x, y, width, height] rectangles."""
    left_x2, left_y2 = left[0] + left[2], left[1] + left[3]
    right_x2, right_y2 = right[0] + right[2], right[1] + right[3]
    intersection = max(0.0, min(left_x2, right_x2) - max(left[0], right[0])) * max(
        0.0, min(left_y2, right_y2) - max(left[1], right[1])
    )
    union = left[2] * left[3] + right[2] * right[3] - intersection
    return 0.0 if union <= 0 else intersection / union


def evaluate_rooms(predicted: list[dict[str, Any]], truth: list[dict[str, Any]],
                   iou_threshold: float = 0.95) -> dict[str, Any]:
    """Match room rectangles once and return deterministic accuracy metrics."""
    if isinstance(iou_threshold, bool) or not isinstance(iou_threshold, (int, float)) or not 0 <= iou_threshold <= 1 or not math.isfinite(iou_threshold):
        raise AnnotationError("iou_threshold must be between 0 and 1")
    if not isinstance(predicted, list) or not isinstance(truth, list):
        raise AnnotationError("predicted and truth rooms must be arrays")
    _unique_ids(predicted, "predicted rooms")
    _unique_ids(truth, "truth rooms")
    for item in predicted:
        prediction_id = _id(item.get("id"), "predicted room id")
        _rect(item.get("rect"), f"predicted room {prediction_id}.rect")
    for item in truth:
        truth_id = _id(item.get("id"), "truth room id")
        _rect(item.get("rect"), f"truth room {truth_id}.rect")
    prediction_rows = {item["id"]: _rect(item["rect"], f"predicted room {item['id']}.rect") for item in predicted}
    truth_rows = {item["id"]: _rect(item["rect"], f"truth room {item['id']}.rect") for item in truth}
    pairs = []
    for prediction in predicted:
        prediction_id = _id(prediction.get("id"), "predicted room id")
        prediction_rect = prediction_rows[prediction_id]
        for expected in truth:
            truth_id = _id(expected.get("id"), "truth room id")
            truth_rect = truth_rows[truth_id]
            pairs.append((rect_iou(prediction_rect, truth_rect), prediction_id, truth_id))
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    neighbors: dict[str, list[tuple[str, float]]] = {item["id"]: [] for item in predicted}
    for score, prediction_id, truth_id in pairs:
        if score >= iou_threshold:
            neighbors[prediction_id].append((truth_id, score))
    matched_truth: dict[str, tuple[str, float]] = {}

    def augment(prediction_id: str, visited: set[str]) -> bool:
        for truth_id, score in neighbors[prediction_id]:
            if truth_id in visited:
                continue
            visited.add(truth_id)
            previous = matched_truth.get(truth_id)
            if previous is None or augment(previous[0], visited):
                matched_truth[truth_id] = (prediction_id, score)
                return True
        return False

    for prediction_id in sorted(neighbors):
        augment(prediction_id, set())
    matches = [{"predicted_id": prediction_id, "truth_id": truth_id,
                "iou": round(score, 6), "accepted": True}
               for truth_id, (prediction_id, score) in matched_truth.items()]
    matches.sort(key=lambda item: (-item["iou"], item["predicted_id"], item["truth_id"]))
    accepted = matches
    predicted_count = len(predicted)
    truth_count = len(truth)
    precision = len(accepted) / predicted_count if predicted_count else 0.0
    recall = len(accepted) / truth_count if truth_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"predicted_count": predicted_count, "truth_count": truth_count,
            "matched_count": len(accepted),
            "precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6),
            "mean_iou": round(sum(item["iou"] for item in accepted) / len(accepted), 6) if accepted else 0.0,
            "iou_threshold": iou_threshold, "matches": matches}


def evaluate_model(model: dict[str, Any], annotation: dict[str, Any],
                   iou_threshold: float = 0.95) -> dict[str, Any]:
    """Evaluate an ingest model against pixel-space ground truth."""
    if not isinstance(model, dict):
        raise AnnotationError("model must be an object")
    truth = load_annotation(annotation)
    source = model.get("source")
    ingest = model.get("ingest")
    if not isinstance(source, dict) or source.get("sha256") != truth["asset_sha256"]:
        raise AnnotationError("model source SHA-256 does not match annotation")
    if not isinstance(ingest, dict):
        raise AnnotationError("model.ingest must be an object")
    pixel_size = ingest.get("pixel_size")
    if pixel_size != truth["pixel_size"]:
        raise AnnotationError("model pixel_size does not match annotation")
    scale = ingest.get("mm_per_pixel")
    scale = _finite(scale, "model.ingest.mm_per_pixel")
    if scale <= 0:
        raise AnnotationError("model.ingest.mm_per_pixel must be > 0")
    rooms = model.get("rooms")
    if not isinstance(rooms, list):
        raise AnnotationError("model.rooms must be an array")
    predicted = []
    for index, room in enumerate(rooms):
        if not isinstance(room, dict):
            raise AnnotationError(f"model.rooms[{index}] must be an object")
        rect = _rect(room.get("rect"), f"model.rooms[{index}].rect")
        predicted.append({"id": _id(room.get("id"), f"model.rooms[{index}].id"),
                          "rect": [value / scale for value in rect]})
    return {"asset_sha256": truth["asset_sha256"], "mm_per_pixel": scale,
            "rooms": evaluate_rooms(predicted, truth["rooms"], iou_threshold)}
