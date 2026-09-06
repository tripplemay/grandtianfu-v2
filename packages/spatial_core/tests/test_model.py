import copy
import json
from pathlib import Path

import pytest

from spatial_core import ModelValidationError, canonical_hash, validate_model


FIXTURE = Path(__file__).parent / "fixtures" / "confirmed-orthogonal-merge.json"


def base_model():
    return json.loads(FIXTURE.read_text())


def assert_invalid(model, text):
    with pytest.raises(ModelValidationError, match=text):
        validate_model(model)


def test_confirmed_orthogonal_merge_fixture_is_valid():
    model = base_model()
    assert validate_model(model) is model


def test_canonical_hash_is_stable_and_changes_with_content():
    model = base_model()
    assert canonical_hash(model) == canonical_hash(copy.deepcopy(model))
    model["revision"] = 2
    assert canonical_hash(model) != canonical_hash(base_model())


def test_duplicate_ids_are_rejected_across_collections():
    model = base_model()
    model["rooms"][0]["id"] = model["walls"][0]["id"]
    assert_invalid(model, "duplicate id")


def test_non_orthogonal_wall_is_rejected():
    model = base_model()
    model["walls"][0]["axis"] = "diagonal"
    assert_invalid(model, "axis")


def test_unknown_room_reference_is_rejected():
    model = base_model()
    model["furniture_instances"][0]["room_id"] = "missing"
    assert_invalid(model, "unknown room")


def test_unknown_opening_host_is_rejected():
    model = base_model()
    model["openings"] = [{
        "id": "window-1",
        "host_wall_id": "missing",
        "width": 1200,
        "height": 1400,
        "bottom_z": 900,
        "offset": 500,
        "kind": "window",
    }]
    assert_invalid(model, "unknown wall")


def test_opening_outside_host_wall_is_rejected():
    model = base_model()
    model["openings"] = [{
        "id": "window-1",
        "host_wall_id": "wall-n",
        "width": 1200,
        "height": 1400,
        "bottom_z": 900,
        "offset": 5200,
        "kind": "window",
    }]
    assert_invalid(model, "inside host wall")


def test_furniture_outside_room_is_rejected():
    model = base_model()
    model["furniture_instances"][0]["transform"]["x"] = 5900
    assert_invalid(model, "inside room")


def test_overlapping_furniture_is_rejected():
    model = base_model()
    second = copy.deepcopy(model["furniture_instances"][0])
    second["id"] = "sofa-2"
    second["transform"]["x"] = 1800
    model["furniture_instances"].append(second)
    assert_invalid(model, "collides")


def test_room_boundary_must_cover_all_four_sides():
    model = base_model()
    model["rooms"][0]["boundary_wall_ids"] = ["wall-n"] * 4
    assert_invalid(model, "cover side")


def test_fractional_rotation_is_rejected_for_mvp():
    model = base_model()
    model["furniture_instances"][0]["transform"]["rotation_z"] = 15
    assert_invalid(model, "multiple of 90")


def test_incomplete_camera_is_rejected():
    model = base_model()
    model["cameras"] = [{"id": "camera-1", "projection": "perspective"}]
    assert_invalid(model, "image_size")
