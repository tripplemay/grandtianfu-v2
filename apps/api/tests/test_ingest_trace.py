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


def test_manual_trace_is_idempotent_and_confirm_blocked(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        upload = client.post("/api/ingests?mm_per_pixel=10", content=_png(), headers={"content-type": "image/png"})
        assert upload.status_code == 201, upload.text
        parent = upload.json()
        body = {"expected_source_sha256": parent["model"]["source"]["sha256"], "bbox": [0, 0, 100, 80],
                "rooms": [{"name": "Living", "kind": "living", "rect": [10.5, 10, 30, 20]}],
                "wall_thickness_mm": 180, "wall_height_mm": 2800}
        first = client.post(f"/api/ingests/{parent['ingest_id']}/trace", json=body)
        second = client.post(f"/api/ingests/{parent['ingest_id']}/trace", json=body)
        assert first.status_code == second.status_code == 201
        assert first.json()["ingest_id"] == second.json()["ingest_id"]
        traced = first.json()
        assert traced["model"]["openings"] == []
        assert traced["model"]["ingest"]["hard_blockers"][0]["code"] == "manual_trace_requires_topology_review"
        confirm = client.post(f"/api/ingests/{traced['ingest_id']}/confirm", json={
            "expected_revision": 1, "expected_hash": traced["envelope"]["hash"],
            "reviewed_object_ids": [item["id"] for key in ("rooms", "walls", "openings") for item in traced["model"][key]],
            "checks": {"scale": True, "geometry": True, "openings": True, "heights": True}, "reviewer": "tester"})
        assert confirm.status_code == 422


def test_trace_rejects_stale_hash_and_extra_fields(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        upload = client.post("/api/ingests?mm_per_pixel=10", content=_png(), headers={"content-type": "image/png"})
        parent = upload.json()
        body = {"expected_source_sha256": "0" * 64, "bbox": [0, 0, 100, 80], "rooms": [],
                "wall_thickness_mm": 100, "wall_height_mm": 2800}
        assert client.post(f"/api/ingests/{parent['ingest_id']}/trace", json=body).status_code == 409
        body["unexpected"] = 1
        assert client.post(f"/api/ingests/{parent['ingest_id']}/trace", json=body).status_code == 422


def test_trace_rejects_boolean_nan_overlap_and_room_limit(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        parent = client.post("/api/ingests?mm_per_pixel=10", content=_png(), headers={"content-type": "image/png"}).json()
        endpoint = f"/api/ingests/{parent['ingest_id']}/trace"
        base = {"expected_source_sha256": parent["model"]["source"]["sha256"], "bbox": [0, 0, 100, 80],
                "rooms": [{"name": "A", "kind": "living", "rect": [1, 1, 20, 20]}],
                "wall_thickness_mm": 100, "wall_height_mm": 2800}
        for key, value in (("wall_thickness_mm", True), ("bbox", [0, 0, 101, 80]),
                           ("rooms", [{"name": "A", "kind": "living", "rect": [1, 1, 20, 20]},
                                      {"name": "A", "kind": "bed", "rect": [30, 30, 20, 20]}])):
            payload = {**base, key: value}
            assert client.post(endpoint, json=payload).status_code == 422
        response = client.post(endpoint, content=(
            f'{{"expected_source_sha256":"{base["expected_source_sha256"]}","bbox":[0,0,100,80],'
            '"rooms":[{"name":"A","kind":"living","rect":[1,1,20,20]}],'
            '"wall_thickness_mm":NaN,"wall_height_mm":2800}'
        ), headers={"content-type": "application/json"})
        assert response.status_code == 422
        too_many = [{"name": str(i), "kind": "room", "rect": [0, 0, 0.5, 0.5]} for i in range(65)]
        assert client.post(endpoint, json={**base, "rooms": too_many}).status_code == 422


def test_trace_busy_lock_and_parent_tamper(tmp_path: Path) -> None:
    root = tmp_path / "ingests"
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=root)) as client:
        parent = client.post("/api/ingests?mm_per_pixel=10", content=_png(), headers={"content-type": "image/png"}).json()
        lock = (root / ".worker.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            body = {"expected_source_sha256": parent["model"]["source"]["sha256"], "bbox": [0, 0, 100, 80],
                    "rooms": [{"name": "A", "kind": "living", "rect": [1, 1, 20, 20]}],
                    "wall_thickness_mm": 100, "wall_height_mm": 2800}
            assert client.post(f"/api/ingests/{parent['ingest_id']}/trace", json=body).status_code == 503
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        source = root / parent["ingest_id"] / "source.png"
        source.write_bytes(b"tampered")
        assert client.post(f"/api/ingests/{parent['ingest_id']}/trace", json=body).status_code == 500
