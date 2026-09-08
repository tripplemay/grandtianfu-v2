from __future__ import annotations

import pytest
from ingest.bitmap import BitmapError
from ingest.topology import (
    _merge_input,
    _opening_connects_rooms,
    _opening_input,
    topology_ingest_key,
)


def test_topology_inputs_are_strict_and_normalized() -> None:
    opening = _opening_input({"id": "door-1", "host_wall_id": "wall-1", "kind": "door",
                              "offset": 100, "width": 900, "height": 2100, "bottom_z": 0}, 0)
    assert opening == {"id": "door-1", "host_wall_id": "wall-1", "kind": "door",
                      "offset": 100.0, "width": 900.0, "height": 2100.0, "bottom_z": 0.0}
    assert _merge_input({"id": "merge-1", "room_ids": ["room-1", "room-2"]}, 0) == {
        "id": "merge-1", "room_ids": ["room-1", "room-2"]
    }


def test_topology_inputs_reject_extra_fields_and_bad_numbers() -> None:
    with pytest.raises(BitmapError, match="unexpected fields"):
        _opening_input({"host_wall_id": "wall-1", "kind": "door", "offset": 0, "width": 900,
                        "height": 2100, "bottom_z": 0, "extra": True}, 0)
    with pytest.raises(BitmapError, match="finite number"):
        _opening_input({"host_wall_id": "wall-1", "kind": "door", "offset": float("nan"), "width": 900,
                        "height": 2100, "bottom_z": 0}, 0)
    with pytest.raises(BitmapError, match="at least two"):
        _merge_input({"room_ids": ["room-1"]}, 0)


def test_topology_key_is_stable_for_same_review() -> None:
    args = ([{"id": "door-1", "host_wall_id": "wall-1", "kind": "door", "offset": 0,
              "width": 900, "height": 2100, "bottom_z": 0}], [{"id": "merge-1", "room_ids": ["a", "b"]}], ["a", "b"])
    assert topology_ingest_key("parent", "source", "model", *args) == topology_ingest_key("parent", "source", "model", *args)


def test_opening_must_intersect_the_shared_boundary_segment() -> None:
    left = {"rect": [0, 0, 400, 400], "boundary_wall_ids": ["w"]}
    right = {"rect": [400, 200, 100, 200], "boundary_wall_ids": ["w"]}
    walls = {"w": {"axis": "v", "x": 400, "y": 0, "length": 400}}
    outside = {"host_wall_id": "w", "offset": 0, "width": 100}
    inside = {"host_wall_id": "w", "offset": 220, "width": 100}
    assert not _opening_connects_rooms(outside, left, right, walls)
    assert _opening_connects_rooms(inside, left, right, walls)
