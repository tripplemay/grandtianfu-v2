"""API orchestration for immutable manual topology review artifacts."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from ingest import BitmapError
from ingest.topology import topology_ingest_from_parent

from .ingest import IngestUnavailable, read_ingest
from .revisions import StorageIntegrityError, checked_model


def topology_ingest_worker(parent: dict[str, Any], *, openings: Any, merge_groups: Any,
                           reviewed_object_ids: Any, root: str | Path) -> dict[str, Any]:
    """Create or reuse a topology artifact while holding the bounded worker lock."""
    parent_model = parent["model"]
    parent_id = parent["ingest_id"]
    parent_hash = parent_model.get("source", {}).get("sha256")
    if parent_model.get("source", {}).get("kind") != "bitmap" or not isinstance(parent_hash, str):
        raise BitmapError("invalid_topology: parent ingest must be a bitmap")
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    with (root_path / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IngestUnavailable("ingest worker is busy; retry after the active task finishes") from exc
        source_name = parent["manifest"]["files"]["source"]
        parent_dir = root_path / parent_id
        try:
            source_data = (parent_dir / source_name).read_bytes()
        except OSError as exc:
            raise StorageIntegrityError("Parent source artifact could not be read") from exc
        if hashlib.sha256(source_data).hexdigest() != parent_hash:
            raise StorageIntegrityError("Parent source artifact hash mismatch")
        model, asset = topology_ingest_from_parent(
            source_data, parent_ingest_id=parent_id, parent_source_sha256=parent_hash,
            parent_model=parent_model, openings=openings, merge_groups=merge_groups,
            reviewed_object_ids=reviewed_object_ids,
        )
        checked_model(model)
        topology_id = model["ingest"]["ingest_id"]
        final = root_path / topology_id
        if final.exists():
            return read_ingest(root_path, topology_id)
        with tempfile.TemporaryDirectory(prefix=".ingest-topology-", dir=root_path) as temp_dir:
            staging = Path(temp_dir) / topology_id
            from ingest.worker import _write_outputs
            _write_outputs(staging, model, asset, "source", source_data=source_data, source_media_type=asset.media_type)
            result = read_ingest(Path(temp_dir), topology_id)
            os.replace(staging, final)
            return result

