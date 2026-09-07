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


def ingest_response(result: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    ingest_id = result["ingest_id"]
    return {
        **result, "model": envelope["model"], "envelope": envelope,
        "requires_human_review": envelope["model"]["status"] == "draft",
        "source_url": f"/api/ingests/{ingest_id}/artifacts/source",
        "preprocessed_url": f"/api/ingests/{ingest_id}/artifacts/preprocessed",
    }
