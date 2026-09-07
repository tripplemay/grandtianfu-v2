"""Deterministic manual rectangle tracing for immutable bitmap ingests."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from spatial_core import canonical_hash, validate_model

from .bitmap import BitmapError, canonical_json, load_bitmap
from .worker import _write_outputs

TRACE_VERSION = "manual-trace-0.1"
_EPS = 1e-9


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise BitmapError(f"invalid_trace: {path} must be a finite number")
    result = float(value)
    if positive and result <= 0:
        raise BitmapError(f"invalid_trace: {path} must be > 0")
    return result


def _bbox(value: Any, width: int, height: int) -> list[int]:
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise BitmapError("invalid_trace: bbox must contain four integer pixel values")
    x, y, w, h = value
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise BitmapError("invalid_trace: bbox must be inside the normalized source image")
    return [x, y, w, h]


def _rooms(value: Any, bbox: list[int], width: int, height: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise BitmapError("invalid_trace: rooms must contain between 1 and 64 entries")
    bx, by, bw, bh = bbox
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"name", "kind", "rect"}:
            raise BitmapError(f"invalid_trace: rooms[{index}] must contain name, kind and rect")
        name, kind = item["name"], item["kind"]
        for field, candidate in (("name", name), ("kind", kind)):
            if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 120 or any(ord(char) < 32 for char in candidate):
                raise BitmapError(f"invalid_trace: rooms[{index}].{field} must be a display string")
        name = name.strip()
        kind = kind.strip()
        if name in names:
            raise BitmapError("invalid_trace: room names must be unique")
        names.add(name)
        rect = item["rect"]
        if not isinstance(rect, list) or len(rect) != 4:
            raise BitmapError(f"invalid_trace: rooms[{index}].rect must be [x, y, width, height]")
        x, y, w, h = (_number(rect[pos], f"rooms[{index}].rect[{pos}]", positive=pos >= 2) for pos in range(4))
        if x < bx or y < by or x + w > bx + bw or y + h > by + bh or x + w > width or y + h > height:
            raise BitmapError(f"invalid_trace: rooms[{index}].rect must be inside bbox")
        result.append({"name": name, "kind": kind, "rect": [x, y, w, h]})
    for index, left in enumerate(result):
        x, y, w, h = left["rect"]
        for other in result[index + 1:]:
            ox, oy, ow, oh = other["rect"]
            if min(x + w, ox + ow) - max(x, ox) > 0 and min(y + h, oy + oh) - max(y, oy) > 0:
                raise BitmapError("invalid_trace: room rectangles must not overlap")
    return result


def trace_ingest_key(parent_ingest_id: str, parent_source_sha256: str, bbox: list[int], rooms: list[dict[str, Any]],
                     wall_thickness_mm: float, wall_height_mm: float, *, parent_model_hash: str = "",
                     mm_per_pixel: float = 0.0) -> str:
    params = {"trace_version": TRACE_VERSION, "parent_ingest_id": parent_ingest_id,
              "parent_source_sha256": parent_source_sha256, "bbox": bbox, "rooms": rooms,
              "wall_thickness_mm": wall_thickness_mm, "wall_height_mm": wall_height_mm,
              "parent_model_hash": parent_model_hash, "mm_per_pixel": mm_per_pixel}
    return hashlib.sha256(canonical_json(params).encode("utf-8")).hexdigest()


def _walls(rooms: list[dict[str, Any]], scale: float, thickness: float, height: float) -> tuple[list[dict[str, Any]], list[list[str]]]:
    segments: list[tuple[str, float, float, float]] = []
    room_edges: list[list[tuple[str, float, float, float]]] = []
    for room in rooms:
        x, y, w, h = room["rect"]
        edges = [("h", y, x, x + w), ("h", y + h, x, x + w), ("v", x, y, y + h), ("v", x + w, y, y + h)]
        room_edges.append(edges)
        segments.extend(edges)
    merged: list[tuple[str, float, float, float]] = []
    for axis, coord, start, end in sorted(segments, key=lambda item: (item[0], item[1], item[2], item[3])):
        if (merged and merged[-1][0] == axis and abs(merged[-1][1] - coord) <= _EPS
                and start <= merged[-1][3] + _EPS):
            previous = merged[-1]
            merged[-1] = (axis, coord, previous[2], max(previous[3], end))
        else:
            merged.append((axis, coord, start, end))
    walls: list[dict[str, Any]] = []
    for index, (axis, coord, start, end) in enumerate(merged, 1):
        x, y = (start, coord) if axis == "h" else (coord, start)
        pixel_length = end - start
        walls.append({"id": f"manual-wall-{index}", "axis": axis, "x": x * scale, "y": y * scale,
                      "length": pixel_length * scale, "thickness": thickness, "bottom_z": 0.0, "top_z": height,
                      "provenance": "manual_trace", "confidence": 0.75,
                      "dimension_provenance": {"source": "manual_trace", "pixel_value": pixel_length,
                                               "world_value_mm": pixel_length * scale, "confidence": 0.75,
                                               "needs_review": True},
                      "height_provenance": {"source": "user_entered", "value_mm": height, "confidence": 1.0,
                                            "needs_review": True}})
    boundaries: list[list[str]] = []
    for edges in room_edges:
        refs: list[str] = []
        for axis, coord, start, end in edges:
            for index, (wax, wcoord, wstart, wend) in enumerate(merged):
                if wax == axis and abs(wcoord - coord) <= _EPS and wstart <= start + _EPS and wend >= end - _EPS:
                    refs.append(walls[index]["id"])
        boundaries.append(refs)
    return walls, boundaries


def trace_ingest(data: bytes, *, parent_ingest_id: str, parent_source_sha256: str, parent_model: dict[str, Any],
                 bbox: Any, rooms: Any, wall_thickness_mm: Any, wall_height_mm: Any,
                 filename: str = "source") -> tuple[dict[str, Any], Any]:
    """Public convenience wrapper used by direct worker callers and tests."""
    return trace_ingest_from_parent(data, parent_ingest_id=parent_ingest_id,
                                    parent_source_sha256=parent_source_sha256, parent_model=parent_model,
                                    bbox=bbox, rooms=rooms, wall_thickness_mm=wall_thickness_mm,
                                    wall_height_mm=wall_height_mm)


def trace_ingest_from_parent(data: bytes, *, parent_ingest_id: str, parent_source_sha256: str,
                             parent_model: dict[str, Any], bbox: Any, rooms: Any,
                             wall_thickness_mm: Any, wall_height_mm: Any) -> tuple[dict[str, Any], Any]:
    asset = load_bitmap(data)
    if asset.sha256 != parent_source_sha256:
        raise BitmapError("invalid_trace: parent source hash does not match source artifact")
    scale = _number(parent_model.get("ingest", {}).get("mm_per_pixel"), "parent scale", positive=True)
    checked_bbox = _bbox(bbox, asset.width, asset.height)
    checked_rooms = _rooms(rooms, checked_bbox, asset.width, asset.height)
    thickness = _number(wall_thickness_mm, "wall_thickness_mm", positive=True)
    height = _number(wall_height_mm, "wall_height_mm", positive=True)
    trace_id = trace_ingest_key(parent_ingest_id, parent_source_sha256, checked_bbox, checked_rooms, thickness, height,
                                parent_model_hash=canonical_hash(parent_model), mm_per_pixel=scale)
    walls, boundaries = _walls(checked_rooms, scale, thickness, height)
    model_rooms = []
    for index, room in enumerate(checked_rooms, 1):
        x, y, w, h = room["rect"]
        rect = [x * scale, y * scale, w * scale, h * scale]
        model_rooms.append({"id": f"manual-room-{index}", "name": room["name"], "kind": room["kind"], "rect": rect,
                            "boundary_wall_ids": boundaries[index - 1], "provenance": "manual_trace", "confidence": 0.75,
                            "dimension_provenance": {"source": "manual_trace", "pixel_rect": room["rect"],
                                                     "world_rect_mm": rect, "source_asset_sha256": parent_source_sha256,
                                                     "confidence": 0.75, "needs_review": True}})
    parent_blockers = list(parent_model.get("ingest", {}).get("hard_blockers", []))
    model = {"schema_version": "2.0", "profile": "orthogonal_v1", "model_id": f"trace-{trace_id[:24]}",
             "revision": 1, "status": "draft", "units": {"length": "mm", "angle": "deg"},
             "coordinates": {"origin": "normalized_bitmap_top_left", "handedness": "right"},
             "source": {"asset_id": f"sha256:{parent_source_sha256}", "kind": "bitmap", "sha256": parent_source_sha256,
                        "provenance": "manual_trace", "parent_ingest_id": parent_ingest_id},
             "confidence": 0.75, "rooms": model_rooms, "walls": walls, "openings": [],
             "furniture_instances": [], "cameras": [], "materials": [],
             "ingest": {"ingest_id": trace_id, "trace": {"version": TRACE_VERSION, "parent_ingest_id": parent_ingest_id,
                         "parent_source_sha256": parent_source_sha256, "parent_model_hash": canonical_hash(parent_model),
                         "bbox": checked_bbox, "rooms": checked_rooms, "wall_thickness_mm": thickness,
                         "wall_height_mm": height, "superseded_blockers": parent_blockers},
                       "algorithm_version": TRACE_VERSION, "parameters_hash": trace_id, "media_type": asset.media_type,
                       "parent_ingest_id": parent_ingest_id,
                       "source_sha256": parent_source_sha256, "pixel_size": {"width": asset.width, "height": asset.height},
                       "mm_per_pixel": scale, "scale_status": "parent_user_supplied", "calibration": parent_model["ingest"].get("calibration", {}),
                       "preprocessing": {**asset.normalization, "source_sha256": parent_source_sha256, "trace_full_source": True},
                       "candidates": [], "evidence": {"parent_ingest_id": parent_ingest_id},
                       "warnings": [], "hard_blockers": [{"code": "manual_trace_requires_topology_review",
                           "message": "Manual room trace has no reviewed doors, windows or merge topology", "needs_review": True}],
                       "requires_human_review": True}}
    try:
        validate_model(model)
    except ValueError as exc:
        raise BitmapError(f"invalid_trace_geometry: {exc}") from exc
    return model, asset


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a manual rectangle trace")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent-ingest-id", required=True)
    parser.add_argument("--parent-source-sha256", required=True)
    parser.add_argument("--parent-model", type=Path, required=True)
    parser.add_argument("--bbox", required=True)
    parser.add_argument("--rooms", required=True)
    parser.add_argument("--wall-thickness-mm", required=True, type=float)
    parser.add_argument("--wall-height-mm", required=True, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        parent_model = json.loads(args.parent_model.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        model, asset = trace_ingest_from_parent(args.input.read_bytes(), parent_ingest_id=args.parent_ingest_id,
                                                parent_source_sha256=args.parent_source_sha256, parent_model=parent_model,
                                                bbox=json.loads(args.bbox), rooms=json.loads(args.rooms),
                                                wall_thickness_mm=args.wall_thickness_mm, wall_height_mm=args.wall_height_mm)
        _write_outputs(args.output, model, asset, "source", source_data=args.input.read_bytes(), source_media_type=asset.media_type)
        print(json.dumps({"ingest_id": model["ingest"]["ingest_id"], "model_id": model["model_id"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, BitmapError) as exc:
        print(f"trace worker error: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
