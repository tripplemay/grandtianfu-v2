from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from scene3d import RenderError, render_model

FIXTURE = Path(__file__).resolve().parents[2] / "spatial_core/tests/fixtures/confirmed-orthogonal-merge.json"


def model() -> dict:
    return json.loads(FIXTURE.read_text())


def png_size(path: Path) -> tuple[int, int, int]:
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    return width, height, raw[25]


def test_render_writes_deterministic_passes_and_manifest(tmp_path):
    first = render_model(model(), tmp_path / "first", width=320, height=240)
    second = render_model(model(), tmp_path / "second", width=320, height=240)
    assert first["model_id"] == "fixture-living-merge-001"
    assert first["model_revision"] == 1
    assert first["camera"]["world_axes"] == "X=east,Y=south,Z=up"
    assert first["camera"]["projection"] == "cpu-perspective-v1"
    assert set(first["files"]) == {"color", "depth", "normal", "instance_mask"}
    assert first["sha256"] == second["sha256"]
    assert first["schema_version"] == "3.0"
    assert png_size(tmp_path / "first" / first["files"]["color"]) == (320, 240, 6)
    assert (tmp_path / "first" / first["files"]["color"]).stat().st_size > 100
    depth_raw = (tmp_path / "first" / first["files"]["depth"]).read_bytes()
    normal_raw = (tmp_path / "first" / first["files"]["normal"]).read_bytes()
    mask_raw = (tmp_path / "first" / first["files"]["instance_mask"]).read_bytes()
    assert len(depth_raw) == 320 * 240 * 4 and any(depth_raw)
    assert len(normal_raw) == 320 * 240 * 12 and any(normal_raw)
    assert len(mask_raw) == 320 * 240 * 4 and any(mask_raw)
    furniture_ids = {item["id"] for item in model()["furniture_instances"]}
    assert furniture_ids <= set(first["mask_values"])
    assert all(first["objects"][item_id]["mask_value"] > 0 for item_id in furniture_ids)
    assert all(first["objects"][item_id]["width"] > 0 and first["objects"][item_id]["height"] > 0 for item_id in furniture_ids)
    assert set(first["opening_geometry"]) == {item["id"] for item in model()["openings"]}
    assert json.loads((tmp_path / "first" / "manifest.json").read_text()) == first


def test_render_uses_first_camera_image_size_and_records_projection(tmp_path):
    document = model()
    document["cameras"] = [{
        "id": "camera-1", "projection": "perspective",
        "image_size": {"width": 200, "height": 150},
        "position": {"x": -5000, "y": -5000, "z": 5000},
        "look_at": {"x": 3000, "y": 2500, "z": 0},
        "up": {"x": 0, "y": 0, "z": 1},
    }]
    manifest = render_model(document, tmp_path, width=None, height=None)
    assert manifest["camera"]["id"] == "camera-1"
    assert manifest["camera"]["width"] == 200
    assert manifest["camera"]["height"] == 150
    assert manifest["camera"]["projection"] == "cpu-perspective-v1"
    assert manifest["camera"]["fov_deg"] == 50.0
    assert manifest["projection"]["near_mm"] == 10.0
    assert manifest["projection"]["far_mm"] == 100000.0


@pytest.mark.parametrize("mutator", [
    lambda value: value["rooms"].clear(),
    lambda value: value["walls"].clear(),
    lambda value: value["furniture_instances"][0]["dimensions"].update(width=1e308),
    lambda value: value["furniture_instances"][0]["transform"].update(z=float("nan")),
    lambda value: value.__setitem__("cameras", [{
        "id": "camera-1", "projection": "perspective",
        "image_size": {"width": 5000, "height": 5000},
        "position": {"x": 0, "y": 0, "z": 5000},
        "look_at": {"x": 0, "y": 0, "z": 0}, "up": {"x": 0, "y": 0, "z": 1},
    }]),
])
def test_render_rejects_unsafe_or_unrenderable_models(tmp_path, mutator):
    document = model()
    mutator(document)
    with pytest.raises(RenderError):
        render_model(document, tmp_path)


def test_render_preserves_model_and_hash(tmp_path):
    document = model()
    original = copy.deepcopy(document)
    manifest = render_model(document, tmp_path)
    assert document == original
    assert manifest["model_hash"]


def test_render_requires_confirmed_model_and_camera(tmp_path):
    document = model()
    document["status"] = "draft"
    with pytest.raises(RenderError, match="confirmed or locked"):
        render_model(document, tmp_path)
    document["status"] = "confirmed"
    document["cameras"] = []
    with pytest.raises(RenderError, match="explicit camera"):
        render_model(document, tmp_path)


def test_uint16_mask_supports_more_than_254_objects(tmp_path):
    document = model()
    for index in range(255):
        item = copy.deepcopy(document["furniture_instances"][0])
        item["id"] = f"extra-sofa-{index}"
        item["transform"]["x"] = (index % 30) * 100
        item["transform"]["y"] = (index // 30) * 100
        item["dimensions"] = {"width": 1, "depth": 1, "height": 1}
        document["furniture_instances"].append(item)
    manifest = render_model(document, tmp_path)
    assert max(manifest["mask_values"].values()) > 254
    assert (tmp_path / manifest["files"]["instance_mask"]).stat().st_size == manifest["camera"]["width"] * manifest["camera"]["height"] * 4


def test_failed_render_does_not_publish_partial_output(tmp_path):
    output = tmp_path / "render"
    original = render_model(model(), output)
    invalid = model()
    invalid["status"] = "draft"
    with pytest.raises(RenderError):
        render_model(invalid, output)
    assert json.loads((output / "manifest.json").read_text()) == original
    assert not list(tmp_path.glob(f".{output.name}.*"))
