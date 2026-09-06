from __future__ import annotations

import copy
import json
import sqlite3
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from spatial_core import canonical_hash

from apps.api.app import DEFAULT_SEED, create_app
from apps.api.revisions import RevisionConflict, RevisionStore


@pytest.fixture
def model():
    return json.loads(DEFAULT_SEED.read_text())


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "workbench.sqlite3")) as value:
        yield value


def endpoint(model):
    return f"/api/models/{model['model_id']}"


def latest(client, model):
    response = client.get(endpoint(model) + "/latest")
    assert response.status_code == 200
    return response.json()


def save_body(current, model=None, action="save"):
    return {
        "model": copy.deepcopy(model if model is not None else current["model"]),
        "expected_revision": current["model"]["revision"],
        "expected_hash": current["hash"],
        "note": "Workbench test",
        "action": action,
    }


def tiny_png() -> bytes:
    pixels = bytes([255, 255, 255, 0, 0, 0, 255, 255, 255, 255, 255, 255])
    raw = b"\x00" + pixels[:6] + b"\x00" + pixels[6:]
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_startup_is_explicit_and_seed_is_idempotent(tmp_path, model):
    path = tmp_path / "workbench.sqlite3"
    app = create_app(path)
    assert not path.exists()
    with TestClient(app) as client:
        initial = latest(client, model)
        body = save_body(initial)
        body["model"]["furniture_instances"][0]["transform"]["x"] += 37.125
        saved = client.post(endpoint(model) + "/revisions", json=body)
        assert saved.status_code == 201
        saved = saved.json()
    with TestClient(create_app(path)) as restarted:
        assert latest(restarted, model) == saved
        assert restarted.get(endpoint(model) + "/revisions/1").json() == initial
        assert len(restarted.get(endpoint(model) + "/revisions").json()) == 2
    assert saved["hash"] == canonical_hash(saved["model"])


def test_seed_does_not_overwrite_existing_model(tmp_path, model):
    path = tmp_path / "workbench.sqlite3"
    with TestClient(create_app(path)) as client:
        initial = latest(client, model)
    modified = copy.deepcopy(model)
    modified["furniture_instances"][0]["transform"]["x"] += 25
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(modified))
    with TestClient(create_app(path, seed_path=seed)) as client:
        assert latest(client, model) == initial


def test_seed_can_be_disabled(tmp_path):
    with TestClient(create_app(tmp_path / "empty.sqlite3", seed_path=None)) as client:
        assert client.get("/api/models").json() == []


def test_model_and_revision_lists(client, model):
    current = latest(client, model)
    assert client.get("/api/models").json() == [{
        "model_id": model["model_id"],
        "title": model.get("title", model["model_id"]),
        "latest_revision": 1,
        "status": "confirmed",
        "hash": current["hash"],
    }]
    assert client.get(endpoint(model) + "/revisions/latest").json() == current
    assert client.get(endpoint(model) + "/revisions").json() == [{
        "revision": 1, "status": "confirmed", "hash": current["hash"],
        "note": current["note"], "created_at": current["created_at"],
    }]
    assert client.get(endpoint(model) + "/revisions/900").status_code == 404
    assert client.get("/api/models/missing/latest").status_code == 404
    assert client.get("/api/models/missing/revisions").status_code == 404


def test_validate_never_writes(client, model):
    initial = latest(client, model)
    assert client.post(endpoint(model) + "/validate", json={"model": model}).json() == {"ok": True, "errors": []}
    invalid = copy.deepcopy(model)
    invalid["furniture_instances"][0]["dimensions"]["width"] = -100
    response = client.post(endpoint(model) + "/validate", json={"model": invalid})
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["errors"][0]["message"]
    assert latest(client, model) == initial
    assert len(client.get(endpoint(model) + "/revisions").json()) == 1


def test_save_then_confirm_are_distinct_immutable_revisions(client, model):
    initial = latest(client, model)
    body = save_body(initial)
    body["model"]["furniture_instances"][0]["transform"]["x"] += 5.125
    draft = client.post(endpoint(model) + "/revisions", json=body)
    assert draft.status_code == 201
    draft = draft.json()
    assert draft["model"]["revision"] == 2
    assert draft["model"]["status"] == "draft"
    confirmed = client.post(endpoint(model) + "/revisions", json=save_body(draft, action="confirm"))
    assert confirmed.status_code == 201
    confirmed = confirmed.json()
    assert confirmed["model"]["revision"] == 3
    assert confirmed["model"]["status"] == "confirmed"
    assert confirmed["model"]["furniture_instances"] == draft["model"]["furniture_instances"]
    assert client.get(endpoint(model) + "/revisions/1").json() == initial
    assert client.get(endpoint(model) + "/revisions/2").json() == draft


