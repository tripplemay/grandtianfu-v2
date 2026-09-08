"""Server-side proof for confirming a manual topology ingest."""

from __future__ import annotations

import fcntl
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from ingest import BitmapError
from ingest.topology import topology_ingest_from_parent
from spatial_core import canonical_hash

from .ingest import IngestUnavailable, read_ingest
from .revisions import InvalidModel, StorageIntegrityError, checked_model


def _without_review(value: Any) -> Any:
    """Return a comparison copy with review-only flags removed recursively."""
    if isinstance(value, dict):
        return {key: _without_review(item) for key, item in value.items() if key != "needs_review"}
    if isinstance(value, list):
        return [_without_review(item) for item in value]
    return value


def _artifact_error(message: str, exc: Exception | None = None) -> StorageIntegrityError:
    error = StorageIntegrityError(message)
    if exc is not None:
        error.__cause__ = exc
    return error


def _topology_metadata(model: dict[str, Any]) -> dict[str, Any] | None:
    ingest = model.get("ingest")
    topology = ingest.get("topology") if isinstance(ingest, dict) else None
    if model.get("source", {}).get("provenance") != "manual_topology" and topology is None:
        return None
    if not isinstance(topology, dict):
        raise _artifact_error("Topology ingest metadata is missing or invalid")
    return topology


