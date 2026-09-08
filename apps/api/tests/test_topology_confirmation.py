from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from apps.api.tests.test_ingest_review import review_body, save
from apps.api.tests.test_ingest_topology import _topology_body, _trace


@pytest.fixture
def topology_case(tmp_path, monkeypatch):
    monkeypatch.setenv("GT_RENDER_ROOT", str(tmp_path / "renders"))
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=tmp_path / "ingests")) as client:
        trace = _trace(client)
        result = client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=_topology_body(trace))
        assert result.status_code == 201, result.text
        yield client, trace, result.json()


def body_for(envelope):
    body = review_body(envelope)
    body["checks"].update({"topology": True, "coverage": True})
    body["reviewed_object_ids"] += sorted({room["merge_group_id"] for room in envelope["model"]["rooms"] if room.get("merge_group_id")})
    return body


def test_topology_confirm_preserves_evidence_and_renders(topology_case):
    client, trace, result = topology_case
    initial = result["envelope"]
    model_id = initial["model"]["model_id"]
    base = f"/api/models/{model_id}"
    endpoint = f"/api/ingests/{result['ingest_id']}/confirm"
    edited = copy.deepcopy(initial)
    edited["model"]["cameras"] = [{"id": "camera", "projection": "perspective", "image_size": {"width": 64, "height": 48},
        "position": {"x": 0, "y": -300, "z": 1200}, "look_at": {"x": 400, "y": 300, "z": 0}, "up": {"x": 0, "y": 0, "z": 1}}]
    saved = save(client, edited).json()
    assert client.post(base + "/renders", json={"revision": 2, "width": 64, "height": 48}).status_code == 422
    confirmed = client.post(endpoint, json=body_for(saved))
    assert confirmed.status_code == 201, confirmed.text
    confirmed = confirmed.json()
    assert confirmed["model"]["status"] == "confirmed"
    proof = confirmed["model"]["review"]["topology_confirmation"]
    assert proof["resolved_blocker_codes"] == ["manual_trace_requires_topology_review"]
    assert proof["scope"] == "traced_regions"
    assert confirmed["model"]["ingest"] == initial["model"]["ingest"]
    assert confirmed["model"]["source"] == initial["model"]["source"]
    assert client.get(base + "/revisions/1").json() == initial
    assert client.get(f"/api/ingests/{trace['ingest_id']}").json()["model"]["status"] == "draft"
    rendered = client.post(base + "/renders", json={"revision": 3, "width": 64, "height": 48})
    assert rendered.status_code == 200, rendered.text
    assert rendered.json()["model_hash"] == confirmed["hash"]
    assert client.post(endpoint, json=body_for(saved)).status_code == 409
    draft = save(client, confirmed).json()
    assert "review" not in draft["model"]
    assert draft["model"]["status"] == "draft"
    assert client.post(base + "/renders", json={"revision": 4, "width": 64, "height": 48}).status_code == 422
    assert client.post(endpoint, json=body_for(draft)).status_code == 201


@pytest.mark.parametrize("mutation", ["missing_check", "false_check", "bool_check", "missing_group", "extra_id", "duplicate_id", "stale_hash"])
def test_topology_confirm_rejects_incomplete_review(topology_case, mutation):
    client, _, result = topology_case
    body = body_for(result["envelope"])
    if mutation == "missing_check":
        del body["checks"]["coverage"]
    elif mutation == "false_check":
        body["checks"]["topology"] = False
    elif mutation == "bool_check":
        body["checks"]["coverage"] = 1
    elif mutation == "missing_group":
        body["reviewed_object_ids"].pop()
    elif mutation == "extra_id":
        body["reviewed_object_ids"].append("unrecognized")
    elif mutation == "duplicate_id":
        body["reviewed_object_ids"].append(body["reviewed_object_ids"][0])
    else:
        body["expected_hash"] = "0" * 64
    response = client.post(f"/api/ingests/{result['ingest_id']}/confirm", json=body)
    assert response.status_code == (409 if mutation == "stale_hash" else 422), response.text
    assert len(client.get(f"/api/models/{result['model']['model_id']}/revisions").json()) == 1


@pytest.mark.parametrize("mutation", ["geometry", "unclassified", "opening_kind", "forged_review", "blockers"])
def test_topology_current_model_cannot_reuse_stale_or_forged_proof(topology_case, mutation):
    client, _, result = topology_case
    current = copy.deepcopy(result["envelope"])
    if mutation == "geometry":
        current["model"]["openings"][0]["width"] -= 10
    elif mutation == "unclassified":
        current["model"]["rooms"][0]["kind"] = "unknown"
    elif mutation == "opening_kind":
        current["model"]["openings"][0]["kind"] = "other"
    elif mutation == "forged_review":
        current["model"]["review"] = {"topology_confirmation": {"resolved_blocker_codes": ["manual_trace_requires_topology_review"]}}
    else:
        current["model"]["ingest"]["hard_blockers"] = []
    saved = save(client, current)
    if mutation == "blockers":
        assert saved.status_code == 422
        return
    assert saved.status_code == 201, saved.text
    if mutation == "forged_review":
        assert "review" not in saved.json()["model"]
        return
    confirmed = client.post(f"/api/ingests/{result['ingest_id']}/confirm", json=body_for(saved.json()))
    assert confirmed.status_code == 422, confirmed.text
