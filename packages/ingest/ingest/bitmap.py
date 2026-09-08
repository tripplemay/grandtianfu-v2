"""Bounded, evidence-preserving CPU recognition of orthogonal bitmap plans."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from PIL import __version__ as pillow_version
from spatial_core import validate_model

ALGORITHM_VERSION = "orthogonal-cv-0.2"
# Keep ROI identities separate from pre-v2 keys whose coordinate contract was
# local-to-parent and could therefore reuse a drifting artifact.
ROI_KEY_VERSION = "roi-crop-v2"
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_SIDE = 12_000
MAX_PIXELS = 50_000_000


class BitmapError(ValueError):
    """Unsupported, corrupt, or insufficiently constrained bitmap input."""


@dataclass(frozen=True)
class BitmapAsset:
    data: bytes
    media_type: str
    width: int
    height: int
    sha256: str
    normalized_png: bytes
    normalization: dict[str, Any]


def canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _scale(value: float | None) -> float:
    if value is None:
        raise BitmapError("scale_required: explicit mm_per_pixel is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise BitmapError("invalid_scale: mm_per_pixel must be finite and > 0")
    return float(value)


@lru_cache(maxsize=1)
def _ocr_runtime() -> dict[str, Any]:
    executable = shutil.which("tesseract")
    if not executable:
        return {"engine": None, "version": None}
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5, check=False)
        version = result.stdout.splitlines()[0] if result.returncode == 0 and result.stdout else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        version = "unavailable"
    return {"engine": "tesseract", "version": version}


def ingest_key(data: bytes, mm_per_pixel: float | None) -> str:
    parameters = {"source_sha256": hashlib.sha256(data).hexdigest(), "mm_per_pixel": _scale(mm_per_pixel),
                  "algorithm_version": ALGORITHM_VERSION, "pillow_version": pillow_version,
                  "opencv_version": cv2.__version__, "numpy_version": np.__version__, "ocr": _ocr_runtime()}
    return hashlib.sha256(canonical_json(parameters).encode()).hexdigest()


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()


def _orientation_transform(orientation: int, width: int, height: int) -> list[list[int]]:
    transforms = {
        1: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        2: [[-1, 0, width - 1], [0, 1, 0], [0, 0, 1]],
        3: [[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]],
        4: [[1, 0, 0], [0, -1, height - 1], [0, 0, 1]],
        5: [[0, 1, 0], [1, 0, 0], [0, 0, 1]],
        6: [[0, -1, height - 1], [1, 0, 0], [0, 0, 1]],
        7: [[0, -1, height - 1], [-1, 0, width - 1], [0, 0, 1]],
        8: [[0, 1, 0], [-1, 0, width - 1], [0, 0, 1]],
    }
    return transforms[orientation]


def _verify_jpeg_pixels(data: bytes) -> None:
    # Pillow/libjpeg can silently fill a prematurely terminated entropy stream.
    # An isolated second decoder makes libjpeg's corruption warnings observable.
    script = (
        "import cv2,numpy as np,sys; "
        "image=cv2.imdecode(np.frombuffer(sys.stdin.buffer.read(),dtype=np.uint8),cv2.IMREAD_COLOR); "
        "sys.exit(0 if image is not None else 2)"
    )
    try:
        result = subprocess.run([sys.executable, "-c", script], input=data, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BitmapError("invalid_bitmap: strict JPEG decode failed") from exc
    if result.returncode or result.stderr:
        raise BitmapError("invalid_bitmap: corrupt or truncated JPEG pixel stream")


def load_bitmap(data: bytes, filename: str = "upload") -> BitmapAsset:
    """Fully decode pixels before admitting a content-addressed source."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise BitmapError("invalid_bitmap: upload must be non-empty bytes")
    data = bytes(data)
    if len(data) > MAX_FILE_BYTES:
        raise BitmapError("input_too_large: maximum file size is 20 MiB")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        expected_format, media_type = "PNG", "image/png"
        if not data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
            raise BitmapError("invalid_bitmap: PNG is missing final IEND")
    elif data.startswith(b"\xff\xd8"):
        expected_format, media_type = "JPEG", "image/jpeg"
        if not data.endswith(b"\xff\xd9"):
            raise BitmapError("invalid_bitmap: JPEG is missing final EOI")
    else:
        raise BitmapError("unsupported_media_type: only PNG and JPEG are supported")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                width, height = probe.size
                if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                    raise BitmapError("input_too_large: maximum side 12000 px and total 50 MP")
                if probe.format != expected_format or getattr(probe, "n_frames", 1) != 1:
                    raise BitmapError("unsupported_bitmap: format mismatch or animated image")
                probe.verify()
            if expected_format == "JPEG":
                _verify_jpeg_pixels(data)
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                orientation = source.getexif().get(274, 1)
                if orientation not in range(1, 9):
                    raise BitmapError("invalid_bitmap: unsupported EXIF orientation")
                transformed = ImageOps.exif_transpose(source)
                icc = source.info.get("icc_profile")
                if icc:
                    transformed = ImageCms.profileToProfile(
                        transformed, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                        ImageCms.createProfile("sRGB"), outputMode="RGBA" if "A" in transformed.getbands() else "RGB",
                    )
                rgba = transformed.convert("RGBA")
                white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                normalized = Image.alpha_composite(white, rgba).convert("RGB")
                encoded = _png(normalized)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise BitmapError("input_too_large: decompression bomb") from exc
    except BitmapError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, ImageCms.PyCMSError) as exc:
        raise BitmapError(f"invalid_bitmap: full pixel decode failed: {exc}") from exc
    metadata = {
        "decoder": "Pillow", "decoder_version": pillow_version,
        "original_pixel_size": {"width": width, "height": height},
        "pixel_size": {"width": normalized.width, "height": normalized.height},
        "exif_orientation": orientation,
        "source_to_normalized_transform": _orientation_transform(orientation, width, height),
        "color_space": "sRGB", "color_profile": "embedded_converted" if icc else "untagged_assumed_srgb",
        "alpha_background": [255, 255, 255], "normalized_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    return BitmapAsset(data, media_type, normalized.width, normalized.height, hashlib.sha256(data).hexdigest(), encoded, metadata)


def _binary(asset: BitmapAsset) -> tuple[np.ndarray, np.ndarray]:
    with Image.open(io.BytesIO(asset.normalized_png)) as image:
        rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    return gray, binary


def _segments(binary: np.ndarray, axis: str, minimum: int) -> list[dict[str, Any]]:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (minimum, 1) if axis == "h" else (1, minimum))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    count, _, stats, _ = cv2.connectedComponentsWithStats(opened, 8)
    result = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        length, thickness = (width, height) if axis == "h" else (height, width)
        if length < minimum or thickness > max(8, min(binary.shape) * 0.08):
            continue
        start, stop = (x, x + width - 1) if axis == "h" else (y, y + height - 1)
        coordinate = y + (height - 1) / 2 if axis == "h" else x + (width - 1) / 2
        result.append({"axis": axis, "coordinate": coordinate, "start": float(start), "end": float(stop),
                       "thickness": float(thickness), "evidence_bbox": [x, y, width, height],
                       "strength": round(area / (width * height), 6)})
    return sorted(result, key=lambda item: (item["coordinate"], item["start"]))


