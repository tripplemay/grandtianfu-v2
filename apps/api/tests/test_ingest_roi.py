from __future__ import annotations

import hashlib
import io
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from apps.api.app import create_app


def plan_png() -> bytes:
    width, height = 400, 300
    pixels = bytearray([255] * (width * height))
    for y in range(30, 271):
        for x in range(40, 361):
            if x in range(40, 46) or x in range(355, 361) or y in range(30, 36) or y in range(265, 271):
                pixels[y * width + x] = 0
    raw = b"".join(b"\x00" + pixels[row * width:(row + 1) * width] for row in range(height))
    def chunk(kind: bytes, value: bytes) -> bytes:
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as value:
        yield value


def _upload(client: TestClient) -> dict:
    response = client.post("/api/ingests?mm_per_pixel=10", content=plan_png(),
                           headers={"content-type": "image/png", "x-filename": "poster.png"})
    assert response.status_code == 201, response.text
    return response.json()


def _crop(client: TestClient, parent: dict, bbox: list) -> object:
    return client.post(f"/api/ingests/{parent['ingest_id']}/crop",
                       json={"expected_source_sha256": parent["model"]["source"]["sha256"], "bbox": bbox})


def test_manual_roi_keeps_parent_overlay_and_maps_geometry(client: TestClient):
    parent = _upload(client)
    bbox = parent["model"]["ingest"]["evidence"]["roi_candidates"][0]["evidence_bbox"]
    bbox = [int(value) for value in bbox]
    response = _crop(client, parent, bbox)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["ingest_id"] != parent["ingest_id"]
    model = result["model"]
    assert model["source"]["sha256"] == parent["model"]["source"]["sha256"]
    assert model["source"]["parent_ingest_id"] == parent["ingest_id"]
    assert model["ingest"]["roi"]["bbox"] == bbox
    assert model["ingest"]["roi"]["candidate_id"] == parent["model"]["ingest"]["evidence"]["roi_candidates"][0]["id"]
    assert model["ingest"]["roi"]["candidate_score"] == parent["model"]["ingest"]["evidence"]["roi_candidates"][0]["confidence"]
    assert model["ingest"]["pixel_size"] == parent["model"]["ingest"]["pixel_size"]
    assert model["ingest"]["preprocessing"]["source_sha256"] == model["source"]["sha256"]
    assert model["ingest"]["preprocessing"]["crop_source_sha256"] != model["source"]["sha256"]
    assert model["rooms"][0]["rect"][0] >= bbox[0] * 10
    assert result["source_url"].endswith("/source")
    assert result["parent_source_url"].endswith(f"{parent['ingest_id']}/artifacts/source")

    source = client.get(result["source_url"])
    cropped = client.get(result["preprocessed_url"])
    assert source.status_code == 200 and source.content == client.get(parent["source_url"]).content
    assert cropped.status_code == 200
    with Image.open(io.BytesIO(cropped.content)) as image:
        assert image.size == (bbox[2], bbox[3])


def test_roi_is_deterministic_and_rejects_out_of_bounds(client: TestClient):
    parent = _upload(client)
    bbox = parent["model"]["ingest"]["evidence"]["roi_candidates"][0]["evidence_bbox"]
    bbox = [int(value) for value in bbox]
    first = _crop(client, parent, bbox)
    second = _crop(client, parent, bbox)
    assert first.status_code == second.status_code == 201
    assert first.json()["ingest_id"] == second.json()["ingest_id"]
    size = parent["model"]["ingest"]["pixel_size"]
    for invalid in ([0, 0, size["width"] + 1, 10], [-1, 0, 10, 10], [0, 0, 0, 10], [0, 0, 10.0, 10]):
        response = _crop(client, parent, invalid)
        assert response.status_code == 422
    assert hashlib.sha256(client.get(parent["source_url"]).content).hexdigest() == parent["model"]["source"]["sha256"]


def test_parent_artifact_tampering_blocks_roi(client: TestClient, tmp_path: Path):
    parent = _upload(client)
    source_path = tmp_path / "ingests" / parent["ingest_id"] / "source.png"
    source_path.write_bytes(b"tampered")
    response = _crop(client, parent, [36, 26, 329, 249])
    assert response.status_code == 500
    assert response.json()["code"] == "storage_integrity_error"


def test_roi_source_compare_and_swap_rejects_forged_hash(client: TestClient):
    parent = _upload(client)
    response = client.post(f"/api/ingests/{parent['ingest_id']}/crop",
                           json={"expected_source_sha256": "0" * 64, "bbox": [36, 26, 329, 249]})
    assert response.status_code == 409


def test_nested_roi_uses_root_source_and_global_overlay(client: TestClient):
    result = _upload(client)
    source_hash = result["model"]["source"]["sha256"]
    for bbox in ([36, 26, 329, 249], [40, 30, 321, 241], [45, 35, 311, 231]):
        response = _crop(client, result, bbox)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["model"]["source"]["sha256"] == source_hash
        assert result["model"]["ingest"]["pixel_size"] == {"width": 400, "height": 300}
        assert result["overlay_url"] == result["normalized_source_url"]
        overlay = client.get(result["overlay_url"])
        assert overlay.status_code == 200
        with Image.open(io.BytesIO(overlay.content)) as image:
            assert image.size == (400, 300)
