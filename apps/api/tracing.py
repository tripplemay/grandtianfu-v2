"""API orchestration for deterministic manual rectangle traces."""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path
from typing import Any

from ingest import BitmapError
from ingest.tracing import trace_ingest_from_parent

from .ingest import IngestUnavailable, read_ingest
from .revisions import checked_model


def trace_ingest_worker(parent: dict[str, Any], *, bbox: Any, rooms: Any,
                        wall_thickness_mm: Any, wall_height_mm: Any,
                        root: str | Path) -> dict[str, Any]:
    """Create or reuse a trace artifact while holding the single-worker lock."""
    parent_model = parent["model"]
    parent_id = parent["ingest_id"]
    parent_hash = parent_model.get("source", {}).get("sha256")
    if parent_model.get("source", {}).get("kind") != "bitmap" or not isinstance(parent_hash, str):
        raise BitmapError("invalid_trace: parent ingest must be a bitmap")
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    lock_path = root_path / ".worker.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IngestUnavailable("ingest worker is busy; retry after the active task finishes") from exc
        source_name = parent["manifest"]["files"]["source"]
        source_data = (root_path / parent_id / source_name).read_bytes()
        model, asset = trace_ingest_from_parent(source_data, parent_ingest_id=parent_id,
            parent_source_sha256=parent_hash, parent_model=parent_model, bbox=bbox, rooms=rooms,
            wall_thickness_mm=wall_thickness_mm, wall_height_mm=wall_height_mm)
        checked_model(model)
        trace_id = model["ingest"]["ingest_id"]
        final = root_path / trace_id
        if final.exists():
            return read_ingest(root_path, trace_id)
        with tempfile.TemporaryDirectory(prefix=".ingest-trace-", dir=root_path) as temp_dir:
            staging = Path(temp_dir) / trace_id
            from ingest.worker import _write_outputs
            _write_outputs(staging, model, asset, "source", source_data=source_data, source_media_type=asset.media_type)
            result = read_ingest(Path(temp_dir), trace_id)
            os.replace(staging, final)
            return result
