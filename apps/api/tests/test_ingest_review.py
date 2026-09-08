from __future__ import annotations

import copy
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from apps.api.app import create_app


def plan_bytes(fmt="PNG"):
    image = Image.new("RGB", (400, 320), "white")
    ImageDraw.Draw(image).rectangle((40, 40, 360, 280), outline="black", width=9)
    stream = io.BytesIO()
    image.save(stream, format=fmt)
    return stream.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GT_RENDER_ROOT", str(tmp_path / "renders"))
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        yield client


def upload(client, scale=10, payload=None, fmt="PNG"):
    response = client.post(f"/api/ingests?mm_per_pixel={scale}", content=payload or plan_bytes(fmt),
                           headers={"Content-Type": "image/png" if fmt == "PNG" else "image/jpeg", "X-Filename": "plan.png"})
    assert response.status_code == 201, response.text
    return response.json()


def save(client, envelope, action="save"):
    return client.post(f"/api/models/{envelope['model']['model_id']}/revisions", json={
        "model": envelope["model"], "expected_hash": envelope["hash"],
        "expected_revision": envelope["model"]["revision"], "action": action, "note": "test edit",
    })


def review_body(envelope):
    return {"expected_revision": envelope["model"]["revision"], "expected_hash": envelope["hash"],
            "reviewed_object_ids": [item["id"] for key in ("rooms", "walls", "openings") for item in envelope["model"][key]],
            "checks": {"scale": True, "geometry": True, "openings": True, "heights": True}, "reviewer": "local-tester"}


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_real_bitmap_enters_workbench_with_source_evidence(client, fmt):
    result = upload(client, fmt=fmt)
    model = result["model"]
    assert model["status"] == "draft"
    assert model["rooms"][0]["rect"][0] > 200  # It is not the image bounds.
    assert model["source"]["sha256"] == hashlib.sha256(plan_bytes(fmt)).hexdigest()
    assert client.get(result["source_url"]).content == plan_bytes(fmt)
    assert client.get(result["preprocessed_url"]).content.startswith(b"\x89PNG")
    assert client.get("/api/models").json()[0]["model_id"] == model["model_id"]


def test_calibration_is_required_and_part_of_identity(client):
    assert client.post("/api/ingests", content=plan_bytes(), headers={"Content-Type": "image/png"}).status_code == 422
    one, two = upload(client, 10), upload(client, 20)
    assert one["ingest_id"] != two["ingest_id"]
    assert one["model"]["source"]["sha256"] == two["model"]["source"]["sha256"]
    assert two["model"]["rooms"][0]["rect"][2] == pytest.approx(one["model"]["rooms"][0]["rect"][2] * 2)


def test_display_filename_does_not_become_a_worker_option_or_job_identity(client):
    response = client.post("/api/ingests?mm_per_pixel=10", content=plan_bytes(),
                           headers={"Content-Type": "image/png", "X-Filename": "--example.png"})
    assert response.status_code == 201, response.text
    assert upload(client)["envelope"] == response.json()["envelope"]


