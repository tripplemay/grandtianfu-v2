"""Minimal, deterministic validation for SpatialModel v2 documents."""

from __future__ import annotations

import math
from typing import Any


class ModelValidationError(ValueError):
    """Raised when a spatial model violates its storage contract."""


_REQUIRED_TOP_LEVEL = (
    "schema_version",
    "model_id",
    "revision",
    "units",
    "source",
    "rooms",
    "walls",
    "openings",
    "furniture_instances",
    "cameras",
    "materials",
)


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


def _unique_ids(items: list[dict[str, Any]], path: str) -> None:
    seen: set[str] = set()
    for index, item in enumerate(items):
        item_id = _id(item.get("id"), f"{path}[{index}].id")
        if item_id in seen:
            raise ModelValidationError(f"duplicate id {item_id!r} in {path}")
        seen.add(item_id)


def validate_model(document: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the original document for convenient composition."""
    if not isinstance(document, dict):
        raise ModelValidationError("model must be an object")
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in document]
    if missing:
        raise ModelValidationError(f"missing top-level fields: {', '.join(missing)}")
    if document["schema_version"] != "2.0":
        raise ModelValidationError("schema_version must be '2.0'")
    _id(document["model_id"], "model_id")
    revision = document["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ModelValidationError("revision must be an integer >= 1")
    if document["units"] != {"length": "mm", "angle": "deg"}:
        raise ModelValidationError("units must be millimetres and degrees")
    for collection in ("rooms", "walls", "openings", "furniture_instances", "cameras", "materials"):
        if not isinstance(document[collection], list):
            raise ModelValidationError(f"{collection} must be an array")
        if any(not isinstance(item, dict) for item in document[collection]):
            raise ModelValidationError(f"{collection} entries must be objects")
        _unique_ids(document[collection], collection)

    furniture = document["furniture_instances"]
    for index, item in enumerate(furniture):
        path = f"furniture_instances[{index}]"
        _id(item.get("catalog_id"), f"{path}.catalog_id")
        transform = item.get("transform")
        dimensions = item.get("dimensions")
        if not isinstance(transform, dict) or not isinstance(dimensions, dict):
            raise ModelValidationError(f"{path} needs transform and dimensions")
        for axis in ("x", "y", "z"):
            _finite_number(transform.get(axis), f"{path}.transform.{axis}")
        _finite_number(transform.get("rotation_z"), f"{path}.transform.rotation_z")
        for axis in ("width", "depth", "height"):
            _positive(dimensions.get(axis), f"{path}.dimensions.{axis}")
        confidence = item.get("confidence")
        if confidence is not None and not 0 <= _finite_number(confidence, f"{path}.confidence") <= 1:
            raise ModelValidationError(f"{path}.confidence must be between 0 and 1")
    return document