def _sanitized_topology_inputs(metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    try:
        openings = metadata["openings"]
        groups = metadata["merge_groups"]
        reviewed = metadata["reviewed_object_ids"]
    except (KeyError, TypeError) as exc:
        raise _artifact_error("Topology recipe is incomplete", exc)
    if not isinstance(openings, list) or not isinstance(groups, list) or not isinstance(reviewed, list):
        raise _artifact_error("Topology recipe has invalid array fields")
    allowed_opening = {"id", "host_wall_id", "kind", "offset", "width", "height", "bottom_z"}
    allowed_group = {"id", "room_ids"}
    clean_openings: list[dict[str, Any]] = []
    clean_groups: list[dict[str, Any]] = []
    for item in openings:
        if not isinstance(item, dict):
            raise _artifact_error("Topology recipe contains invalid opening fields")
        if not allowed_opening.issubset(item) and not (allowed_opening - {"id"}).issubset(item):
            raise _artifact_error("Topology recipe contains an empty opening")
        clean_openings.append({key: deepcopy(item[key]) for key in allowed_opening if key in item})
    for item in groups:
        if not isinstance(item, dict):
            raise _artifact_error("Topology recipe contains invalid merge fields")
        if not allowed_group.issubset(item) and not (allowed_group - {"id"}).issubset(item):
            raise _artifact_error("Topology recipe contains an incomplete merge field")
        clean_groups.append({key: deepcopy(item[key]) for key in allowed_group if key in item})
    if any(not isinstance(item, str) for item in reviewed):
        raise _artifact_error("Topology recipe contains invalid reviewed object ids")
    return clean_openings, clean_groups, list(reviewed)


def verify_topology_reference(result: dict, root: Path) -> dict | None:
    """Verify and replay a topology artifact, returning its original model."""
    if not isinstance(result, dict) or not isinstance(result.get("model"), dict):
        raise _artifact_error("Topology result is invalid")
    model = result["model"]
    metadata = _topology_metadata(model)
    if metadata is None:
        return None

    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    # The topology worker and this verifier share one bounded decode slot.
    with (root_path / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IngestUnavailable("ingest worker is busy; retry after the active task finishes") from exc
        try:
            parent_id = metadata.get("parent_ingest_id")
            parent_source_hash = metadata.get("parent_source_sha256")
            parent_model_hash = metadata.get("parent_model_hash")
            if not all(isinstance(value, str) and value for value in (parent_id, parent_source_hash, parent_model_hash)):
                raise _artifact_error("Topology parent identity is invalid")
            if model.get("source", {}).get("parent_ingest_id") != parent_id:
                raise _artifact_error("Topology parent ingest identity mismatch")
            parent = read_ingest(root_path, parent_id)
            parent_model = parent["model"]
            if parent_model.get("source", {}).get("provenance") != "manual_trace":
                raise _artifact_error("Topology parent is not a manual trace artifact")
            if canonical_hash(parent_model) != parent_model_hash:
                raise _artifact_error("Topology parent model hash mismatch")
            source_name = parent["manifest"]["files"]["source"]
            source_path = root_path / parent_id / source_name
            source_data = source_path.read_bytes()
            if hashlib.sha256(source_data).hexdigest() != parent_source_hash:
                raise _artifact_error("Topology parent source hash mismatch")
            if model.get("source", {}).get("sha256") != parent_source_hash:
                raise _artifact_error("Topology source hash mismatch")
            openings, groups, reviewed = _sanitized_topology_inputs(metadata)
            replay, _ = topology_ingest_from_parent(
                source_data,
                parent_ingest_id=parent_id,
                parent_source_sha256=parent_source_hash,
                parent_model=parent_model,
                openings=openings,
                merge_groups=groups,
                reviewed_object_ids=reviewed,
            )
            try:
                checked_model(model)
                checked_model(replay)
            except InvalidModel as exc:
                raise _artifact_error("Topology artifact model is invalid", exc)
            if canonical_hash(replay) != canonical_hash(model):
                raise _artifact_error("Topology replay does not match stored model")
            return model
        except StorageIntegrityError:
            raise
        except (OSError, KeyError, TypeError, ValueError, BitmapError) as exc:
            raise _artifact_error("Topology artifacts are incomplete or corrupt", exc)


def topology_confirmation_evidence(current_model: dict, reference: dict) -> dict:
    """Compare a user draft with a verified topology artifact and issue proof."""
    checked_model(current_model)
    try:
        checked_model(reference)
    except InvalidModel as exc:
        raise _artifact_error("Verified topology reference is invalid", exc)
    current_topology = _topology_metadata(current_model)
    reference_topology = _topology_metadata(reference)
    if current_topology is None or reference_topology is None:
        raise InvalidModel("topology confirmation requires a verified topology artifact")

    for key in ("source", "ingest"):
        if _without_review(current_model.get(key)) != _without_review(reference.get(key)):
            raise InvalidModel(f"model.{key} does not match topology reference")
    for key in ("units", "coordinates", "rooms", "walls", "openings"):
        if _without_review(current_model.get(key)) != _without_review(reference.get(key)):
            raise InvalidModel(f"model.{key} does not match topology reference")
    for index, room in enumerate(current_model["rooms"]):
        if not isinstance(room.get("kind"), str) or not room["kind"].strip() or room["kind"].strip().lower() == "unknown":
            raise InvalidModel(f"rooms[{index}].kind must be classified")
    for index, opening in enumerate(current_model["openings"]):
        if opening.get("kind") not in {"door", "window", "passage"}:
            raise InvalidModel(f"openings[{index}].kind must be door, window or passage")
    object_ids = {item["id"] for key in ("rooms", "walls", "openings") for item in current_model[key]}
    group_ids = {room["merge_group_id"] for room in current_model["rooms"] if room.get("merge_group_id")}
    if object_ids & group_ids:
        raise InvalidModel("merge group ids must not collide with reviewed object ids")

    parent_ingest_id = reference_topology.get("parent_ingest_id")
    parent_model_hash = reference_topology.get("parent_model_hash")
    source_hash = reference_topology.get("parent_source_sha256")
    topology_ingest_id = reference.get("ingest", {}).get("ingest_id")
    if not all(isinstance(value, str) and value for value in (parent_ingest_id, parent_model_hash, source_hash, topology_ingest_id)):
        raise _artifact_error("Topology reference identity is incomplete")
    geometry_hash = canonical_hash({key: _without_review(reference[key]) for key in ("rooms", "walls", "openings")})
    return {
        "topology_ingest_id": topology_ingest_id,
        "topology_model_hash": canonical_hash(reference),
        "parent_ingest_id": parent_ingest_id,
        "parent_model_hash": parent_model_hash,
        "geometry_hash": geometry_hash,
        "scope": "traced_regions",
        "resolved_blocker_codes": ["manual_trace_requires_topology_review"],
    }