def test_review_cas_and_confirmed_to_3d(client):
    result = upload(client)
    initial = result["envelope"]
    base = f"/api/models/{initial['model']['model_id']}"
    assert client.post(base + "/renders", json={"revision": 1, "width": 64, "height": 48}).status_code == 422
    edited = copy.deepcopy(initial)
    edited["model"]["cameras"] = [{"id": "review-camera", "projection": "perspective", "image_size": {"width": 64, "height": 48},
        "position": {"x": 2000, "y": 1000, "z": 1500}, "look_at": {"x": 2000, "y": 2500, "z": 500}, "up": {"x": 0, "y": 0, "z": 1}}]
    saved = save(client, edited).json()
    assert saved["model"]["revision"] == 2
    assert save(client, saved, "confirm").status_code == 422
    endpoint = f"/api/ingests/{result['ingest_id']}/confirm"
    assert client.post(endpoint, json=review_body(initial)).status_code == 409
    body = review_body(saved)
    body["checks"]["scale"] = False
    assert client.post(endpoint, json=body).status_code == 422
    confirmed = client.post(endpoint, json=review_body(saved))
    assert confirmed.status_code == 201, confirmed.text
    confirmed = confirmed.json()
    assert confirmed["model"]["review"]["draft_hash"] == saved["hash"]
    assert confirmed["model"]["status"] == "confirmed"
    for key in ("rooms", "walls", "openings"):
        assert all(item["needs_review"] is False for item in confirmed["model"][key])
        assert all(item["confidence"] < 0.9 for item in confirmed["model"][key])
    assert confirmed["model"]["walls"][0]["height_provenance"]["needs_review"] is False
    assert initial["model"]["walls"][0]["needs_review"] is True
    assert client.get(base + "/revisions/1").json() == initial
    rendered = client.post(base + "/renders", json={"revision": 3, "width": 64, "height": 48})
    assert rendered.status_code == 200, rendered.text
    assert rendered.json()["model_hash"] == confirmed["hash"]
    assert rendered.json()["source"]["sha256"] == result["model"]["source"]["sha256"]
    assert rendered.json()["review"]["draft_hash"] == saved["hash"]
    assert upload(client)["envelope"] == confirmed
    new_draft = save(client, confirmed).json()
    assert new_draft["model"]["status"] == "draft"
    assert "review" not in new_draft["model"]
    assert all(item["needs_review"] for key in ("rooms", "walls", "openings") for item in new_draft["model"][key])


@pytest.mark.parametrize("mutation", ["source", "scale", "objects", "checks", "forged_review"])
def test_review_cannot_be_bypassed(client, mutation):
    result = upload(client)
    envelope = result["envelope"]
    body = review_body(envelope)
    if mutation in {"source", "scale", "forged_review"}:
        if mutation == "source":
            envelope["model"]["source"]["kind"] = "manual"
        elif mutation == "scale":
            envelope["model"]["ingest"]["mm_per_pixel"] = 1
        else:
            envelope["model"]["review"] = {"checks": body["checks"]}
        response = save(client, envelope, "confirm")
    else:
        if mutation == "objects":
            body["reviewed_object_ids"].pop()
        else:
            body["checks"]["geometry"] = 1
        response = client.post(f"/api/ingests/{result['ingest_id']}/confirm", json=body)
    assert response.status_code == 422
    assert len(client.get(f"/api/models/{envelope['model']['model_id']}/revisions").json()) == 1


def test_corrupt_artifact_is_not_returned_as_success(client, tmp_path):
    result = upload(client)
    directory = tmp_path / "ingests" / result["ingest_id"]
    (directory / "preprocessed.png").write_bytes(b"corrupt")
    response = client.get(f"/api/ingests/{result['ingest_id']}")
    assert response.status_code == 500
    assert response.json()["code"] == "storage_integrity_error"
    assert (directory / result["manifest"]["files"]["source"]).read_bytes() == plan_bytes()


@pytest.mark.parametrize("bad_manifest", [[], {"files": ["source", "preprocessed", "draft_model", "preprocessing"], "artifact_hashes": {}}])
def test_malformed_manifest_has_structured_integrity_error(client, tmp_path, bad_manifest):
    result = upload(client)
    directory = tmp_path / "ingests" / result["ingest_id"]
    (directory / "ingest-manifest.json").write_text(json.dumps(bad_manifest))
    response = client.get(f"/api/ingests/{result['ingest_id']}")
    assert response.status_code == 500
    assert response.json()["code"] == "storage_integrity_error"


@pytest.mark.parametrize("scale", ["nan", "inf", "-1", "0"])
def test_invalid_scale_never_publishes(client, scale):
    response = client.post(f"/api/ingests?mm_per_pixel={scale}", content=plan_bytes(), headers={"Content-Type": "image/png"})
    assert response.status_code == 422
    assert client.get("/api/models").json() == []
