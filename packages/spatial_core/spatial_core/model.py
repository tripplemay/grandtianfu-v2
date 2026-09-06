"""Canonical SpatialModel v2 validation and stable hashing."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class ModelValidationError(ValueError):
    """Raised when a spatial model violates the v2 storage contract."""


_REQUIRED_TOP_LEVEL = (
    "schema_version", "profile", "model_id", "revision", "status", "units",
    "coordinates", "source", "confidence", "rooms", "walls", "openings",
    "furniture_instances", "cameras", "materials",
)
_STATUSES = {"draft", "confirmed", "locked"}
_ATTACHMENTS = {"free", "wall", "fixed"}
_WALL_AXES = {"h", "v"}
_EPS = 1e-6


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelValidationError(f"{path} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ModelValidationError(f"{path} must be a finite number")
    return value


def _positive(value: Any, path: str) -> float:
    value = _finite_number(value, path)
    if value <= 0:
        raise ModelValidationError(f"{path} must be > 0")
    return value


def _id(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelValidationError(f"{path} must be a non-empty string")
    return value


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelValidationError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ModelValidationError(f"{path} must be an array")
    return value


def _confidence(value: Any, path: str) -> float:
    value = _finite_number(value, path)
    if not 0 <= value <= 1:
        raise ModelValidationError(f"{path} must be between 0 and 1")
    return value


def _xyz(value: Any, path: str) -> None:
    point = _object(value, path)
    for axis in ("x", "y", "z"):
        _finite_number(point.get(axis), f"{path}.{axis}")


def _collection_ids(collections: dict[str, list[dict[str, Any]]]) -> None:
    seen: dict[str, str] = {}
    for collection, items in collections.items():
        for index, item in enumerate(items):
            item_id = _id(item.get("id"), f"{collection}[{index}].id")
            previous = seen.get(item_id)
            if previous is not None:
                raise ModelValidationError(
                    f"duplicate id {item_id!r}: {previous} and {collection}[{index}]"
                )
            seen[item_id] = f"{collection}[{index}]"


def _rect(value: Any, path: str) -> tuple[float, float, float, float]:
    values = _list(value, path)
    if len(values) != 4:
        raise ModelValidationError(f"{path} must be [x, y, width, height]")
    x = _finite_number(values[0], f"{path}[0]")
    y = _finite_number(values[1], f"{path}[1]")
    width = _positive(values[2], f"{path}[2]")
    height = _positive(values[3], f"{path}[3]")
    return x, y, width, height


def _validate_source(value: Any) -> None:
    source = _object(value, "source")
    _id(source.get("asset_id"), "source.asset_id")
    _id(source.get("kind"), "source.kind")
    _id(source.get("sha256"), "source.sha256")
    _id(source.get("provenance"), "source.provenance")


def _validate_wall(item: dict[str, Any], index: int) -> None:
    path = f"walls[{index}]"
    if item.get("axis") not in _WALL_AXES:
        raise ModelValidationError(f"{path}.axis must be 'h' or 'v' in orthogonal_v1")
    for field in ("x", "y"):
        _finite_number(item.get(field), f"{path}.{field}")
    _positive(item.get("length"), f"{path}.length")
    _positive(item.get("thickness"), f"{path}.thickness")
    bottom = _finite_number(item.get("bottom_z"), f"{path}.bottom_z")
    top = _finite_number(item.get("top_z"), f"{path}.top_z")
    if bottom < 0 or top <= bottom:
        raise ModelValidationError(f"{path} must have 0 <= bottom_z < top_z")


def _validate_room(
    item: dict[str, Any], index: int, wall_ids: set[str]
) -> tuple[float, float, float, float]:
    path = f"rooms[{index}]"
    _id(item.get("name"), f"{path}.name")
    _id(item.get("kind"), f"{path}.kind")
    rect = _rect(item.get("rect"), f"{path}.rect")
    boundaries = _list(item.get("boundary_wall_ids"), f"{path}.boundary_wall_ids")
    if len(boundaries) < 4:
        raise ModelValidationError(f"{path}.boundary_wall_ids must contain at least 4 walls")
    for boundary_index, wall_id in enumerate(boundaries):
        wall_id = _id(wall_id, f"{path}.boundary_wall_ids[{boundary_index}]")
        if wall_id not in wall_ids:
            raise ModelValidationError(f"{path} references unknown wall {wall_id!r}")
    group = item.get("merge_group_id")
    if group is not None:
        _id(group, f"{path}.merge_group_id")
    return rect


def _validate_opening(item: dict[str, Any], index: int, wall_ids: set[str]) -> None:
    path = f"openings[{index}]"
    host = _id(item.get("host_wall_id"), f"{path}.host_wall_id")
    if host not in wall_ids:
        raise ModelValidationError(f"{path} references unknown wall {host!r}")
    _positive(item.get("width"), f"{path}.width")
    _positive(item.get("height"), f"{path}.height")
    bottom = _finite_number(item.get("bottom_z"), f"{path}.bottom_z")
    if bottom < 0:
        raise ModelValidationError(f"{path}.bottom_z must be >= 0")
    _finite_number(item.get("offset"), f"{path}.offset")
    _id(item.get("kind"), f"{path}.kind")


def _validate_furniture(
    item: dict[str, Any], index: int, room_ids: set[str],
    room_rects: dict[str, tuple[float, float, float, float]],
) -> None:
    path = f"furniture_instances[{index}]"
    _id(item.get("catalog_id"), f"{path}.catalog_id")
    room_id = _id(item.get("room_id"), f"{path}.room_id")
    if room_id not in room_ids:
        raise ModelValidationError(f"{path} references unknown room {room_id!r}")
    if item.get("attachment") not in _ATTACHMENTS:
        raise ModelValidationError(f"{path}.attachment must be one of {sorted(_ATTACHMENTS)}")
    _id(item.get("provenance"), f"{path}.provenance")
    _confidence(item.get("confidence"), f"{path}.confidence")
    asset_ref = _object(item.get("asset_ref"), f"{path}.asset_ref")
    _id(asset_ref.get("kind"), f"{path}.asset_ref.kind")
    _id(asset_ref.get("ref"), f"{path}.asset_ref.ref")
    transform = _object(item.get("transform"), f"{path}.transform")
    for axis in ("x", "y", "z"):
        _finite_number(transform.get(axis), f"{path}.transform.{axis}")
    rotation = _finite_number(transform.get("rotation_z"), f"{path}.transform.rotation_z")
    if abs(rotation / 90.0 - round(rotation / 90.0)) > _EPS:
        raise ModelValidationError(f"{path}.transform.rotation_z must be a multiple of 90 in orthogonal_v1")
    dimensions = _object(item.get("dimensions"), f"{path}.dimensions")
    width = _positive(dimensions.get("width"), f"{path}.dimensions.width")
    depth = _positive(dimensions.get("depth"), f"{path}.dimensions.depth")
    _positive(dimensions.get("height"), f"{path}.dimensions.height")
    room_x, room_y, room_w, room_h = room_rects[room_id]
    if int(round(rotation / 90.0)) % 2:
        width, depth = depth, width
    x, y = float(transform["x"]), float(transform["y"])
    if x < room_x - _EPS or y < room_y - _EPS or x + width > room_x + room_w + _EPS or y + depth > room_y + room_h + _EPS:
        raise ModelValidationError(f"{path} footprint must be inside room {room_id!r}")


def _validate_camera(item: dict[str, Any], index: int) -> None:
    path = f"cameras[{index}]"
    if item.get("projection") != "perspective":
        raise ModelValidationError(f"{path}.projection must be 'perspective' in orthogonal_v1")
    size = _object(item.get("image_size"), f"{path}.image_size")
    width = _positive(size.get("width"), f"{path}.image_size.width")
    height = _positive(size.get("height"), f"{path}.image_size.height")
    if width != int(width) or height != int(height):
        raise ModelValidationError(f"{path}.image_size dimensions must be integers")
    _xyz(item.get("position"), f"{path}.position")
    _xyz(item.get("look_at"), f"{path}.look_at")
    _xyz(item.get("up"), f"{path}.up")


def _validate_material(item: dict[str, Any], index: int) -> None:
    path = f"materials[{index}]"
    _id(item.get("provenance"), f"{path}.provenance")
    source = item.get("color") or item.get("texture")
    if source is None or not isinstance(source, (str, dict)):
        raise ModelValidationError(f"{path} needs color or texture")


def canonical_hash(document: dict[str, Any]) -> str:
    """Return a stable hash, excluding any stored content hash field."""
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_model(document: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the original model for convenient composition."""
    if not isinstance(document, dict):
        raise ModelValidationError("model must be an object")
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in document]
    if missing:
        raise ModelValidationError(f"missing top-level fields: {', '.join(missing)}")
    if document["schema_version"] != "2.0":
        raise ModelValidationError("schema_version must be '2.0'")
    if document["profile"] != "orthogonal_v1":
        raise ModelValidationError("profile must be 'orthogonal_v1'")
    if document["status"] not in _STATUSES:
        raise ModelValidationError(f"status must be one of {sorted(_STATUSES)}")
    _id(document["model_id"], "model_id")
    revision = document["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ModelValidationError("revision must be an integer >= 1")
    if document["units"] != {"length": "mm", "angle": "deg"}:
        raise ModelValidationError("units must be millimetres and degrees")
    coordinates = _object(document["coordinates"], "coordinates")
    _id(coordinates.get("origin"), "coordinates.origin")
    if coordinates.get("handedness") != "right":
        raise ModelValidationError("coordinates.handedness must be 'right'")
    _validate_source(document["source"])
    _confidence(document["confidence"], "confidence")

    collections: dict[str, list[dict[str, Any]]] = {}
    for collection in ("rooms", "walls", "openings", "furniture_instances", "cameras", "materials"):
        items = _list(document[collection], collection)
        if any(not isinstance(item, dict) for item in items):
            raise ModelValidationError(f"{collection} entries must be objects")
        collections[collection] = items
    _collection_ids(collections)

    wall_ids = {item["id"] for item in collections["walls"]}
    for index, item in enumerate(collections["walls"]):
        _validate_wall(item, index)
    room_rects: dict[str, tuple[float, float, float, float]] = {}
    for index, item in enumerate(collections["rooms"]):
        room_rects[item["id"]] = _validate_room(item, index, wall_ids)
    room_ids = set(room_rects)
    for index, item in enumerate(collections["openings"]):
        _validate_opening(item, index, wall_ids)
    for index, item in enumerate(collections["furniture_instances"]):
        _validate_furniture(item, index, room_ids, room_rects)
    for index, item in enumerate(collections["cameras"]):
        _validate_camera(item, index)
    for index, item in enumerate(collections["materials"]):
        _validate_material(item, index)
    return document

