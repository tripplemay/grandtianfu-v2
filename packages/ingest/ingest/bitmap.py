"""PNG/JPEG intake and deterministic candidate draft generation.

This module intentionally produces a reviewable draft only.  It does not
claim that image bounds are measured architectural boundaries and never
changes the draft status to ``confirmed``.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from dataclasses import dataclass
from typing import Any

from spatial_core import validate_model


class BitmapError(ValueError):
    """Raised when a bitmap is unsupported or cannot produce a draft."""


@dataclass(frozen=True)
class BitmapAsset:
    data: bytes
    media_type: str
    width: int
    height: int
    sha256: str


def _u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise BitmapError("truncated bitmap header")
    return struct.unpack_from(">I", data, offset)[0]


def _read_png(data: bytes) -> tuple[int, int, list[int]]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise BitmapError("invalid PNG signature")
    offset = 8
    width = height = bit_depth = color_type = None
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = _u32(data, offset)
        end = offset + 12 + length
        if end > len(data):
            raise BitmapError("truncated PNG chunk")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = _u32(data, offset + 8 + length)
        actual_crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise BitmapError("PNG chunk CRC mismatch")
        offset = end
        if kind == b"IHDR":
            if length != 13:
                raise BitmapError("invalid PNG IHDR")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if not width or not height:
                raise BitmapError("PNG dimensions must be positive")
            if bit_depth != 8 or color_type not in (0, 2, 4, 6):
                raise BitmapError("PNG requires 8-bit grayscale, RGB, or RGBA")
            if compression != 0 or filtering != 0 or interlace != 0:
                raise BitmapError("PNG compression/filter/interlace mode unsupported")
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if width is None or height is None:
        raise BitmapError("PNG is missing IHDR")
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise BitmapError("invalid PNG pixel stream") from exc
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise BitmapError("PNG pixel stream has unexpected length")
    rows: list[bytes] = []
    cursor = 0
    previous = bytes(stride)
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + stride]
        cursor += stride
        row = bytearray(encoded)
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (value + left) & 255
            elif filter_type == 2:
                row[index] = (value + up) & 255
            elif filter_type == 3:
                row[index] = (value + ((left + up) // 2)) & 255
            elif filter_type == 4:
                prediction = left + up - upper_left
                distances = (abs(prediction - left), abs(prediction - up), abs(prediction - upper_left))
                row[index] = (value + (left if distances[0] <= distances[1] and distances[0] <= distances[2] else up if distances[1] <= distances[2] else upper_left)) & 255
            elif filter_type != 0:
                raise BitmapError(f"unsupported PNG filter {filter_type}")
        decoded = bytes(row)
        rows.append(decoded)
        previous = decoded
    # Downsample deterministically; candidates need signal statistics, not a full image copy.
    grayscale: list[int] = []
    for row in rows:
        for pixel in range(width):
            base = pixel * channels
            if color_type == 0:
                value = row[base]
            elif color_type == 2:
                r, g, b = row[base : base + 3]
                value = (299 * r + 587 * g + 114 * b) // 1000
            elif color_type == 4:
                luminance, alpha = row[base : base + 2]
                value = (luminance * alpha + 255 * (255 - alpha)) // 255
            else:
                r, g, b, alpha = row[base : base + 4]
                value = ((299 * r + 587 * g + 114 * b) * alpha + 255000 * (255 - alpha)) // 255000
            grayscale.append(value)
    return width, height, grayscale


def _read_jpeg(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise BitmapError("invalid JPEG signature")
    index = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while index + 3 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        marker = data[index]
        index += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        length = struct.unpack_from(">H", data, index)[0]
        if length < 2 or index + length > len(data):
            raise BitmapError("truncated JPEG segment")
        if marker in sof:
            if length < 7:
                raise BitmapError("invalid JPEG frame")
            height, width = struct.unpack_from(">HH", data, index + 3)
            if not width or not height:
                raise BitmapError("JPEG dimensions must be positive")
            return width, height
        index += length
    raise BitmapError("JPEG frame dimensions not found")


def load_bitmap(data: bytes, filename: str = "upload") -> BitmapAsset:
    """Validate a PNG/JPEG upload and return immutable identifying metadata."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise BitmapError("bitmap upload must be non-empty bytes")
    data = bytes(data)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height, _ = _read_png(data)
        media_type = "image/png"
    elif data.startswith(b"\xff\xd8"):
        width, height = _read_jpeg(data)
        media_type = "image/jpeg"
    else:
        raise BitmapError("only PNG and JPEG uploads are supported")
    if width * height > 20_000_000:
        raise BitmapError("bitmap exceeds 20 megapixels")
    return BitmapAsset(data, media_type, width, height, hashlib.sha256(data).hexdigest())


