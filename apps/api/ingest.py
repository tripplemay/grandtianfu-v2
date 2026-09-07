"""Bounded CPU worker orchestration and immutable ingest artifacts."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ingest import BitmapError
from ingest.bitmap import load_bitmap, roi_ingest_key

from .revisions import StorageIntegrityError, strict_json


class IngestUnavailable(RuntimeError):
    """The single local ingest worker is busy or unavailable."""


def read_ingest(root: str | Path, ingest_id: str) -> dict[str, Any]:
    if len(ingest_id) != 64 or any(char not in "0123456789abcdef" for char in ingest_id):
        raise FileNotFoundError("Ingest not found")
    directory = Path(root) / ingest_id
    if not directory.is_dir():
        raise FileNotFoundError("Ingest not found")
    try:
        manifest = strict_json((directory / "ingest-manifest.json").read_bytes())
        if not isinstance(manifest, dict):
            raise TypeError("manifest must be an object")
        files, hashes = manifest["files"], manifest["artifact_hashes"]
        if (not isinstance(files, dict) or not isinstance(hashes, dict)
                or set(files) != {"source", "preprocessed", "draft_model", "preprocessing"}):
            raise ValueError("unexpected artifact set")
        for key, filename in files.items():
            if not isinstance(filename, str) or Path(filename).name != filename or filename in {".", ".."}:
                raise ValueError("invalid artifact name")
            path = directory / filename
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]:
                raise ValueError("artifact hash mismatch")
        model = strict_json((directory / files["draft_model"]).read_bytes())
        from spatial_core import canonical_hash

        if (model["source"]["sha256"] != hashes["source"] or model["ingest"]["ingest_id"] != ingest_id
                or manifest["ingest_id"] != ingest_id or manifest["model_hash"] != canonical_hash(model)
                or manifest["source_sha256"] != hashes["source"]):
            raise ValueError("source or job identity mismatch")
        return {"ingest_id": ingest_id, "manifest": manifest, "model": model}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise StorageIntegrityError("Ingest artifacts are incomplete or corrupt; original evidence was not overwritten") from exc


def _retain_failure(root: Path, ingest_id: str, source: bytes, error: Exception) -> None:
    rejected = root / "rejected"
    rejected.mkdir(exist_ok=True)
    final = rejected / ingest_id
    if final.exists():
        return
    with tempfile.TemporaryDirectory(prefix=".failed-", dir=root) as temporary:
        staging = Path(temporary) / ingest_id
        staging.mkdir()
        (staging / "source.bin").write_bytes(source)
        (staging / "failure.json").write_text(json.dumps({
            "ingest_id": ingest_id, "source_sha256": hashlib.sha256(source).hexdigest(),
            "status": "failed", "error_type": type(error).__name__, "detail": str(error),
        }, sort_keys=True), encoding="utf-8")
        os.replace(staging, final)


def ingest_bitmap_worker(data: bytes, filename: str, root: str | Path, *, mm_per_pixel: float | None) -> dict[str, Any]:
    from ingest.bitmap import ingest_key

    if len(data) > 20 * 1024 * 1024:
        raise BitmapError("bitmap upload exceeds 20 MiB")
    ingest_id = ingest_key(data, mm_per_pixel)
    root_path = Path(root).resolve()
    final = root_path / ingest_id
    root_path.mkdir(parents=True, exist_ok=True)
    # flock coordinates API processes as well as threads. Excess CPU work is
    # rejected rather than spawning an unbounded number of worker processes.
    with (root_path / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IngestUnavailable("ingest worker is busy; retry after the active task finishes") from exc
        if final.exists():
            return read_ingest(root_path, ingest_id)
        with tempfile.TemporaryDirectory(prefix=".ingest-", dir=root_path) as temp_dir:
            source = Path(temp_dir) / "input"
            source.write_bytes(data)
            output = Path(temp_dir) / ingest_id
            command = [sys.executable, "-m", "ingest.worker", "--input", str(source),
                       "--output", str(output), "--mm-per-pixel", str(mm_per_pixel),
                       f"--filename={filename}"]
            try:
                try:
                    process = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
                except subprocess.TimeoutExpired as exc:
                    raise IngestUnavailable("ingest worker timed out after 120 seconds") from exc
                except OSError as exc:
                    raise IngestUnavailable("ingest worker could not be started") from exc
                if process.returncode:
                    detail = (process.stderr or "ingest worker failed").strip()[-2000:]
                    if process.returncode in {2, 3}:
                        raise BitmapError(detail)
                    raise IngestUnavailable(detail)
                result = read_ingest(Path(temp_dir), ingest_id)
                if result["model"]["source"]["sha256"] != hashlib.sha256(data).hexdigest():
                    raise StorageIntegrityError("Worker source hash mismatch")
                os.replace(output, final)
                return result
            except (BitmapError, IngestUnavailable, StorageIntegrityError) as exc:
                _retain_failure(root_path, ingest_id, data, exc)
                raise


def _validated_roi_bbox(value: Any, pixel_size: dict[str, Any]) -> list[int]:
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise BitmapError("invalid_roi: bbox must contain four integer pixel values")
    x, y, width, height = value
    image_width, image_height = pixel_size.get("width"), pixel_size.get("height")
    if not (isinstance(image_width, int) and isinstance(image_height, int) and image_width > 0 and image_height > 0):
        raise StorageIntegrityError("Parent ingest has invalid normalized pixel dimensions")
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > image_width or y + height > image_height:
        raise BitmapError("invalid_roi: bbox must be inside the normalized source image")
    return [x, y, width, height]


def crop_ingest_worker(parent: dict[str, Any], bbox: list[int], root: str | Path) -> dict[str, Any]:
    """Run deterministic recognition on a verified parent preprocessed artifact."""
    parent_model = parent["model"]
    scale = parent_model.get("ingest", {}).get("mm_per_pixel")
    parent_id = parent["ingest_id"]
    parent_source_sha256 = parent_model["source"]["sha256"]
    candidate_id, candidate_score = None, None
    for candidate in parent_model.get("ingest", {}).get("evidence", {}).get("roi_candidates", []):
        if candidate.get("evidence_bbox") == bbox:
            candidate_id, candidate_score = candidate.get("id"), candidate.get("confidence")
            break
    ingest_id = roi_ingest_key(parent_id, parent_source_sha256, bbox, scale)
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    final = root_path / ingest_id
    with (root_path / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IngestUnavailable("ingest worker is busy; retry after the active task finishes") from exc
        if final.exists():
            return read_ingest(root_path, ingest_id)
        parent_dir = root_path / parent_id
        source_name = parent["manifest"]["files"]["source"]
        source_data = (parent_dir / source_name).read_bytes()
        if hashlib.sha256(source_data).hexdigest() != parent_source_sha256:
            raise StorageIntegrityError("Parent source artifact hash mismatch")
        # The source artifact is retained unchanged through an ROI chain. Decode
        # it afresh so EXIF orientation and dimensions always describe the root
        # normalized bitmap, never an immediate parent's cropped preprocessed PNG.
        source_asset = load_bitmap(source_data, source_name)
        bbox = _validated_roi_bbox(
            bbox, {"width": source_asset.width, "height": source_asset.height}
        )
        media_type = source_asset.media_type
        with tempfile.TemporaryDirectory(prefix=".ingest-roi-", dir=root_path) as temp_dir:
            temp = Path(temp_dir)
            input_path = temp / source_name
            source_path = temp / source_name
            output = temp / ingest_id
            input_path.write_bytes(source_data)
            source_path.write_bytes(source_data)
            command = [sys.executable, "-m", "ingest.worker", "--input", str(input_path),
                       "--output", str(output), "--mm-per-pixel", str(scale),
                       "--filename", "roi.png", "--crop-bbox", *map(str, bbox),
                       "--parent-ingest-id", parent_id, "--parent-source-sha256", parent_source_sha256,
                       "--parent-source-file", str(source_path), "--parent-source-media-type", media_type]
            if candidate_id is not None:
                command.extend(["--roi-candidate-id", str(candidate_id)])
            if candidate_score is not None:
                command.extend(["--roi-candidate-score", str(candidate_score)])
            try:
                try:
                    process = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
                except subprocess.TimeoutExpired as exc:
                    raise IngestUnavailable("ROI ingest worker timed out after 120 seconds") from exc
                except OSError as exc:
                    raise IngestUnavailable("ROI ingest worker could not be started") from exc
                if process.returncode:
                    detail = (process.stderr or "ROI ingest worker failed").strip()[-2000:]
                    if process.returncode in {2, 3}:
                        raise BitmapError(detail)
                    raise IngestUnavailable(detail)
                result = read_ingest(temp, ingest_id)
                model = result["model"]
                if (model["source"]["sha256"] != parent_source_sha256
                        or model["source"].get("parent_ingest_id") != parent_id
                        or model["ingest"].get("roi", {}).get("bbox") != bbox):
                    raise StorageIntegrityError("ROI worker provenance or source hash mismatch")
                os.replace(output, final)
                return result
            except (BitmapError, IngestUnavailable, StorageIntegrityError) as exc:
                _retain_failure(root_path, ingest_id, source_data, exc)
                raise


def ingest_response(result: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    ingest_id = result["ingest_id"]
    parent_ingest_id = result["model"].get("source", {}).get("parent_ingest_id")
    return {
        **result, "model": envelope["model"], "envelope": envelope,
        "requires_human_review": envelope["model"]["status"] == "draft",
        "source_url": f"/api/ingests/{ingest_id}/artifacts/source",
        "preprocessed_url": f"/api/ingests/{ingest_id}/artifacts/preprocessed",
        # Both names point at the verified normalized root pixels.  A child
        # preprocessed artifact is intentionally crop-local and is not suitable
        # as a global-coordinate overlay.
        "normalized_source_url": f"/api/ingests/{ingest_id}/artifacts/normalized-source",
        "overlay_url": f"/api/ingests/{ingest_id}/artifacts/normalized-source",
        "parent_source_url": (f"/api/ingests/{parent_ingest_id}/artifacts/source"
                               if isinstance(parent_ingest_id, str) else None),
        "parent_preprocessed_url": (f"/api/ingests/{parent_ingest_id}/artifacts/preprocessed"
                                     if isinstance(parent_ingest_id, str) else None),
    }
