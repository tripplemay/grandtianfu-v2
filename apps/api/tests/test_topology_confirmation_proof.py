from __future__ import annotations

import copy
from pathlib import Path

import pytest

from apps.api.revisions import InvalidModel, StorageIntegrityError
from apps.api.tests.test_ingest_topology import _topology_body, _trace
from apps.api.topology_confirmation import topology_confirmation_evidence, verify_topology_reference


def test_verify_replays_topology_and_rejects_parent_hash_tampering(tmp_path: Path):
    from fastapi.testclient import TestClient

    from apps.api.app import create_app

    root = tmp_path / "ingests"
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=root)) as client:
        trace = _trace(client)
        response = client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=_topology_body(trace))
        assert response.status_code == 201
        result = response.json()
        assert verify_topology_reference(result, root) == result["model"]

        tampered = copy.deepcopy(result)
        tampered["model"]["ingest"]["topology"]["parent_model_hash"] = "0" * 64
        with pytest.raises(StorageIntegrityError):
            verify_topology_reference(tampered, root)


def test_verify_replay_mismatch_is_storage_error(tmp_path: Path):
    from fastapi.testclient import TestClient

    from apps.api.app import create_app

    root = tmp_path / "ingests"
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=root)) as client:
        trace = _trace(client)
        result = client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=_topology_body(trace)).json()
        tampered = copy.deepcopy(result)
        tampered["model"]["ingest"]["topology"]["openings"][0]["width"] += 1
        with pytest.raises(StorageIntegrityError):
            verify_topology_reference(tampered, root)


def test_confirmation_rejects_unclassified_room_and_extra_blocker(tmp_path: Path):
    from fastapi.testclient import TestClient

    from apps.api.app import create_app
    from apps.api.tests.test_ingest_review import save

    root = tmp_path / "ingests"
    with TestClient(create_app(tmp_path / "db.sqlite", seed_path=None, ingest_root=root)) as client:
        trace = _trace(client)
        result = client.post(f"/api/ingests/{trace['ingest_id']}/topology", json=_topology_body(trace)).json()
        reference = verify_topology_reference(result, root)
        current = copy.deepcopy(reference)
        current["rooms"][0]["kind"] = "unknown"
        with pytest.raises(InvalidModel):
            topology_confirmation_evidence(current, reference)

        edited = copy.deepcopy(result["envelope"])
        edited["model"]["ingest"]["hard_blockers"].append({"code": "other_blocker"})
        saved = save(client, edited)
        assert saved.status_code == 422