def preprocess_bitmap(asset: BitmapAsset) -> dict[str, Any]:
    """Extract deterministic grayscale statistics and dark-line candidates."""
    if asset.media_type == "image/png":
        width, height, pixels = _read_png(asset.data)
        mean = sum(pixels) / len(pixels)
        threshold = min(220.0, max(32.0, mean * 0.72))
        dark = [value < threshold for value in pixels]
        row_scores = [sum(dark[row * width : (row + 1) * width]) / width for row in range(height)]
        col_scores = [sum(dark[col::width]) / height for col in range(width)]
        rows = [index for index, score in enumerate(row_scores) if score >= 0.55]
        cols = [index for index, score in enumerate(col_scores) if score >= 0.55]
        return {
            "decoder": "builtin-png-8bit",
            "mean_luma": round(mean, 6),
            "dark_threshold": round(threshold, 6),
            "dark_ratio": round(sum(dark) / len(dark), 6),
            "line_candidates": {
                "horizontal_rows_px": rows[:256],
                "vertical_columns_px": cols[:256],
            },
            "provenance": "deterministic_pixel_scan",
            "confidence": 0.35,
        }
    return {
        "decoder": "jpeg-header-only",
        "line_candidates": {"horizontal_rows_px": [], "vertical_columns_px": []},
        "provenance": "jpeg_dimensions_only",
        "confidence": 0.1,
    }


def ingest_bitmap(
    data: bytes,
    *,
    filename: str = "upload",
    model_id: str | None = None,
    revision: int = 1,
    mm_per_pixel: float = 10.0,
) -> dict[str, Any]:
    """Create a reviewable SpatialModel draft from a bitmap upload.

    The image bounds are a candidate room, not a measurement.  ``mm_per_pixel``
    is therefore explicitly recorded as an inferred calibration and the output
    remains ``draft`` until a human supplies/validates dimensions and topology.
    """
    if isinstance(mm_per_pixel, bool) or not isinstance(mm_per_pixel, (int, float)) or not math.isfinite(float(mm_per_pixel)) or mm_per_pixel <= 0:
        raise BitmapError("mm_per_pixel must be a finite number > 0")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise BitmapError("revision must be an integer >= 1")
    asset = load_bitmap(data, filename)
    preprocessing = preprocess_bitmap(asset)
    width_mm = round(asset.width * float(mm_per_pixel), 6)
    height_mm = round(asset.height * float(mm_per_pixel), 6)
    min_dimension = min(width_mm, height_mm)
    # Keep the provisional wall geometrically bounded even for tiny test images.
    wall_thickness = min(200.0, max(1.0, min_dimension * 0.02), min_dimension * 0.45)
    wall_top = 2800.0
    prefix = model_id or f"bitmap-{asset.sha256[:12]}"
    source_provenance = "user_upload"
    model: dict[str, Any] = {
        "schema_version": "2.0",
        "profile": "orthogonal_v1",
        "model_id": prefix,
        "revision": revision,
        "status": "draft",
        "units": {"length": "mm", "angle": "deg"},
        "coordinates": {"origin": "project_south_west_corner", "handedness": "right"},
        "source": {
            "asset_id": filename or f"upload-{asset.sha256[:12]}",
            "kind": "bitmap",
            "sha256": asset.sha256,
            "provenance": source_provenance,
        },
        "confidence": 0.2,
        "rooms": [{
            "id": "room-candidate-1", "name": "待校核房间", "kind": "unknown",
            "rect": [0.0, 0.0, width_mm, height_mm],
            "boundary_wall_ids": ["wall-n", "wall-s", "wall-w", "wall-e"],
            "provenance": "image_bounds_candidate", "confidence": 0.2,
        }],
        "walls": [
            {"id": "wall-n", "axis": "h", "x": 0.0, "y": 0.0, "length": width_mm, "thickness": wall_thickness, "bottom_z": 0.0, "top_z": wall_top, "provenance": "image_bounds_candidate", "confidence": 0.2},
            {"id": "wall-s", "axis": "h", "x": 0.0, "y": height_mm, "length": width_mm, "thickness": wall_thickness, "bottom_z": 0.0, "top_z": wall_top, "provenance": "image_bounds_candidate", "confidence": 0.2},
            {"id": "wall-w", "axis": "v", "x": 0.0, "y": 0.0, "length": height_mm, "thickness": wall_thickness, "bottom_z": 0.0, "top_z": wall_top, "provenance": "image_bounds_candidate", "confidence": 0.2},
            {"id": "wall-e", "axis": "v", "x": width_mm, "y": 0.0, "length": height_mm, "thickness": wall_thickness, "bottom_z": 0.0, "top_z": wall_top, "provenance": "image_bounds_candidate", "confidence": 0.2},
        ],
        "openings": [],
        "furniture_instances": [],
        "cameras": [],
        "materials": [],
        "ingest": {
            "filename": filename,
            "media_type": asset.media_type,
            "pixel_size": {"width": asset.width, "height": asset.height},
            "mm_per_pixel": float(mm_per_pixel),
            "calibration": {"value": float(mm_per_pixel), "provenance": "caller_default_or_input", "confidence": 0.1},
            "preprocessing": preprocessing,
            "candidates": [{"id": "room-candidate-1", "kind": "room_bounds", "provenance": "image_bounds_candidate", "confidence": 0.2}],
            "requires_human_review": True,
        },
    }
    validate_model(model)
    return model


def canonical_json(model: dict[str, Any]) -> str:
    """Stable JSON helper for persisted ingest artifacts and tests."""
    return json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