def _roi_candidates(gray: np.ndarray, binary: np.ndarray,
                    line_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find visual plan regions without promoting an ROI to model geometry.

    Marketing sheets commonly contain a title block, dimension strings, logos and a
    smaller plan drawing.  A line-only connected component mask is deliberately used
    here: dark text can be evidence inside a region, but cannot join two regions or
    define a room.  Returned boxes are crop/trace suggestions and always need review.
    """
    height, width = binary.shape
    short_line = max(15, int(min(height, width) * 0.025)) | 1
    horizontal = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (short_line, 1))
    )
    vertical = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, short_line))
    )
    line_mask = cv2.bitwise_or(horizontal, vertical)
    join_size = max(9, int(min(height, width) * 0.006)) | 1
    joined = cv2.morphologyEx(
        line_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (join_size, join_size))
    )
    joined = cv2.dilate(
        joined, cv2.getStructuringElement(cv2.MORPH_RECT, (join_size, join_size))
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    minimum_area = max(512, int(width * height * 0.001))
    candidates: list[dict[str, Any]] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[index])
        if area < minimum_area or box_width < short_line * 2 or box_height < short_line * 2:
            continue
        box = binary[y:y + box_height, x:x + box_width]
        line_box = joined[y:y + box_height, x:x + box_width]
        dark_ratio = float(np.mean(box > 0))
        line_ratio = float(np.mean(line_box > 0))
        intersects = []
        for line in line_candidates:
            lx, ly, lw, lh = line["evidence_bbox"]
            if lx < x + box_width and lx + lw > x and ly < y + box_height and ly + lh > y:
                intersects.append(line)
        if not intersects:
            continue
        # Area and orthogonal-line coverage rank suggestions; this is not factual
        # confidence and intentionally remains below the confirmation threshold.
        area_ratio = area / float(width * height)
        score = max(0.0, min(0.89, 0.35 + min(0.35, area_ratio) + min(0.19, line_ratio)))
        candidates.append({
            "id": "",
            "kind": "floorplan_roi",
            "pixel_geometry": {"bbox": [x, y, box_width, box_height]},
            "evidence_bbox": [x, y, box_width, box_height],
            "provenance": "orthogonal_line_component",
            "confidence": round(score, 6),
            "needs_review": True,
            "selection": "manual_crop_or_trace",
            "dark_pixel_ratio": round(dark_ratio, 6),
            "line_pixel_ratio": round(line_ratio, 6),
            "intersecting_line_count": len(intersects),
            "parameters": {"short_line_px": short_line, "join_size_px": join_size},
        })
    candidates.sort(key=lambda item: (-item["confidence"], -item["intersecting_line_count"], item["evidence_bbox"]))
    for rank, candidate in enumerate(candidates[:8], start=1):
        candidate["id"] = f"roi-candidate-{rank}"
        candidate["rank"] = rank
    return candidates[:8]


def _group_lines(segments: list[dict[str, Any]], maximum_gap: int) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for segment in segments:
        match = next((line for line in reversed(groups)
                      if abs(line["coordinate"] - segment["coordinate"]) <= 1
                      and segment["start"] <= line["end"] + maximum_gap
                      and segment["end"] >= line["start"] - maximum_gap), None)
        if match is None:
            groups.append({**segment, "intervals": [[segment["start"], segment["end"]]], "gaps": []})
            continue
        match["start"] = min(match["start"], segment["start"])
        match["end"] = max(match["end"], segment["end"])
        match["intervals"].append([segment["start"], segment["end"]])
        intervals = sorted(match["intervals"])
        match["gaps"] = []
        end = intervals[0][1]
        for start, stop in intervals[1:]:
            if start > end + 1:
                match["gaps"].append([end + 1, start])
            end = max(end, stop)
        match["thickness"] = max(match["thickness"], segment["thickness"])
    return groups


def _pair_parallel(lines: list[dict[str, Any]], maximum_thickness: float) -> list[dict[str, Any]]:
    """Treat paired outline strokes as one wall, retaining both pixel evidences."""
    result, consumed = [], set()
    for index, line in enumerate(lines):
        if index in consumed:
            continue
        partner = None
        for other_index in range(index + 1, len(lines)):
            other = lines[other_index]
            separation = other["coordinate"] - line["coordinate"]
            overlap = min(line["end"], other["end"]) - max(line["start"], other["start"])
            longest = max(line["end"] - line["start"], other["end"] - other["start"])
            # Pair only adjacent strokes.  A broad search radius makes page
            # decorations and dimension lines look like a single very thick
            # wall (e.g. 120 px apart in a 3000 px marketing plan).  The
            # lower bound preserves the existing 1 px double-outline case;
            # the upper bound scales with the thinner stroke so unrelated
            # long lines cannot be absorbed into a wall candidate.
            pair_limit = max(12.0, 4.0 * min(line["thickness"], other["thickness"]))
            if other_index not in consumed and max(line["thickness"], other["thickness"]) < separation <= min(maximum_thickness, pair_limit) and overlap >= longest * 0.9:
                partner = (other_index, other)
                break
        if partner is None:
            result.append(line)
            continue
        other_index, other = partner
        consumed.add(other_index)
        result.append({**line, "coordinate": (line["coordinate"] + other["coordinate"]) / 2,
                       "start": min(line["start"], other["start"]), "end": max(line["end"], other["end"]),
                       "thickness": other["coordinate"] - line["coordinate"] + (line["thickness"] + other["thickness"]) / 2,
                       "paired_evidence": [line["evidence_bbox"], other["evidence_bbox"]],
                       "gaps": [[max(a, c), min(b, d)] for a, b in line["gaps"] for c, d in other["gaps"] if min(b, d) > max(a, c)]})
    return sorted(result, key=lambda item: (item["coordinate"], item["start"]))


def _covers(line: dict[str, Any], start: float, end: float) -> bool:
    tolerance = max(2, line["thickness"] / 2 + 1)
    if line["start"] > start + tolerance or line["end"] < end - tolerance:
        return False
    missing = sum(max(0, min(b, end) - max(a, start)) for a, b in line["gaps"])
    return missing <= 0.2 * (end - start)


def _roi_component_faces(binary: np.ndarray, roi: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover room-sized free-space components inside a marketing-page ROI.

    The primary recognizer intentionally uses a strict closed-rectangle rule. A
    brochure plan usually has furniture, labels, and door gaps which violate
    that rule even when the structural walls are orthogonal. This fallback
    treats long orthogonal strokes as a wall mask and returns disjoint
    component boxes as *candidates*; they remain review-gated and are never
    promoted to confirmed topology by this function alone.
    """
    bbox = roi.get("evidence_bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return []
    x0, y0, width, height = (round(value) for value in bbox)
    if width < 200 or height < 160:
        return []
    crop = binary[y0:y0 + height, x0:x0 + width]
    if crop.size == 0:
        return []
    minimum = max(13, int(min(width, height) * 0.045)) | 1
    maximum_gap = max(4, int(min(width, height) * 0.16))
    raw = _segments(crop, "h", minimum) + _segments(crop, "v", minimum)
    lines = _pair_parallel(_group_lines([item for item in raw if item["axis"] == "h"], maximum_gap), minimum / 2)
    lines += _pair_parallel(_group_lines([item for item in raw if item["axis"] == "v"], maximum_gap), minimum / 2)

    wall_mask = np.zeros_like(crop)
    structural_length = max(180, int(min(width, height) * 0.18))
    for line in lines:
        line_length = line["end"] - line["start"]
        if line["thickness"] < 2 and line_length < structural_length:
            continue
        thickness = max(3, round(line["thickness"]))
        if line["axis"] == "h":
            start = (round(line["start"]), round(line["coordinate"]))
            end = (round(line["end"]), round(line["coordinate"]))
        else:
            start = (round(line["coordinate"]), round(line["start"]))
            end = (round(line["coordinate"]), round(line["end"]))
        cv2.line(wall_mask, start, end, 255, thickness=thickness, lineType=cv2.LINE_8)
    wall_mask = cv2.morphologyEx(
        wall_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    )
    wall_mask = cv2.dilate(wall_mask, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    free_space = cv2.bitwise_not(wall_mask)
    labels_count, _labels, stats, _ = cv2.connectedComponentsWithStats(free_space, 4)
    minimum_area = max(40_000, int(width * height * 0.014))
    minimum_width = max(150, int(width * 0.07))
    minimum_height = max(120, int(height * 0.07))
    faces: list[dict[str, Any]] = []
    for index in range(1, labels_count):
        local_x, local_y, local_width, local_height, area = (int(value) for value in stats[index])
        if area < minimum_area or local_width < minimum_width or local_height < minimum_height:
            continue
        # A component touching the ROI edge is page background, not a room.
        if local_x <= 1 or local_y <= 1 or local_x + local_width >= width - 1 or local_y + local_height >= height - 1:
            continue
        rect = [float(local_x + x0), float(local_y + y0), float(local_width), float(local_height)]
        x, y, room_width, room_height = rect
        synthetic_lines = [
            {"axis": "h", "coordinate": y, "start": x, "end": x + room_width, "thickness": 5.0, "gaps": [],
             "evidence_bbox": [x, y, room_width, 5]},
            {"axis": "h", "coordinate": y + room_height, "start": x, "end": x + room_width, "thickness": 5.0, "gaps": [],
             "evidence_bbox": [x, y + room_height, room_width, 5]},
            {"axis": "v", "coordinate": x, "start": y, "end": y + room_height, "thickness": 5.0, "gaps": [],
             "evidence_bbox": [x, y, 5, room_height]},
            {"axis": "v", "coordinate": x + room_width, "start": y, "end": y + room_height, "thickness": 5.0, "gaps": [],
             "evidence_bbox": [x + room_width, y, 5, room_height]},
        ]
        faces.append({"rect": rect, "lines": synthetic_lines, "provenance": "roi_structural_component",
                      "confidence": 0.45, "component_area": area})
    faces.sort(key=lambda item: (item["rect"][1], item["rect"][0]))
    return faces


def _recognize(asset: BitmapAsset) -> dict[str, Any]:
    gray, binary = _binary(asset)
    minimum = max(13, int(min(asset.width, asset.height) * 0.12)) | 1
    maximum_gap = max(4, int(min(asset.width, asset.height) * 0.16))
    if float(np.mean(binary > 0)) > 0.65:
        raise BitmapError("unsupported_bitmap: insufficient light room interior")
    raw = _segments(binary, "h", minimum) + _segments(binary, "v", minimum)
    roi_candidates = _roi_candidates(gray, binary, raw)
    hough = cv2.HoughLinesP(binary, 1, np.pi / 720, threshold=minimum,
                            minLineLength=minimum * 2, maxLineGap=2)
    if hough is not None:
        for x1, y1, x2, y2 in hough[:, 0, :]:
            angle = abs(math.degrees(math.atan2(int(y2) - int(y1), int(x2) - int(x1)))) % 90
            if min(angle, 90 - angle) > 2:
                covered_by_axis_band = any(
                    (line["axis"] == "h" and max(abs(y1 - line["coordinate"]), abs(y2 - line["coordinate"])) <= line["thickness"] / 2 + 1
                     and min(x1, x2) >= line["start"] - 2 and max(x1, x2) <= line["end"] + 2)
                    or (line["axis"] == "v" and max(abs(x1 - line["coordinate"]), abs(x2 - line["coordinate"])) <= line["thickness"] / 2 + 1
                        and min(y1, y2) >= line["start"] - 2 and max(y1, y2) <= line["end"] + 2)
                    for line in raw
                )
                if not covered_by_axis_band:
                    raise BitmapError("non_orthogonal_candidate: long diagonal line requires manual tracing")
    lines = _pair_parallel(_group_lines([item for item in raw if item["axis"] == "h"], maximum_gap), minimum / 2)
    lines += _pair_parallel(_group_lines([item for item in raw if item["axis"] == "v"], maximum_gap), minimum / 2)
    if len(lines) > 128:
        raise BitmapError("input_too_complex: more than 128 long wall candidates")
    horizontal = [item for item in lines if item["axis"] == "h"]
    vertical = [item for item in lines if item["axis"] == "v"]
    rectangles = []
    for index, top in enumerate(horizontal):
        for bottom in horizontal[index + 1:]:
            y1, y2 = top["coordinate"], bottom["coordinate"]
            if y2 - y1 < minimum:
                continue
            sides = [line for line in vertical if _covers(line, y1, y2)]
            for left_index, left in enumerate(sides):
                for right in sides[left_index + 1:]:
                    x1, x2 = left["coordinate"], right["coordinate"]
                    if x2 - x1 < minimum or not _covers(top, x1, x2) or not _covers(bottom, x1, x2):
                        continue
                    rectangles.append({"rect": [x1, y1, x2 - x1, y2 - y1], "lines": [top, bottom, left, right]})
    faces = []
    for candidate in rectangles:
        x, y, width, height = candidate["rect"]
        subdivided = any(
            (line["axis"] == "v" and x + 2 < line["coordinate"] < x + width - 2 and _covers(line, y, y + height))
            or (line["axis"] == "h" and y + 2 < line["coordinate"] < y + height - 2 and _covers(line, x, x + width))
            for line in lines
        )
        if not subdivided:
            faces.append(candidate)
    faces.sort(key=lambda item: (item["rect"][1], item["rect"][0]))
    if not faces:
        raise BitmapError("no_closed_rectangle: no supported closed orthogonal room was found")
    for index, face in enumerate(faces):
        x, y, width, height = face["rect"]
        for other in faces[index + 1:]:
            ox, oy, ow, oh = other["rect"]
            if min(x + width, ox + ow) - max(x, ox) > 1 and min(y + height, oy + oh) - max(y, oy) > 1:
                raise BitmapError("overlapping_room_candidates: manual tracing required")
    # A large brochure ROI often yields one strict rectangle because door gaps
    # interrupt the interior partition lines. Recover disjoint structural
    # components before returning the one-room result in that case.
    if len(faces) == 1 and roi_candidates:
        component_faces = _roi_component_faces(binary, roi_candidates[0])
        if len(component_faces) > 1:
            faces = component_faces
            metadata_detection = "roi_structural_components"
        else:
            metadata_detection = "closed_rectangle"
    else:
        metadata_detection = "closed_rectangle"
    used = {id(line) for face in faces for line in face["lines"]}
    unused = [line for line in lines if id(line) not in used]
    return {"faces": faces, "lines": lines, "unused": unused, "metadata": {
        **asset.normalization, "algorithm_version": ALGORITHM_VERSION, "opencv_version": cv2.__version__,
        "threshold": 180, "threshold_mode": "fixed_inverse", "denoise": "none", "contrast": "none",
        "minimum_line_length_px": minimum, "maximum_gap_px": maximum_gap,
        "mean_luma": round(float(gray.mean()), 6), "dark_ratio": round(float(np.mean(binary > 0)), 6),
        "roi_candidates": roi_candidates,
        "room_detection": {"mode": metadata_detection, "room_candidate_count": len(faces)},
        "line_candidates": raw,
    }}


def preprocess_bitmap(asset: BitmapAsset) -> dict[str, Any]:
    return _recognize(asset)["metadata"]


def _ocr_evidence(asset: BitmapAsset) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runtime = _ocr_runtime()
    executable = shutil.which("tesseract")
    if executable is None:
        return {**runtime, "dimensions": []}, [{"code": "ocr_unavailable", "message": "Tesseract is not installed; dimensions require manual review"}]
    try:
        result = subprocess.run(
            [executable, "stdin", "stdout", "--psm", "11", "-l", "eng", "tsv"],
            input=asset.normalized_png, capture_output=True,
            timeout=10, check=False, env={**os.environ, "OMP_THREAD_LIMIT": "1", "LC_ALL": "C"},
        )
        if result.returncode:
            return {**runtime, "dimensions": []}, [{"code": "ocr_failed", "message": "Tesseract could not produce dimension evidence"}]
        entries = []
        for row in csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t"):
            value = row.get("text", "").strip()
            if not re.fullmatch(r"\d{2,6}(?:\.\d+)?(?:mm|cm|m)?", value, re.IGNORECASE):
                continue
            entries.append({"text": value, "evidence_bbox": [int(row[key]) for key in ("left", "top", "width", "height")],
                            "confidence": round(max(0, min(100, float(row["conf"]))) / 100, 6),
                            "provenance": "ocr_dimension_unassociated", "needs_review": True, "association": None})
        entries.sort(key=lambda item: (item["evidence_bbox"][1], item["evidence_bbox"][0], item["text"]))
        notes = [{"code": "dimension_ocr_unassociated", "message": "OCR text is evidence only; no dimension endpoints or scale were inferred"}] if entries else []
        return {**runtime, "language": "eng", "psm": 11, "dimensions": entries}, notes
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, KeyError):
        return {**runtime, "dimensions": []}, [{"code": "ocr_failed", "message": "Dimension OCR failed or exceeded its 10 second budget"}]


def ingest_bitmap(data: bytes, *, filename: str = "upload", model_id: str | None = None,
                  revision: int = 1, mm_per_pixel: float | None = None) -> dict[str, Any]:
    scale = _scale(mm_per_pixel)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise BitmapError("invalid_revision: revision must be an integer >= 1")
    asset = load_bitmap(data, filename)
    if max(asset.width, asset.height) * scale > 1_000_000:
        raise BitmapError("invalid_scale: resulting dimensions exceed 1000000 mm")
    recognition = _recognize(asset)
    job_id = ingest_key(data, scale)
    source_ref = {"source_asset_sha256": asset.sha256, "provenance": "opencv_line_candidate",
                  "confidence": 0.8, "needs_review": True, "algorithm_version": ALGORITHM_VERSION}
    candidates, walls, rooms, openings = [], [], [], []
    line_ids: dict[int, str] = {}

    def length(value: float) -> float:
        return round(value * scale, 6)

    def candidate(object_id: str, kind: str, pixels: dict[str, Any], geometry: dict[str, Any], bbox: list[float],
                 evidence_source: dict[str, Any] | None = None) -> None:
        source = evidence_source or source_ref
        candidates.append({"id": object_id, "kind": kind, "pixel_geometry": pixels, "geometry_mm": geometry,
                           "evidence_bbox": bbox, **source})

    for face in recognition["faces"]:
        face_source = {**source_ref, "provenance": face.get("provenance", source_ref["provenance"]),
                       "confidence": face.get("confidence", source_ref["confidence"])}
        boundaries = []
        for line in face["lines"]:
            identity = id(line)
            if identity not in line_ids:
                wall_id = f"wall-candidate-{len(walls) + 1}"
                line_ids[identity] = wall_id
                axis, coordinate, start, end = (line[key] for key in ("axis", "coordinate", "start", "end"))
                x, y = (start, coordinate) if axis == "h" else (coordinate, start)
                thickness = line["thickness"]
                wall = {"id": wall_id, "axis": axis, "x": length(x), "y": length(y), "length": length(end - start),
                        "thickness": length(thickness), "bottom_z": 0.0, "top_z": 2800.0, **face_source,
                        "dimension_provenance": {"source": "user_scale", "pixel_value": end - start, "world_value_mm": length(end - start),
                                                 "source_asset_sha256": asset.sha256, "confidence": face_source["confidence"], "needs_review": True},
                        "height_provenance": {"source": "default_unmeasured", "value_mm": 2800, "confidence": 0, "needs_review": True}}
                walls.append(wall)
                bbox = [x, y - thickness / 2, end - start, thickness] if axis == "h" else [x - thickness / 2, y, thickness, end - start]
                candidate(wall_id, "wall", {"axis": axis, "x": x, "y": y, "length": end - start, "thickness": thickness},
                          {key: wall[key] for key in ("axis", "x", "y", "length", "thickness")}, bbox, face_source)
                for gap_start, gap_end in line["gaps"]:
                    if gap_end - gap_start <= max(2, thickness):
                        continue
                    opening_id = f"opening-candidate-{len(openings) + 1}"
                    opening = {"id": opening_id, "host_wall_id": wall_id, "kind": "passage", "offset": length(gap_start - start),
                               "width": length(gap_end - gap_start), "height": 2100.0, "bottom_z": 0.0, **source_ref,
                               "confidence": 0.5, "provenance": "wall_gap_unclassified",
                               "height_provenance": {"source": "default_unmeasured", "value_mm": 2100, "confidence": 0, "needs_review": True}}
                    openings.append(opening)
                    obox = [gap_start, coordinate - thickness / 2, gap_end - gap_start, thickness] if axis == "h" else [coordinate - thickness / 2, gap_start, thickness, gap_end - gap_start]
                    candidate(opening_id, "opening", {"host_wall_id": wall_id, "offset": gap_start - start, "width": gap_end - gap_start},
                              {key: opening[key] for key in ("host_wall_id", "offset", "width", "height")}, obox, face_source)
                    candidates[-1].update(confidence=0.5, provenance="wall_gap_unclassified")
            boundaries.append(line_ids[identity])
        room_id = f"room-candidate-{len(rooms) + 1}"
        pixel_rect = face["rect"]
        rect = [length(value) for value in pixel_rect]
        room = {"id": room_id, "name": f"Room {len(rooms) + 1}", "kind": "unknown", "rect": rect,
                "boundary_wall_ids": boundaries, **face_source,
                "dimension_provenance": {"source": "user_scale", "pixel_rect": pixel_rect, "world_rect_mm": rect,
                                         "source_asset_sha256": asset.sha256, "confidence": face_source["confidence"], "needs_review": True}}
        rooms.append(room)
        candidate(room_id, "room", {"rect": pixel_rect}, {"rect": rect}, pixel_rect, face_source)
    for index, room in enumerate(rooms):
        for other in rooms[index + 1:]:
            x, y, width, height = room["rect"]
            ox, oy, ow, oh = other["rect"]
            shared = sorted(wall["id"] for wall in walls
                            if wall["id"] in room["boundary_wall_ids"] and wall["id"] in other["boundary_wall_ids"]
                            and ((wall["axis"] == "v" and (abs(x + width - ox) < 1e-6 or abs(ox + ow - x) < 1e-6)
                                  and abs(wall["x"] - max(x, ox)) < 1e-6)
                                 or (wall["axis"] == "h" and (abs(y + height - oy) < 1e-6 or abs(oy + oh - y) < 1e-6)
                                     and abs(wall["y"] - max(y, oy)) < 1e-6)))
            if shared and any(item["host_wall_id"] in shared for item in openings):
                candidates.append({"id": f"merge-candidate-{room['id']}-{other['id']}", "kind": "merge_group",
                                   "room_ids": [room["id"], other["id"]], "shared_wall_ids": shared,
                                   "pixel_geometry": {}, "geometry_mm": {}, "evidence_bbox": [],
                                   **source_ref, "confidence": 0.5, "provenance": "shared_wall_gap"})
    ocr, notes = _ocr_evidence(asset)
    # Evidence is immutable input provenance too; attach the original source
    # hash before any ROI mapping can move its pixel coordinates.
    for item in ocr.get("dimensions", []):
        item["source_asset_sha256"] = asset.sha256
    preprocessing = {
        **recognition["metadata"],
        "source_sha256": asset.sha256,
        "line_candidates": [
            {**item, "source_asset_sha256": asset.sha256}
            for item in recognition["metadata"].get("line_candidates", [])
        ],
        "roi_candidates": [
            {**item, "source_asset_sha256": asset.sha256}
            for item in recognition["metadata"].get("roi_candidates", [])
        ],
    }
    notes.append({"code": "unmeasured_heights", "message": "Wall and opening heights are defaults and must be reviewed"})
    if openings:
        notes.append({"code": "unclassified_wall_gaps", "message": "Wall gaps are passage candidates, not classified doors or windows"})
    if recognition["unused"]:
        notes.append({"code": "unassigned_line_candidates", "message": "Some long lines do not bound a closed room", "count": len(recognition["unused"])})
    hard_blockers = []
    if recognition["unused"]:
        hard_blockers.append({
            "code": "partial_plan_requires_manual_trace",
            "message": "Unassigned structural lines remain; crop or trace the complete floor plan before confirmation",
            "count": len(recognition["unused"]),
        })
    model = {
        "schema_version": "2.0", "profile": "orthogonal_v1", "model_id": model_id or f"bitmap-{job_id[:24]}",
        "revision": revision, "status": "draft", "units": {"length": "mm", "angle": "deg"},
        "coordinates": {"origin": "normalized_bitmap_top_left", "handedness": "right"},
        "source": {"asset_id": f"sha256:{asset.sha256}", "kind": "bitmap", "sha256": asset.sha256, "provenance": "user_upload"},
        "confidence": 0.8, "rooms": rooms, "walls": walls, "openings": openings,
        "furniture_instances": [], "cameras": [], "materials": [],
        "ingest": {"ingest_id": job_id, "algorithm_version": ALGORITHM_VERSION, "parameters_hash": job_id,
                   "media_type": asset.media_type, "source_sha256": asset.sha256,
                   "pixel_size": {"width": asset.width, "height": asset.height}, "mm_per_pixel": scale,
                   "scale_status": "user_supplied", "calibration": {"value": scale, "provenance": "user_scale", "confidence": 1.0, "needs_review": True},
                   "preprocessing": preprocessing, "candidates": candidates,
                   "evidence": {"ocr": ocr,
                                "unassigned_lines": [{**item, "source_asset_sha256": asset.sha256}
                                                     for item in recognition["unused"]],
                                "roi_candidates": [{**candidate, "source_asset_sha256": asset.sha256}
                                                   for candidate in recognition["metadata"]["roi_candidates"]]},
                   "warnings": notes, "hard_blockers": hard_blockers, "requires_human_review": True},
    }
    try:
        validate_model(model)
    except ValueError as exc:
        raise BitmapError(f"invalid_candidate_geometry: {exc}") from exc
    return model


def roi_ingest_key(parent_ingest_id: str, parent_source_sha256: str,
                   bbox: list[int], mm_per_pixel: float) -> str:
    """Return a deterministic identity for a parent-backed ROI recognition."""
    scale = _scale(mm_per_pixel)
    parameters = {
        "roi_key_version": ROI_KEY_VERSION,
        "parent_ingest_id": parent_ingest_id,
        "parent_source_sha256": parent_source_sha256,
        "bbox": bbox,
        "mm_per_pixel": scale,
        "algorithm_version": ALGORITHM_VERSION,
        "pillow_version": pillow_version,
        "opencv_version": cv2.__version__,
        "numpy_version": np.__version__,
        "ocr": _ocr_runtime(),
    }
    return hashlib.sha256(canonical_json(parameters).encode()).hexdigest()


def _offset_pixel_bbox(value: Any, offset_x: int, offset_y: int) -> Any:
    if not isinstance(value, list) or len(value) != 4:
        return value
    return [value[0] + offset_x, value[1] + offset_y, value[2], value[3]]


def _offset_geometry(value: Any, offset_x_mm: float, offset_y_mm: float) -> Any:
    if isinstance(value, list) and len(value) == 4:
        return [round(value[0] + offset_x_mm, 6), round(value[1] + offset_y_mm, 6), value[2], value[3]]
    if isinstance(value, dict):
        result = copy.deepcopy(value)
        for key in ("x", "y"):
            if isinstance(result.get(key), (int, float)) and not isinstance(result[key], bool):
                result[key] = round(result[key] + (offset_x_mm if key == "x" else offset_y_mm), 6)
        for key, item in list(result.items()):
            if key in {"rect", "world_rect", "world_rect_mm"} and isinstance(item, list) and len(item) == 4:
                result[key] = _offset_geometry(item, offset_x_mm, offset_y_mm)
        return result
    return value


def _map_pixel_geometry(value: Any, offset_x: int, offset_y: int) -> Any:
    if isinstance(value, list) and len(value) == 4:
        return [value[0] + offset_x, value[1] + offset_y, value[2], value[3]]
    if not isinstance(value, dict):
        return value
    result = copy.deepcopy(value)
    for key in ("x", "y"):
        if isinstance(result.get(key), (int, float)) and not isinstance(result[key], bool):
            result[key] += offset_x if key == "x" else offset_y
    for key, item in list(result.items()):
        if key in {"bbox", "rect", "pixel_rect"} and isinstance(item, list) and len(item) == 4:
            result[key] = _map_pixel_geometry(item, offset_x, offset_y)
    return result


def _map_evidence_item(item: Any, offset_x: int, offset_y: int) -> None:
    if not isinstance(item, dict):
        return
    for key in ("evidence_bbox", "pixel_bbox", "bbox"):
        if isinstance(item.get(key), list) and len(item[key]) == 4:
            item[key] = _offset_pixel_bbox(item[key], offset_x, offset_y)
    if isinstance(item.get("paired_evidence"), list):
        item["paired_evidence"] = [
            _offset_pixel_bbox(box, offset_x, offset_y) if isinstance(box, list) and len(box) == 4 else box
            for box in item["paired_evidence"]
        ]
    if isinstance(item.get("pixel_geometry"), dict):
        item["pixel_geometry"] = _map_pixel_geometry(item["pixel_geometry"], offset_x, offset_y)
    if item.get("axis") in {"h", "v"}:
        along, across = (offset_x, offset_y) if item["axis"] == "h" else (offset_y, offset_x)
        for key, offset in (("coordinate", across), ("start", along), ("end", along)):
            if isinstance(item.get(key), (int, float)):
                item[key] += offset
        for key in ("intervals", "gaps"):
            if isinstance(item.get(key), list):
                item[key] = [[start + along, end + along] for start, end in item[key]]


def _map_roi_coordinates(model: dict[str, Any], bbox: list[int], parent_ingest_id: str,
                         parent_source_sha256: str, roi_id: str) -> dict[str, Any]:
    """Map crop-local geometry/evidence back to normalized parent pixels/mm."""
    offset_x, offset_y, _, _ = bbox
    scale = float(model["ingest"]["mm_per_pixel"])
    offset_x_mm, offset_y_mm = offset_x * scale, offset_y * scale
    mapped = copy.deepcopy(model)
    for wall in mapped["walls"]:
        wall["x"] = round(wall["x"] + offset_x_mm, 6)
        wall["y"] = round(wall["y"] + offset_y_mm, 6)
        for provenance_key in ("dimension_provenance",):
            provenance = wall.get(provenance_key)
            if isinstance(provenance, dict) and isinstance(provenance.get("pixel_value"), (int, float)):
                provenance["parent_pixel_origin"] = [offset_x, offset_y]
            if isinstance(provenance, dict) and "source_asset_sha256" in provenance:
                provenance["source_asset_sha256"] = parent_source_sha256
    for room in mapped["rooms"]:
        for key in ("rect", "world_rect", "world_rect_mm"):
            if key in room:
                room[key] = _offset_geometry(room[key], offset_x_mm, offset_y_mm)
        provenance = room.get("dimension_provenance")
        if isinstance(provenance, dict) and isinstance(provenance.get("pixel_rect"), list):
            provenance["pixel_rect"] = _offset_pixel_bbox(provenance["pixel_rect"], offset_x, offset_y)
        if isinstance(provenance, dict):
            for key in ("world_rect", "world_rect_mm"):
                if key in provenance:
                    provenance[key] = _offset_geometry(provenance[key], offset_x_mm, offset_y_mm)
        if isinstance(provenance, dict) and "source_asset_sha256" in provenance:
            provenance["source_asset_sha256"] = parent_source_sha256
        if room.get("source_asset_sha256"):
            room["source_asset_sha256"] = parent_source_sha256
    for candidate in mapped["ingest"].get("candidates", []):
        if isinstance(candidate, dict):
            _map_evidence_item(candidate, offset_x, offset_y)
            geometry = candidate.get("geometry_mm")
            if geometry is not None:
                candidate["geometry_mm"] = _offset_geometry(geometry, offset_x_mm, offset_y_mm)
            if candidate.get("source_asset_sha256"):
                candidate["source_asset_sha256"] = parent_source_sha256
    evidence = mapped["ingest"].get("evidence", {})
    if isinstance(evidence, dict):
        ocr = evidence.get("ocr")
        if isinstance(ocr, dict):
            for item in ocr.get("dimensions", []):
                _map_evidence_item(item, offset_x, offset_y)
        for item in evidence.get("unassigned_lines", []):
            _map_evidence_item(item, offset_x, offset_y)
        for item in evidence.get("roi_candidates", []):
            if isinstance(item, dict):
                _map_evidence_item(item, offset_x, offset_y)
                if item.get("source_asset_sha256"):
                    item["source_asset_sha256"] = parent_source_sha256
    preprocessing = mapped["ingest"].get("preprocessing", {})
    if isinstance(preprocessing, dict):
        preprocessing["source_sha256"] = parent_source_sha256
        preprocessing["crop_source_sha256"] = mapped["source"]["sha256"]
        for key in ("roi_candidates", "line_candidates"):
            for item in preprocessing.get(key, []):
                if isinstance(item, dict):
                    _map_evidence_item(item, offset_x, offset_y)
                    if item.get("source_asset_sha256"):
                        item["source_asset_sha256"] = parent_source_sha256
    # Every recognized evidence record must identify the immutable root source,
    # even when this model was produced from a nested crop.
    def replace_hashes(value: Any) -> None:
        if isinstance(value, dict):
            if "source_asset_sha256" in value:
                value["source_asset_sha256"] = parent_source_sha256
            for child in value.values():
                replace_hashes(child)
        elif isinstance(value, list):
            for child in value:
                replace_hashes(child)
    replace_hashes(mapped.get("walls", []))
    replace_hashes(mapped.get("rooms", []))
    replace_hashes(mapped.get("openings", []))
    replace_hashes(mapped.get("ingest", {}).get("candidates", []))
    replace_hashes(mapped.get("ingest", {}).get("evidence", {}))
    replace_hashes(mapped.get("ingest", {}).get("preprocessing", {}))
    mapped["source"] = {
        "asset_id": f"sha256:{mapped['source']['sha256']}", "kind": "bitmap",
        "sha256": mapped["source"]["sha256"], "provenance": "manual_roi_crop",
        "parent_ingest_id": parent_ingest_id, "parent_source_sha256": parent_source_sha256,
        "roi_bbox": bbox,
    }
    mapped["model_id"] = f"bitmap-{roi_id[:24]}"
    mapped["ingest"]["ingest_id"] = roi_id
    mapped["ingest"]["parameters_hash"] = roi_id
    mapped["ingest"]["parent_ingest_id"] = parent_ingest_id
    mapped["ingest"]["parent_source_sha256"] = parent_source_sha256
    mapped["ingest"]["roi"] = {
        "bbox": bbox, "coordinate_space": "normalized_parent_pixels", "selection": "manual",
        "algorithm_version": ALGORITHM_VERSION, "source_asset_sha256": parent_source_sha256,
    }
    mapped["ingest"]["evidence"]["parent_ingest_id"] = parent_ingest_id
    mapped["ingest"]["evidence"]["parent_source_sha256"] = parent_source_sha256
    mapped["ingest"]["warnings"].append({
        "code": "roi_coordinates_mapped_to_parent", "message": "Geometry is recognized from a manual ROI and mapped to normalized parent pixels",
    })
    return mapped


def crop_ingest(data: bytes, *, parent_ingest_id: str, parent_source_sha256: str,
                bbox: list[int], mm_per_pixel: float, candidate_id: str | None = None,
                candidate_score: float | None = None) -> tuple[dict[str, Any], BitmapAsset]:
    """Crop a normalized parent bitmap, recognize it, and map geometry to parent space."""
    asset = load_bitmap(data, "parent-preprocessed.png")
    x, y, width, height = bbox
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > asset.width or y + height > asset.height:
        raise BitmapError("invalid_roi: bbox is outside the normalized source image")
    with Image.open(io.BytesIO(asset.normalized_png)) as image:
        cropped = image.crop((x, y, x + width, y + height))
        cropped_png = _png(cropped)
    cropped_asset = load_bitmap(cropped_png, "roi.png")
    roi_id = roi_ingest_key(parent_ingest_id, parent_source_sha256, bbox, mm_per_pixel)
    model = ingest_bitmap(cropped_png, filename="roi.png", model_id=f"bitmap-{roi_id[:24]}", mm_per_pixel=mm_per_pixel)
    model = _map_roi_coordinates(model, bbox, parent_ingest_id, parent_source_sha256, roi_id)
    if candidate_id is not None:
        model["ingest"]["roi"]["candidate_id"] = candidate_id
    if candidate_score is not None:
        model["ingest"]["roi"]["candidate_score"] = candidate_score
    model["source"] = {
        "asset_id": f"sha256:{parent_source_sha256}", "kind": "bitmap",
        "sha256": parent_source_sha256, "provenance": "manual_roi_crop",
        "parent_ingest_id": parent_ingest_id, "parent_source_sha256": parent_source_sha256,
        "roi_bbox": bbox,
    }
    model["ingest"]["source_sha256"] = parent_source_sha256
    model["ingest"]["pixel_size"] = {"width": asset.width, "height": asset.height}
    model["ingest"]["roi"]["crop_pixel_size"] = {"width": width, "height": height}
    return model, cropped_asset
