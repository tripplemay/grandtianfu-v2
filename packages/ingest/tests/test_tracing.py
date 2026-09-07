from __future__ import annotations

import hashlib
import io

import pytest
from ingest.tracing import trace_ingest_from_parent
from PIL import Image


def _source() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (200, 120), "white").save(stream, format="PNG")
    return stream.getvalue()


def _parent(data: bytes) -> dict:
    return {"source": {"sha256": hashlib.sha256(data).hexdigest()},
            "ingest": {"mm_per_pixel": 10.0, "calibration": {"value": 10.0}}}


def test_trace_deduplicates_shared_edges_but_keeps_gaps() -> None:
    data = _source()
    kwargs = {"parent_ingest_id": "a" * 64, "parent_source_sha256": hashlib.sha256(data).hexdigest(),
              "parent_model": _parent(data), "bbox": [0, 0, 200, 120],
              "rooms": [{"name": "A", "kind": "living", "rect": [10, 10, 50, 40]},
                        {"name": "B", "kind": "bed", "rect": [61, 10, 50, 40]}],
              "wall_thickness_mm": 200, "wall_height_mm": 2800}
    model, asset = trace_ingest_from_parent(data, **kwargs)
    assert len(model["walls"]) == 8  # separated rooms have no shared edge
    assert asset.normalized_png
    kwargs["rooms"] = [{"name": "A", "kind": "living", "rect": [10, 10, 50, 40]},
                        {"name": "B", "kind": "bed", "rect": [60, 10, 50, 40]}]
    model2, _ = trace_ingest_from_parent(data, **kwargs)
    assert len(model2["walls"]) == 5


@pytest.mark.parametrize("bbox", [[0, 0, 0, 10], [0, 0, 201, 10], [0, 0, 1.0, 2]])
def test_trace_rejects_invalid_bbox(bbox: list) -> None:
    data = _source()
    with pytest.raises(ValueError):
        trace_ingest_from_parent(data, parent_ingest_id="a" * 64,
            parent_source_sha256=hashlib.sha256(data).hexdigest(), parent_model=_parent(data), bbox=bbox,
            rooms=[{"name": "A", "kind": "living", "rect": [0, 0, 1, 1]}], wall_thickness_mm=200, wall_height_mm=2800)


def test_trace_rejects_overlap_and_preserves_parent_blockers() -> None:
    data = _source()
    parent = _parent(data)
    parent["ingest"]["hard_blockers"] = [{"code": "partial_plan_requires_manual_trace"}]
    with pytest.raises(ValueError):
        trace_ingest_from_parent(data, parent_ingest_id="a" * 64,
            parent_source_sha256=parent["source"]["sha256"], parent_model=parent, bbox=[0, 0, 200, 120],
            rooms=[{"name": "A", "kind": "living", "rect": [0, 0, 30, 30]},
                   {"name": "B", "kind": "bed", "rect": [20, 20, 30, 30]}], wall_thickness_mm=200, wall_height_mm=2800)
    model, _ = trace_ingest_from_parent(data, parent_ingest_id="a" * 64,
        parent_source_sha256=parent["source"]["sha256"], parent_model=parent, bbox=[0, 0, 200, 120],
        rooms=[{"name": "A", "kind": "living", "rect": [0, 0, 30, 30]}], wall_thickness_mm=200, wall_height_mm=2800)
    assert model["ingest"]["trace"]["superseded_blockers"] == parent["ingest"]["hard_blockers"]
    assert model["ingest"]["hard_blockers"][0]["code"] == "manual_trace_requires_topology_review"