def test_stale_revision_and_hash_cannot_overwrite(client, model):
    initial = latest(client, model)
    body = save_body(initial)
    saved = client.post(endpoint(model) + "/revisions", json=body).json()
    conflict = client.post(endpoint(model) + "/revisions", json=body)
    assert conflict.status_code == 409
    assert conflict.json()["current_revision"] == 2
    assert conflict.json()["current_hash"] == saved["hash"]
    wrong_hash = save_body(saved)
    wrong_hash["expected_hash"] = "0" * 64
    assert client.post(endpoint(model) + "/revisions", json=wrong_hash).status_code == 409
    assert latest(client, model) == saved


def test_restore_old_content_appends_new_revision(client, model):
    initial = latest(client, model)
    body = save_body(initial)
    body["model"]["furniture_instances"][0]["transform"]["x"] += 13.75
    saved = client.post(endpoint(model) + "/revisions", json=body).json()
    restore = save_body(saved, initial["model"])
    restore["note"] = "Restore revision 1"
    restored = client.post(endpoint(model) + "/revisions", json=restore)
    assert restored.status_code == 201
    restored = restored.json()
    assert restored["model"] == {**initial["model"], "revision": 3, "status": "draft"}
    assert restored["hash"] == canonical_hash(restored["model"])
    assert restored["hash"] != initial["hash"]
    assert client.get(endpoint(model) + "/revisions/1").json() == initial
    assert client.get(endpoint(model) + "/revisions/2").json() == saved


@pytest.mark.parametrize("field,value", [
    ("status", []), ("status", {}), ("rooms", {}), ("rooms", []), ("walls", [None]), ("walls", []),
    ("revision", 999), ("revision", 10**100), ("model_id", "different-model"), ("content_hash", "forged"),
])
def test_invalid_model_fields_never_write_or_500(client, model, field, value):
    initial = latest(client, model)
    body = save_body(initial)
    body["model"][field] = value
    response = client.post(endpoint(model) + "/revisions", json=body)
    assert response.status_code == 422
    assert response.json()["errors"][0]["message"]
    assert latest(client, model) == initial


@pytest.mark.parametrize("collection,field", [("walls", "axis"), ("furniture_instances", "attachment")])
def test_malformed_nested_enums_are_client_errors(client, model, collection, field):
    current = latest(client, model)
    body = save_body(current)
    body["model"][collection][0][field] = {"malformed": True}
    assert client.post(endpoint(model) + "/revisions", json=body).status_code == 422
    validated = client.post(endpoint(model) + "/validate", json={"model": body["model"]})
    assert validated.status_code == 200
    assert validated.json()["ok"] is False


