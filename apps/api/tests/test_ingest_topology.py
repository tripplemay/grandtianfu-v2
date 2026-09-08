from __future__ import annotations

import fcntl
import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from apps.api.app import create_app


def _png() -> bytes:
    stream = io.BytesIO()
    image = Image.new("RGB", (100, 80), "white")
    pixels = image.load()
    for x in range(10, 91):
        for y in range(10, 71):
            if x < 13 or x > 87 or y < 13 or y > 67:
                pixels[x, y] = (0, 0, 0)
    image.save(stream, format="PNG")
    return stream.getvalue()


def _trace(client: TestClient) -> dict:
    parent = client.post("/api/ingests?mm_per_pixel=10", content=_png(), headers={"content-type": "image/png"}).json()
    response = client.post(f"/api/ingests/{parent['ingest_id']}/trace", json={
        "expected_source_sha256": parent["model"]["source"]["sha256"], "bbox": [0, 0, 100, 80],
        "rooms": [
            {"name": "A", "kind": "living", "rect": [10, 10, 30, 40]},
            {"name": "B", "kind": "bed", "rect": [40, 10, 30, 40]},
        ], "wall_thickness_mm": 100, "wall_height_mm": 2800,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _topology_body(trace: dict) -> dict:
    model = trace["model"]
    wall = next(item for item in model["walls"] if item["axis"] == "v" and item["x"] == 400)
    reviewed = [item["id"] for key in ("rooms", "walls", "openings") for item in model[key]]
    return {
        "expected_source_sha256": model["source"]["sha256"],
        "openings": [{"id": "door-1", "host_wall_id": wall["id"], "kind": "door", "offset": 100,
                      "width": 200, "height": 2100, "bottom_z": 0}],
        "merge_groups": [{"id": "merge-1", "room_ids": [model["rooms"][0]["id"], model["rooms"][1]["id"]]}],
        "reviewed_object_ids": reviewed + ["door-1", "merge-1"],
    }


def test_topology_is_idempotent_and_retains_parent_blocker(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        trace = _trace(client)
        body = _topology_body(trace)
        first = client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=body)
        second = client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=body)
        assert first.status_code == second.status_code == 201, first.text
        assert first.json()["ingest_id"] == second.json()["ingest_id"]
        model = first.json()["model"]
        assert model["source"]["provenance"] == "manual_topology"
        assert model["rooms"][0]["merge_group_id"] == "merge-1"
        assert model["openings"][0]["provenance"] == "manual_topology"
        assert model["ingest"]["hard_blockers"][0]["code"] == "manual_trace_requires_topology_review"
        assert body["expected_source_sha256"] == trace["model"]["source"]["sha256"]
        assert trace["model"]["rooms"][0].get("merge_group_id") is None


def test_topology_rejects_stale_extra_and_invalid_geometry(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        trace = _trace(client)
        endpoint = f"/api/ingests/{trace['ingest_id']}/topology"
        body = _topology_body(trace)
        body["expected_source_sha256"] = "0" * 64
        assert client.post(endpoint, json=body).status_code == 409
        body = _topology_body(trace)
        body["openings"][0]["offset"] = 99999
        assert client.post(endpoint, json=body).status_code == 422
        body = _topology_body(trace)
        body["merge_groups"][0]["room_ids"] = [trace["model"]["rooms"][0]["id"], "unknown"]
        assert client.post(endpoint, json=body).status_code == 422
        body = _topology_body(trace)
        body["unexpected"] = 1
        assert client.post(endpoint, json=body).status_code == 422


def test_topology_rejects_non_adjacent_merge(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        parent = client.post("/api/ingests?mm_per_pixel=10", content=_png(), headers={"content-type": "image/png"}).json()
        trace_response = client.post(f"/api/ingests/{parent['ingest_id']}/trace", json={
            "expected_source_sha256": parent["model"]["source"]["sha256"], "bbox": [0, 0, 100, 80],
            "rooms": [{"name": "A", "kind": "living", "rect": [10, 10, 20, 20]},
                      {"name": "B", "kind": "bed", "rect": [30, 10, 20, 20]},
                      {"name": "C", "kind": "study", "rect": [70, 50, 20, 20]}],
            "wall_thickness_mm": 100, "wall_height_mm": 2800,
        })
        assert trace_response.status_code == 201
        trace = trace_response.json()
        model = trace["model"]
        ids = [item["id"] for key in ("rooms", "walls", "openings") for item in model[key]]
        body = {"expected_source_sha256": model["source"]["sha256"], "openings": [],
                "merge_groups": [{"id": "bad", "room_ids": [model["rooms"][0]["id"], model["rooms"][2]["id"]]}],
                "reviewed_object_ids": ids + ["bad"]}
        assert client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=body).status_code == 422


def test_topology_rejects_parent_tamper(tmp_path: Path) -> None:
    root = tmp_path / "ingests"
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=root)) as client:
        trace = _trace(client)
        body = _topology_body(trace)
        source = root / trace["ingest_id"] / "source.png"
        source.write_bytes(b"tampered")
        assert client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=body).status_code == 500


def test_topology_t_shape_requires_opening_to_hit_shared_segment(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        parent = client.post("/api/ingests?mm_per_pixel=10", content=_png(), headers={"content-type": "image/png"}).json()
        trace = client.post(f"/api/ingests/{parent['ingest_id']}/trace", json={
            "expected_source_sha256": parent["model"]["source"]["sha256"], "bbox": [0, 0, 100, 80],
            "rooms": [{"name": "A", "kind": "living", "rect": [10, 10, 40, 40]},
                      {"name": "B", "kind": "bed", "rect": [50, 20, 10, 20]}],
            "wall_thickness_mm": 100, "wall_height_mm": 2800,
        }).json()
        model = trace["model"]
        shared = set(model["rooms"][0]["boundary_wall_ids"]) & set(model["rooms"][1]["boundary_wall_ids"])
        wall_id = next(iter(shared))
        ids = [item["id"] for key in ("rooms", "walls", "openings") for item in model[key]]
        body = {"expected_source_sha256": model["source"]["sha256"], "openings": [{"id": "outside", "host_wall_id": wall_id,
                "kind": "door", "offset": 0, "width": 50, "height": 2100, "bottom_z": 0}],
                "merge_groups": [{"id": "merge-t", "room_ids": [model["rooms"][0]["id"], model["rooms"][1]["id"]]}],
                "reviewed_object_ids": ids + ["outside", "merge-t"]}
        assert client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=body).status_code == 422
        body["openings"][0].update({"id": "inside", "offset": 120, "width": 100})
        body["reviewed_object_ids"] = ids + ["inside", "merge-t"]
        assert client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=body).status_code == 201


def test_topology_busy_worker_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ingests"
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=root)) as client:
        trace = _trace(client)
        lock = (root / ".worker.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            assert client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=_topology_body(trace)).status_code == 503
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
