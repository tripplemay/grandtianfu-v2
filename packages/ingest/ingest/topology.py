"""Deterministic manual topology review for immutable trace ingests."""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from typing import Any

from spatial_core import canonical_hash, validate_model

from .bitmap import BitmapError, canonical_json, load_bitmap

TOPOLOGY_VERSION = "manual-topology-0.1"
_EPS = 1e-6


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        numeric = math.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(numeric):
        raise BitmapError(f"invalid_topology: {path} must be a finite number")
    result = numeric
    if positive and result <= 0:
        raise BitmapError(f"invalid_topology: {path} must be > 0")
    return result


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise BitmapError(f"invalid_topology: {path} must be a non-empty display string")
    return value.strip()


def _object_ids(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise BitmapError(f"invalid_topology: {path} must be an array of object ids")
    result = [item.strip() for item in value]
    if len(result) != len(set(result)):
        raise BitmapError(f"invalid_topology: {path} must not contain duplicate ids")
    return result


def _opening_input(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) not in ({"host_wall_id", "kind", "offset", "width", "height", "bottom_z"},
                                                          {"id", "host_wall_id", "kind", "offset", "width", "height", "bottom_z"}):
        raise BitmapError(f"invalid_topology: openings[{index}] has unexpected fields")
    result = {
        "host_wall_id": _text(value["host_wall_id"], f"openings[{index}].host_wall_id"),
        "kind": _text(value["kind"], f"openings[{index}].kind"),
        "offset": _number(value["offset"], f"openings[{index}].offset"),
        "width": _number(value["width"], f"openings[{index}].width", positive=True),
        "height": _number(value["height"], f"openings[{index}].height", positive=True),
        "bottom_z": _number(value["bottom_z"], f"openings[{index}].bottom_z"),
    }
    if result["kind"] not in {"door", "window", "passage"}:
        raise BitmapError(f"invalid_topology: openings[{index}].kind must be door, window or passage")
    if "id" in value:
        result["id"] = _text(value["id"], f"openings[{index}].id")
    if result["offset"] < 0 or result["bottom_z"] < 0:
        raise BitmapError(f"invalid_topology: openings[{index}] offset and bottom_z must be >= 0")
    return result


def _merge_input(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) not in ({"room_ids"}, {"id", "room_ids"}):
        raise BitmapError(f"invalid_topology: merge_groups[{index}] has unexpected fields")
    room_ids = _object_ids(value.get("room_ids"), f"merge_groups[{index}].room_ids")
    if len(room_ids) < 2:
        raise BitmapError("invalid_topology: each merge group must contain at least two rooms")
    result = {"room_ids": room_ids}
    if "id" in value:
        result["id"] = _text(value["id"], f"merge_groups[{index}].id")
    return result


def topology_ingest_key(parent_ingest_id: str, parent_source_sha256: str, parent_model_hash: str,
                        openings: list[dict[str, Any]], merge_groups: list[dict[str, Any]],
                        reviewed_object_ids: list[str]) -> str:
    payload = {"version": TOPOLOGY_VERSION, "parent_ingest_id": parent_ingest_id,
               "parent_source_sha256": parent_source_sha256, "parent_model_hash": parent_model_hash,
               "openings": openings, "merge_groups": merge_groups,
               "reviewed_object_ids": reviewed_object_ids}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _touching(left: dict[str, Any], right: dict[str, Any]) -> bool:
    x, y, w, h = left["rect"]
    ox, oy, ow, oh = right["rect"]
    horizontal = (abs(x + w - ox) <= _EPS or abs(ox + ow - x) <= _EPS) and min(y + h, oy + oh) - max(y, oy) > _EPS
    vertical = (abs(y + h - oy) <= _EPS or abs(oy + oh - y) <= _EPS) and min(x + w, ox + ow) - max(x, ox) > _EPS
    return horizontal or vertical


def _shared_wall_ids(left: dict[str, Any], right: dict[str, Any], walls: dict[str, dict[str, Any]]) -> set[str]:
    """Return walls that lie on the actual shared side, not a coincident exterior side."""
    x, y, w, h = left["rect"]
    ox, oy, ow, oh = right["rect"]
    result: set[str] = set()
    if abs(x + w - ox) <= _EPS or abs(ox + ow - x) <= _EPS:
        coord = x + w if abs(x + w - ox) <= _EPS else x
        start, end = max(y, oy), min(y + h, oy + oh)
        for wall_id in set(left.get("boundary_wall_ids", [])) & set(right.get("boundary_wall_ids", [])):
            wall = walls.get(wall_id, {})
            if wall.get("axis") == "v" and abs(float(wall.get("x", 0)) - coord) <= _EPS and float(wall.get("y", 0)) <= start + _EPS and float(wall.get("y", 0)) + float(wall.get("length", 0)) >= end - _EPS:
                result.add(wall_id)
    if abs(y + h - oy) <= _EPS or abs(oy + oh - y) <= _EPS:
        coord = y + h if abs(y + h - oy) <= _EPS else y
        start, end = max(x, ox), min(x + w, ox + ow)
        for wall_id in set(left.get("boundary_wall_ids", [])) & set(right.get("boundary_wall_ids", [])):
            wall = walls.get(wall_id, {})
            if wall.get("axis") == "h" and abs(float(wall.get("y", 0)) - coord) <= _EPS and float(wall.get("x", 0)) <= start + _EPS and float(wall.get("x", 0)) + float(wall.get("length", 0)) >= end - _EPS:
                result.add(wall_id)
    return result


def _opening_connects_rooms(opening: dict[str, Any], left: dict[str, Any], right: dict[str, Any], walls: dict[str, dict[str, Any]]) -> bool:
    wall_id = opening["host_wall_id"]
    wall = walls.get(wall_id)
    if wall is None or wall_id not in _shared_wall_ids(left, right, walls):
        return False
    x, y, w, h = left["rect"]
    ox, oy, ow, oh = right["rect"]
    if wall.get("axis") == "v":
        shared_start, shared_end = max(y, oy), min(y + h, oy + oh)
        wall_start = float(wall["y"])
    else:
        shared_start, shared_end = max(x, ox), min(x + w, ox + ow)
        wall_start = float(wall["x"])
    opening_start = wall_start + float(opening["offset"])
    opening_end = opening_start + float(opening["width"])
    return min(opening_end, shared_end) - max(opening_start, shared_start) > _EPS


def _validate_review_ids(parent: dict[str, Any], openings: list[dict[str, Any]], groups: list[dict[str, Any]], reviewed: Any) -> list[str]:
    ids = _object_ids(reviewed, "reviewed_object_ids")
    known = {item["id"] for key in ("rooms", "walls", "openings") for item in parent.get(key, [])}
    known.update(item["id"] for item in openings if "id" in item)
    known.update(item["id"] for item in groups if "id" in item)
    if not known.issuperset(ids):
        unknown = sorted(set(ids) - known)
        raise BitmapError(f"invalid_topology: reviewed_object_ids references unknown objects: {unknown}")
    required = {item["id"] for key in ("rooms", "walls", "openings") for item in parent.get(key, [])}
    required.update(item["id"] for item in openings)
    required.update(item["id"] for item in groups)
    if not required.issubset(ids):
        raise BitmapError("invalid_topology: every parent room, wall and opening must be reviewed")
    return ids


def topology_ingest_from_parent(data: bytes, *, parent_ingest_id: str, parent_source_sha256: str,
                                parent_model: dict[str, Any], openings: Any, merge_groups: Any,
                                reviewed_object_ids: Any) -> tuple[dict[str, Any], Any]:
    asset = load_bitmap(data)
    if asset.sha256 != parent_source_sha256:
        raise BitmapError("invalid_topology: parent source hash does not match source artifact")
    if parent_model.get("source", {}).get("kind") != "bitmap":
        raise BitmapError("invalid_topology: parent ingest must be a bitmap")
    if parent_model.get("source", {}).get("sha256") != parent_source_sha256:
        raise BitmapError("invalid_topology: parent model source hash does not match source artifact")
    if "manual_trace_requires_topology_review" not in {item.get("code") for item in parent_model.get("ingest", {}).get("hard_blockers", [])}:
        raise BitmapError("invalid_topology: parent must be a manual trace draft awaiting topology review")
    checked_openings = [_opening_input(item, index) for index, item in enumerate(openings if isinstance(openings, list) else [])]
    checked_groups = [_merge_input(item, index) for index, item in enumerate(merge_groups if isinstance(merge_groups, list) else [])]
    if not isinstance(openings, list) or len(checked_openings) > 128 or not isinstance(merge_groups, list) or len(checked_groups) > 64:
        raise BitmapError("invalid_topology: openings and merge_groups must be bounded arrays")
    parent_walls = {item["id"]: item for item in parent_model.get("walls", [])}
    parent_rooms = {item["id"]: item for item in parent_model.get("rooms", [])}
    existing_openings = list(parent_model.get("openings", []))
    known_ids = {item["id"] for key in ("rooms", "walls", "openings") for item in parent_model.get(key, [])}
    new_ids: set[str] = set()
    for index, opening in enumerate(checked_openings, 1):
        opening.setdefault("id", f"topology-opening-{index}")
        if opening["id"] in known_ids or opening["id"] in new_ids:
            raise BitmapError(f"invalid_topology: duplicate opening id {opening['id']!r}")
        new_ids.add(opening["id"])
        wall = parent_walls.get(opening["host_wall_id"])
        if wall is None:
            raise BitmapError(f"invalid_topology: openings[{index - 1}] references unknown wall")
        if opening["offset"] + opening["width"] > float(wall["length"]) + _EPS:
            raise BitmapError(f"invalid_topology: opening {opening['id']!r} exceeds host wall span")
        if opening["bottom_z"] < float(wall.get("bottom_z", 0)) - _EPS or opening["bottom_z"] + opening["height"] > float(wall["top_z"]) + _EPS:
            raise BitmapError(f"invalid_topology: opening {opening['id']!r} exceeds host wall height")
        for other in existing_openings + checked_openings[:index - 1]:
            if other.get("host_wall_id") == opening["host_wall_id"]:
                spans = min(opening["offset"] + opening["width"], float(other["offset"]) + float(other["width"])) - max(opening["offset"], float(other["offset"]))
                levels = min(opening["bottom_z"] + opening["height"], float(other.get("bottom_z", 0)) + float(other["height"])) - max(opening["bottom_z"], float(other.get("bottom_z", 0)))
                if spans > _EPS and levels > _EPS:
                    raise BitmapError(f"invalid_topology: opening {opening['id']!r} overlaps another opening")
        opening.update({"provenance": "manual_topology", "confidence": 0.9, "needs_review": True,
                        "height_provenance": {"source": "manual_topology", "value_mm": opening["height"], "confidence": 0.9, "needs_review": True}})
    group_ids: set[str] = set()
    assigned: dict[str, str] = {}
    for index, group in enumerate(checked_groups, 1):
        group.setdefault("id", f"topology-merge-{index}")
        if group["id"] in group_ids or group["id"] in {room.get("merge_group_id") for room in parent_rooms.values()}:
            raise BitmapError(f"invalid_topology: duplicate merge group id {group['id']!r}")
        group_ids.add(group["id"])
        for room_id in group["room_ids"]:
            if room_id not in parent_rooms:
                raise BitmapError(f"invalid_topology: merge group references unknown room {room_id!r}")
            if room_id in assigned or parent_rooms[room_id].get("merge_group_id") is not None:
                raise BitmapError(f"invalid_topology: room {room_id!r} belongs to more than one merge group")
            assigned[room_id] = group["id"]
        for left_id, right_id in zip(group["room_ids"], group["room_ids"][1:]):
            left, right = parent_rooms[left_id], parent_rooms[right_id]
            shared = _shared_wall_ids(left, right, parent_walls)
            for opening in checked_openings:
                if opening["host_wall_id"] in shared and not _opening_connects_rooms(opening, left, right, parent_walls):
                    raise BitmapError(f"invalid_topology: opening {opening['id']!r} does not intersect the shared boundary")
            explicit = any(_opening_connects_rooms(item, left, right, parent_walls) for item in checked_openings)
            if not shared and not explicit:
                raise BitmapError(f"invalid_topology: merge rooms {left_id!r} and {right_id!r} are not adjacent")
    reviewed = _validate_review_ids(parent_model, checked_openings, checked_groups, reviewed_object_ids)
    topology_id = topology_ingest_key(parent_ingest_id, parent_source_sha256, canonical_hash(parent_model),
                                      checked_openings, checked_groups, reviewed)
    model = deepcopy(parent_model)
    model["model_id"] = f"topology-{topology_id[:24]}"
    model["revision"] = 1
    model["status"] = "draft"
    model["source"] = {**model["source"], "provenance": "manual_topology", "parent_ingest_id": parent_ingest_id}
    model["openings"] = existing_openings + checked_openings
    for room in model["rooms"]:
        if room["id"] in assigned:
            room["merge_group_id"] = assigned[room["id"]]
            room["topology_provenance"] = "manual_topology"
            room["topology_confidence"] = 0.9
    ingest = model.setdefault("ingest", {})
    ingest_id = topology_id
    ingest["ingest_id"] = ingest_id
    ingest["algorithm_version"] = TOPOLOGY_VERSION
    ingest["parameters_hash"] = topology_id
    ingest["source_sha256"] = parent_source_sha256
    ingest["parent_ingest_id"] = parent_ingest_id
    ingest["topology"] = {"version": TOPOLOGY_VERSION, "parent_ingest_id": parent_ingest_id,
                           "parent_source_sha256": parent_source_sha256, "parent_model_hash": canonical_hash(parent_model),
                           "openings": checked_openings, "merge_groups": checked_groups,
                           "reviewed_object_ids": reviewed}
    ingest["evidence"] = {**ingest.get("evidence", {}), "topology_review": ingest["topology"]}
    ingest["requires_human_review"] = True
    model["confidence"] = min(float(model.get("confidence", 0.75)), 0.9)
    try:
        validate_model(model)
    except ValueError as exc:
        raise BitmapError(f"invalid_topology_geometry: {exc}") from exc
    return model, asset