@pytest.mark.parametrize("field,value", [
    ("expected_revision", True), ("expected_revision", "1"),
    ("expected_hash", {}), ("note", []), ("action", {}), ("action", "locked"), ("model", []),
])
def test_invalid_request_types(client, model, field, value):
    current = latest(client, model)
    body = save_body(current)
    body[field] = value
    assert client.post(endpoint(model) + "/revisions", json=body).status_code == 422
    assert latest(client, model) == current


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_rejected_everywhere(client, model, token):
    current = latest(client, model)
    body = save_body(current)
    raw = json.dumps(body).replace('"confidence": 1.0', f'"confidence": {token}')
    response = client.post(endpoint(model) + "/revisions", content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert latest(client, model) == current


@pytest.mark.parametrize("raw", ['{"model":{},"model":{}}', '{', '[1,2]', 'null', '{"model":"\\ud800"}'])
def test_malformed_json_and_duplicate_keys(client, model, raw):
    assert client.post(endpoint(model) + "/validate", content=raw, headers={"content-type": "application/json"}).status_code == 422


def test_body_type_and_size_limits(client, model):
    assert client.post(endpoint(model) + "/validate", content="{}").status_code == 422
    response = client.post(endpoint(model) + "/validate", content=b" " * (2 * 1024 * 1024 + 1), headers={"content-type": "application/json"})
    assert response.status_code == 422


def test_render_confirmed_revision_publishes_raw_artifacts(client, model, tmp_path, monkeypatch):
    monkeypatch.setenv("GT_RENDER_ROOT", str(tmp_path / "renders"))
    response = client.post(endpoint(model) + "/renders", json={"revision": 1, "width": 320, "height": 240})
    assert response.status_code == 200, response.text
    manifest = response.json()
    assert manifest["camera"]["projection"] == "cpu-perspective-v1"
    assert manifest["camera"]["width"] == 320
    assert manifest["camera"]["height"] == 240
    assert manifest["artifact_url"].startswith("/render-artifacts/")
    for filename in manifest["files"].values():
        assert (tmp_path / "renders" / model["model_id"] / f"r1-{manifest['model_hash'][:16]}" / filename).is_file()
    color_path = tmp_path / "renders" / model["model_id"] / f"r1-{manifest['model_hash'][:16]}" / manifest["files"]["color"]
    color_path.write_bytes(b"tampered")
    repaired = client.post(endpoint(model) + "/renders", json={"revision": 1, "width": 320, "height": 240}).json()
    assert color_path.read_bytes() != b"tampered"
    assert repaired["artifact_hashes"]["color"] == manifest["artifact_hashes"]["color"]


def test_render_rejects_draft_and_invalid_dimensions(client, model):
    current = latest(client, model)
    body = save_body(current)
    draft = client.post(endpoint(model) + "/revisions", json=body).json()
    assert client.post(endpoint(model) + "/renders", json={"revision": draft["model"]["revision"], "width": 320, "height": 240}).status_code == 422
    assert client.post(endpoint(model) + "/renders", json={"revision": 1, "width": 0, "height": 240}).status_code == 422


def test_bitmap_ingest_returns_immutable_draft_and_is_idempotent(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GT_INGEST_ROOT", str(tmp_path / "ingests"))
    payload = tiny_png()
    response = client.post("/api/ingests", content=payload, headers={"content-type": "image/png", "x-filename": "plan.png"})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["requires_human_review"] is True
    assert result["model"]["status"] == "draft"
    assert result["model"]["source"]["kind"] == "bitmap"
    assert result["model"]["source"]["sha256"] == result["ingest_id"]
    assert client.get(f"/api/ingests/{result['ingest_id']}").json()["model"] == result["model"]
    again = client.post("/api/ingests", content=payload, headers={"content-type": "image/png", "x-filename": "plan.png"})
    assert again.status_code == 201
    assert again.json()["ingest_id"] == result["ingest_id"]


def test_bitmap_ingest_rejects_mismatched_or_unsupported_input(client):
    assert client.post("/api/ingests", content=b"not-an-image", headers={"content-type": "image/png"}).status_code == 422
    assert client.post("/api/ingests", content=b"%PDF-1.7", headers={"content-type": "application/pdf"}).status_code == 422


def test_global_numeric_bounds_apply_to_all_model_values(client, model):
    current = latest(client, model)
    for number in (1_000_000_001, -1_000_000_001, 1e308, -1e308):
        candidate = copy.deepcopy(model)
        candidate["furniture_instances"][0]["transform"]["z"] = number
        response = client.post(endpoint(model) + "/validate", json={"model": candidate})
        assert response.status_code in (200, 422)
        if response.status_code == 200:
            assert response.json()["ok"] is False
            assert response.json()["errors"][0]["message"]
        else:
            assert response.json()["errors"][0]["message"]
    edge = copy.deepcopy(model)
    edge["walls"].append({
        "id": "boundary-wall", "axis": "h", "x": 1_000_000_000,
        "y": -1_000_000_000, "length": 1_000_000_000,
        "thickness": 1, "bottom_z": 0, "top_z": 2700,
    })
    assert client.post(endpoint(model) + "/validate", json={"model": edge}).json() == {"ok": True, "errors": []}
    assert latest(client, model) == current


def test_concurrent_writers_only_one_wins(tmp_path, model):
    store = RevisionStore(tmp_path / "workbench.sqlite3")
    store.initialize(DEFAULT_SEED)
    current = store.get(model["model_id"])
    barrier = Barrier(2)

    def write(offset):
        edited = copy.deepcopy(model)
        edited["furniture_instances"][0]["transform"]["x"] += offset
        barrier.wait(timeout=5)
        try:
            return store.append(model["model_id"], edited, 1, current["hash"], "Concurrent edit", "save")
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [1.125, 2.625]))
    assert results.count("conflict") == 1
    winner = next(result for result in results if isinstance(result, dict))
    assert store.get(model["model_id"]) == winner
    assert len(store.list_revisions(model["model_id"])) == 2
    assert store.get(model["model_id"], 1) == current


def test_sql_revisions_are_immutable_and_hashes_verified_on_read(tmp_path, model):
    path = tmp_path / "workbench.sqlite3"
    with TestClient(create_app(path)) as client:
        current = latest(client, model)
        with sqlite3.connect(path) as db:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute("UPDATE revisions SET note = 'changed'")
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute("DELETE FROM revisions")
            db.execute("DROP TRIGGER revisions_no_update")
            tampered = copy.deepcopy(current["model"])
            tampered["confidence"] = 0.5
            db.execute("UPDATE revisions SET payload = ?", (json.dumps(tampered),))
        for url in [endpoint(model) + "/latest", endpoint(model) + "/revisions/1", endpoint(model) + "/revisions", "/api/models"]:
            response = client.get(url)
            assert response.status_code == 500
            assert response.json()["code"] == "storage_integrity_error"


def test_static_frontend_and_traversal(tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<title>Workbench</title>")
    (assets / "app.js").write_text("export const ready = true;")
    (tmp_path / "secret.txt").write_text("not public")
    (assets / "leak.txt").symlink_to(tmp_path / "secret.txt")
    with TestClient(create_app(tmp_path / "db.sqlite3", seed_path=None, static_dir=dist)) as client:
        assert client.get("/").status_code == 200
        assert "Workbench" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/%2e%2e/%2e%2e/secret.txt").status_code == 404
        assert client.get("/assets/leak.txt").status_code == 404
        assert client.get("/secret.txt").status_code == 404


def test_unbuilt_frontend_is_explicit(tmp_path):
    with TestClient(create_app(tmp_path / "db.sqlite3", seed_path=None, static_dir=tmp_path / "missing")) as client:
        assert client.get("/").status_code == 503
