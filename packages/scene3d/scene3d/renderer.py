"""Small deterministic perspective software renderer for the Stage 3 slice.

The renderer deliberately has no GPU or image dependency. It turns the v2
orthogonal model into a conservative box-based scene and writes PNGs using
only the Python standard library. It is a geometry smoke-test, not a
photo-realistic renderer.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import shutil
import struct
import tempfile
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spatial_core import ModelValidationError, canonical_hash, validate_model

MAX_NUMBER = 1_000_000_000.0
MAX_IMAGE_DIMENSION = 4096
FOV_DEG = 50.0
NEAR_MM = 10.0
FAR_MM = 100_000.0
_EPS = 1e-9


class RenderError(ValueError):
    """The model or render settings cannot be safely rasterized."""


def _finite(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RenderError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or abs(number) > MAX_NUMBER:
        raise RenderError(f"{path} must be finite and within +/-{int(MAX_NUMBER)}")
    return number


def _check_numbers(value: Any, path: str = "model") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _check_numbers(key, f"{path}.<key>")
            _check_numbers(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _check_numbers(nested, f"{path}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _finite(value, path)


def _unit(vector: tuple[float, float, float], path: str) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if not math.isfinite(length) or length < _EPS:
        raise RenderError(f"{path} must be a non-zero finite vector")
    return tuple(component / length for component in vector)


def _image_dimension(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RenderError(f"{path} must be an integer")
    if not 1 <= value <= MAX_IMAGE_DIMENSION:
        raise RenderError(f"{path} must be between 1 and {MAX_IMAGE_DIMENSION}")
    return value


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _sub(left: tuple[float, float, float], right: tuple[float, float, float]) -> tuple[float, float, float]:
    return left[0] - right[0], left[1] - right[1], left[2] - right[2]


def _cross(left: tuple[float, float, float], right: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


@dataclass(frozen=True)
class _Camera:
    position: tuple[float, float, float]
    forward: tuple[float, float, float]
    right: tuple[float, float, float]
    up: tuple[float, float, float]
    width: int
    height: int
    source_id: str


@dataclass(frozen=True)
class _Triangle:
    vertices: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    normal: tuple[float, float, float]
    color: tuple[int, int, int]
    object_id: str
    mask_value: int
    role: str


def _camera(model: dict[str, Any], width: int | None, height: int | None) -> _Camera:
    cameras = model["cameras"]
    if cameras:
        raw = cameras[0]
        def point(key: str) -> tuple[float, float, float]:
            value = raw[key]
            return tuple(_finite(value[axis], f"cameras[0].{key}.{axis}") for axis in ("x", "y", "z"))

        position, target = point("position"), point("look_at")
        forward = _unit(_sub(target, position), "camera look direction")
        supplied_up = _unit(point("up"), "camera up")
        right = _unit(_cross(forward, supplied_up), "camera right")
        up = _unit(_cross(right, forward), "camera up")
        image_size = raw["image_size"]
        output_width = _image_dimension(image_size["width"], "camera image width") if width is None else _image_dimension(width, "output width")
        output_height = _image_dimension(image_size["height"], "camera image height") if height is None else _image_dimension(height, "output height")
        source_id = str(raw["id"])
    else:
        raise RenderError("render requires an explicit camera in model.cameras")
    return _Camera(position, forward, right, up, output_width, output_height, source_id)


def _color(seed: str, role: str) -> tuple[int, int, int]:
    palette = {"floor": (202, 193, 177), "wall": (218, 220, 217), "ceiling": (238, 238, 232), "opening": (86, 137, 166)}
    if role in palette:
        return palette[role]
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return 75 + digest[0] % 125, 75 + digest[1] % 125, 75 + digest[2] % 125


def _box(
    object_id: str,
    role: str,
    bounds: tuple[float, float, float, float, float, float],
    color: tuple[int, int, int],
    mask_value: int,
) -> list[_Triangle]:
    x0, y0, x1, y1, z0, z1 = bounds
    p = {
        "000": (x0, y0, z0), "100": (x1, y0, z0), "010": (x0, y1, z0), "110": (x1, y1, z0),
        "001": (x0, y0, z1), "101": (x1, y0, z1), "011": (x0, y1, z1), "111": (x1, y1, z1),
    }
    faces = [
        (("000", "010", "110", "100"), (0.0, 0.0, -1.0)),
        (("001", "101", "111", "011"), (0.0, 0.0, 1.0)),
        (("000", "100", "101", "001"), (0.0, -1.0, 0.0)),
        (("010", "011", "111", "110"), (0.0, 1.0, 0.0)),
        (("000", "001", "011", "010"), (-1.0, 0.0, 0.0)),
        (("100", "110", "111", "101"), (1.0, 0.0, 0.0)),
    ]
    triangles: list[_Triangle] = []
    for corners, normal in faces:
        a, b, c, d = (p[key] for key in corners)
        triangles.extend((
            _Triangle((a, b, c), normal, color, object_id, mask_value, role),
            _Triangle((a, c, d), normal, color, object_id, mask_value, role),
        ))
    return triangles


def _plane(
    object_id: str,
    role: str,
    bounds: tuple[float, float, float, float, float],
    color: tuple[int, int, int],
    mask_value: int,
) -> list[_Triangle]:
    """Emit a zero-thickness horizontal plane at the supplied Z."""
    x0, y0, x1, y1, z = bounds
    normal = (0.0, 0.0, 1.0)
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    return [
        _Triangle((a, b, c), normal, color, object_id, mask_value, role),
        _Triangle((a, c, d), normal, color, object_id, mask_value, role),
    ]


def _union_rects(rects: list[tuple[str, float, float, float, float]]) -> list[tuple[str, float, float, float, float]]:
    """Return deterministic non-overlapping cells for axis-aligned rectangles."""
    if not rects:
        return []
    xs = sorted({value for _, x, y, width, height in rects for value in (x, x + width)})
    ys = sorted({value for _, x, y, width, height in rects for value in (y, y + height)})
    cells = []
    for x0, x1 in itertools.pairwise(xs):
        for y0, y1 in itertools.pairwise(ys):
            if x1 - x0 <= _EPS or y1 - y0 <= _EPS:
                continue
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            owner = next((item_id for item_id, x, y, width, height in rects
                          if x <= cx <= x + width and y <= cy <= y + height), None)
            if owner is not None:
                cells.append((owner, x0, y0, x1, y1))
    return cells


def _scene_triangles(model: dict[str, Any]) -> tuple[list[_Triangle], dict[str, int], dict[str, str]]:
    triangles: list[_Triangle] = []
    mask_values: dict[str, int] = {}
    roles: dict[str, str] = {}
    next_mask = 1

    def add(object_id: str, role: str, bounds: tuple[float, float, float, float, float, float], color_role: str) -> None:
        nonlocal next_mask
        if object_id not in mask_values:
            if next_mask > 65534:
                raise RenderError("scene has more than 65534 maskable objects")
            mask_values[object_id] = next_mask
            next_mask += 1
        roles[object_id] = role
        triangles.extend(_box(object_id, role, bounds, _color(object_id, color_role), mask_values[object_id]))

    walls_by_id = {wall["id"]: wall for wall in model["walls"]}
    groups: dict[str, list[dict[str, Any]]] = {}
    for room in model["rooms"]:
        groups.setdefault(str(room.get("merge_group_id") or room["id"]), []).append(room)
    for group_rooms in groups.values():
        # Keep every source room addressable even when its rectangle is fully
        # covered by another member of the deterministic union.
        for room in group_rooms:
            object_id = f"room:{room['id']}"
            if object_id not in mask_values:
                if next_mask > 65534:
                    raise RenderError("scene has more than 65534 maskable objects")
                mask_values[object_id] = next_mask
                next_mask += 1
            roles[object_id] = "room"
        room_rects = [(room["id"], *(float(value) for value in room["rect"])) for room in group_rooms]
        floor_cells = _union_rects(room_rects)
        for room_id, x0, y0, x1, y1 in floor_cells:
            object_id = f"room:{room_id}"
            add_triangles = _plane(object_id, "floor", (x0, y0, x1, y1, 0.0), _color(object_id, "floor"), mask_values[object_id])
            triangles.extend(add_triangles)
    for group_id, rooms in sorted(groups.items()):
        boundary_ids = {wall_id for room in rooms for wall_id in room.get("boundary_wall_ids", [])}
        tops = [float(walls_by_id[wall_id]["top_z"]) for wall_id in boundary_ids if wall_id in walls_by_id]
        if not tops:
            raise RenderError(f"room/merge group {group_id!r} has no boundary wall top_z")
        top = max(tops)
        ceiling_rects = [(room["id"], *(float(value) for value in room["rect"])) for room in rooms]
        for room_id, x0, y0, x1, y1 in _union_rects(ceiling_rects):
            object_id = f"ceiling:{group_id}"
            if object_id not in mask_values:
                if next_mask > 65534:
                    raise RenderError("scene has more than 65534 maskable objects")
                mask_values[object_id] = next_mask
                next_mask += 1
            roles[object_id] = "ceiling"
            triangles.extend(_plane(object_id, "ceiling", (x0, y0, x1, y1, top), _color(object_id, "ceiling"), mask_values[object_id]))
    openings_by_wall: dict[str, list[dict[str, Any]]] = {}
    for opening in model["openings"]:
        openings_by_wall.setdefault(opening["host_wall_id"], []).append(opening)
    for wall in model["walls"]:
        x, y = float(wall["x"]), float(wall["y"])
        half = float(wall["thickness"]) / 2.0
        length, bottom, top = float(wall["length"]), float(wall["bottom_z"]), float(wall["top_z"])
        wall_openings = openings_by_wall.get(wall["id"], [])
        axis_breaks = {0.0, length}
        for opening in wall_openings:
            axis_breaks.update((float(opening["offset"]), float(opening["offset"]) + float(opening["width"])))
        ordered = sorted(axis_breaks)
        for start, end in itertools.pairwise(ordered):
            if end - start <= _EPS:
                continue
            midpoint = (start + end) / 2.0
            active = [opening for opening in wall_openings if float(opening["offset"]) <= midpoint <= float(opening["offset"]) + float(opening["width"])]
            z_breaks = {bottom, top}
            for opening in active:
                z_breaks.update((float(opening["bottom_z"]), float(opening["bottom_z"]) + float(opening["height"])))
            for z_start, z_end in itertools.pairwise(sorted(z_breaks)):
                if z_end - z_start <= _EPS:
                    continue
                z_midpoint = (z_start + z_end) / 2.0
                if active and any(float(opening["bottom_z"]) <= z_midpoint <= float(opening["bottom_z"]) + float(opening["height"]) for opening in active):
                    continue
                if wall["axis"] == "h":
                    bounds = (x + start, y - half, x + end, y + half, z_start, z_end)
                else:
                    bounds = (x - half, y + start, x + half, y + end, z_start, z_end)
                add(f"wall:{wall['id']}", "wall", bounds, "wall")
    # Openings are represented by the absence of wall triangles. They retain
    # a non-zero manifest instance ID even though the void has no pixels.
    for opening in model["openings"]:
        # A void has no covered pixels, but retains a non-zero ID in the
        # instance table so downstream geometry consumers can resolve it.
        object_id = f"opening:{opening['id']}"
        if object_id not in mask_values:
            if next_mask > 65534:
                raise RenderError("scene has more than 65534 maskable objects")
            mask_values[object_id] = next_mask
            next_mask += 1
        roles[object_id] = "opening"
    for item in model["furniture_instances"]:
        if item.get("asset_ref", {}).get("kind") != "parametric":
            raise RenderError(f"unsupported furniture asset kind for {item['id']!r}")
        transform, dimensions = item["transform"], item["dimensions"]
        x, y, z = (float(transform[key]) for key in ("x", "y", "z"))
        width, depth, furniture_height = (float(dimensions[key]) for key in ("width", "depth", "height"))
        if round(float(transform["rotation_z"]) / 90.0) % 2:
            width, depth = depth, width
        add(f"furniture:{item['id']}", "furniture", (x, y, x + width, y + depth, z, z + furniture_height), "furniture")
    return triangles, mask_values, roles


def _png(data: bytes, width: int, height: int, color_type: int, bit_depth: int = 8) -> bytes:
    channels = {0: 1, 2: 3, 6: 4}[color_type]
    stride = width * channels * (bit_depth // 8)
    raw = b"".join(b"\x00" + data[row * stride:(row + 1) * stride] for row in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _rasterize(
    triangles: Iterable[_Triangle], camera: _Camera, width: int, height: int
) -> tuple[bytes, bytes, bytes, bytes, dict[str, dict[str, Any]], dict[str, int]]:
    triangles = list(triangles)
    if not triangles:
        raise RenderError("scene contains no renderable geometry")
    tan_vertical = math.tan(math.radians(FOV_DEG) / 2.0)
    tan_horizontal = tan_vertical * width / height

    def project(vertex: tuple[float, float, float]) -> tuple[float, float, float]:
        relative = _sub(vertex, camera.position)
        u, v = _dot(relative, camera.right), _dot(relative, camera.up)
        depth = _dot(_sub(vertex, camera.position), camera.forward)
        # Clipping intersections are generated exactly on the plane; allow
        # those boundary vertices through after polygon clipping.
        if depth < NEAR_MM - 1e-6 or depth > FAR_MM + 1e-6:
            raise RenderError("triangle intersects camera clipping range")
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
        return cx + (u / depth / tan_horizontal) * width / 2.0, cy - (v / depth / tan_vertical) * height / 2.0, depth

    def clip_polygon(vertices: list[tuple[float, float, float]], limit: float, keep_greater: bool) -> list[tuple[float, float, float]]:
        if not vertices:
            return []
        result: list[tuple[float, float, float]] = []
        previous = vertices[-1]
        previous_depth = _dot(_sub(previous, camera.position), camera.forward)
        previous_inside = previous_depth >= limit if keep_greater else previous_depth <= limit
        for current in vertices:
            current_depth = _dot(_sub(current, camera.position), camera.forward)
            current_inside = current_depth >= limit if keep_greater else current_depth <= limit
            if current_inside != previous_inside:
                denominator = current_depth - previous_depth
                if abs(denominator) > _EPS:
                    ratio = (limit - previous_depth) / denominator
                    result.append(tuple(previous[index] + ratio * (current[index] - previous[index]) for index in range(3)))
            if current_inside:
                result.append(current)
            previous, previous_depth, previous_inside = current, current_depth, current_inside
        return result

    projected = []
    for triangle in triangles:
        polygon = clip_polygon(list(triangle.vertices), NEAR_MM, True)
        polygon = clip_polygon(polygon, FAR_MM, False)
        if len(polygon) < 3:
            continue
        for index in range(1, len(polygon) - 1):
            clipped = _Triangle((polygon[0], polygon[index], polygon[index + 1]), triangle.normal, triangle.color, triangle.object_id, triangle.mask_value, triangle.role)
            projected.append((clipped, tuple(project(vertex) for vertex in clipped.vertices)))
    if not projected:
        raise RenderError("all geometry is outside camera clipping range")
    min_depth, max_depth = NEAR_MM, FAR_MM
    pixels = bytearray([248, 247, 243, 255] * (width * height))
    depth_buffer = [math.inf] * (width * height)
    normal_buffer = [(0.0, 0.0, 0.0)] * (width * height)
    mask_buffer = [0] * (width * height)
    object_boxes: dict[str, list[float]] = {}
    object_masks: dict[str, int] = {}

    for triangle, points in projected:
        x_values, y_values = [point[0] for point in points], [point[1] for point in points]
        left, right = max(0, math.floor(min(x_values))), min(width - 1, math.ceil(max(x_values)))
        top, bottom = max(0, math.floor(min(y_values))), min(height - 1, math.ceil(max(y_values)))
        if left > right or top > bottom:
            continue
        x0, y0, d0 = points[0]
        x1, y1, d1 = points[1]
        x2, y2, d2 = points[2]
        denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denominator) < _EPS:
            continue
        box = object_boxes.setdefault(triangle.object_id, [float(width), float(height), 0.0, 0.0])
        object_masks[triangle.object_id] = triangle.mask_value
        for py in range(top, bottom + 1):
            for px in range(left, right + 1):
                alpha = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denominator
                beta = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denominator
                gamma = 1.0 - alpha - beta
                if alpha < -_EPS or beta < -_EPS or gamma < -_EPS:
                    continue
                depth = alpha * d0 + beta * d1 + gamma * d2
                index = py * width + px
                if depth >= depth_buffer[index]:
                    continue
                depth_buffer[index] = depth
                color_index = index * 4
                pixels[color_index:color_index + 4] = bytes((*triangle.color, 255))
                normal_buffer[index] = triangle.normal
                mask_buffer[index] = triangle.mask_value
                box[0], box[1] = min(box[0], px), min(box[1], py)
                box[2], box[3] = max(box[2], px), max(box[3], py)

    color_png = _png(bytes(pixels), width, height, 6)
    boxes = {
        object_id: ({"x": int(box[0]), "y": int(box[1]), "width": int(box[2] - box[0] + 1), "height": int(box[3] - box[1] + 1), "mask_value": object_masks[object_id]} if box[2] >= box[0] and box[3] >= box[1] else {"visible": False, "mask_value": object_masks[object_id]})
        for object_id, box in object_boxes.items()
    }
    depth_raw = b"".join(struct.pack("<f", 0.0 if not math.isfinite(value) else value) for value in depth_buffer)
    normal_raw = b"".join(struct.pack("<fff", *normal) for normal in normal_buffer)
    mask_raw = b"".join(struct.pack("<I", value) for value in mask_buffer)
    return color_png, depth_raw, normal_raw, mask_raw, boxes, {"width": width, "height": height, "depth_min": min_depth, "depth_max": max_depth, "fov_deg": FOV_DEG, "near_mm": NEAR_MM, "far_mm": FAR_MM, "projection": "perspective"}


def render_model(model: dict[str, Any], output_dir: str | Path, *, width: int | None = None, height: int | None = None) -> dict[str, Any]:
    """Render a validated model and return the written manifest."""
    _check_numbers(model)
    try:
        validate_model(model)
    except (ModelValidationError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RenderError(str(exc)) from exc
    if model["status"] not in {"confirmed", "locked"}:
        raise RenderError("render requires a confirmed or locked model revision")
    if not model["rooms"] or not model["walls"]:
        raise RenderError("render requires at least one room and one wall")
    if not model["cameras"]:
        raise RenderError("render requires an explicit camera in model.cameras")
    camera = _camera(model, width, height)
    triangles, masks, roles = _scene_triangles(model)
    color, depth, normal, mask, boxes, projection = _rasterize(triangles, camera, camera.width, camera.height)
    output = Path(output_dir)
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=parent))
    try:
        payloads = {
            "color": ("color.png", color),
            "depth": ("depth.f32le", depth),
            "normal": ("normal.f32le", normal),
            "instance_mask": ("instance-mask.u32le", mask),
        }
        files: dict[str, str] = {}
        hashes: dict[str, str] = {}
        for name, (filename, payload) in payloads.items():
            path = staging / filename
            path.write_bytes(payload)
            files[name] = path.name
            hashes[name] = hashlib.sha256(payload).hexdigest()
        model_hash = canonical_hash(model)
        camera_hash = hashlib.sha256(json.dumps(model["cameras"][0], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        instance_table = {str(mask): {"id": object_id, "role": roles[object_id]} for object_id, mask in masks.items() if mask}
        manifest = {
            "schema_version": "3.0",
            "model_id": model["model_id"],
            "model_revision": model["revision"],
            "model_hash": model_hash,
            "camera": {"id": camera.source_id, "width": camera.width, "height": camera.height, "input_projection": "perspective", "projection": "cpu-perspective-v1", "fov_deg": FOV_DEG, "near_mm": NEAR_MM, "far_mm": FAR_MM, "world_axes": "X=east,Y=south,Z=up"},
            "camera_id": camera.source_id,
            "camera_hash": camera_hash,
            "render_profile": "cpu-perspective-v1",
            "renderer": {"name": "scene3d-stdlib", "version": "0.1.0", "adapter": "spatialmodel-orthogonal-v1"},
            "asset_hashes": {},
            "image_size": {"width": camera.width, "height": camera.height},
            "projection": projection,
            "objects": {object_id: {"role": roles[object_id], **boxes.get(object_id, {"visible": False, "mask_value": masks[object_id]})} for object_id in masks},
            "mask_values": masks,
            "files": files,
            "sha256": hashes,
            "artifact_hashes": hashes,
            "instance_table": instance_table,
            "channels": {
                "color": {"file": files["color"], "dtype": "uint8", "shape": [camera.height, camera.width, 4], "encoding": "RGBA PNG", "color_space": "sRGB"},
                "depth": {"file": files["depth"], "dtype": "float32", "endianness": "little", "shape": [camera.height, camera.width], "units": "mm", "background": 0.0},
                "normal": {"file": files["normal"], "dtype": "float32", "endianness": "little", "shape": [camera.height, camera.width, 3], "encoding": "world XYZ"},
                "instance_mask": {"file": files["instance_mask"], "dtype": "uint32", "endianness": "little", "shape": [camera.height, camera.width], "background": 0},
            },
            "opening_geometry": {opening["id"]: {"role": "void", "instance_id": f"opening:{opening['id']}", "mask_value": masks[f"opening:{opening['id']}"]} for opening in model["openings"]},
            "geometry_checks": {"coordinate_adapter": "identity-xy-z-up-v1", "projection": "perspective", "invalid_geometry": "hard-fail"},
            "determinism": {"seed": 0, "threads": 1},
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        (staging / "render-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    backup: Path | None = None
    try:
        if output.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.old.", dir=parent))
            backup.rmdir()
            os.replace(output, backup)
        os.replace(staging, output)
    except Exception:
        if output.exists() and backup is not None:
            shutil.rmtree(output)
        if backup is not None and backup.exists():
            os.replace(backup, output)
        if staging.exists():
            shutil.rmtree(staging)
        raise
    if backup is not None and backup.exists():
        shutil.rmtree(backup)
    return manifest
