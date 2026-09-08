import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ingest import ingest_bitmap, load_bitmap
from ingest.worker import _write_outputs
from spatial_core import canonical_hash
from test_bitmap import plan_png


def run_worker(source: Path, output: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ingest.worker", "--input", str(source), "--output", str(output), *args],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": "packages/spatial_core:packages/ingest"},
        timeout=30, check=False,
    )


def test_worker_publishes_complete_hashed_artifacts_and_repeats_deterministically(tmp_path):
    source = tmp_path / "plan.png"
    source.write_bytes(plan_png(door=True))
    manifests = []
    for iteration in range(3):
        output = tmp_path / f"ingest-{iteration}"
        result = run_worker(source, output, "--mm-per-pixel", "10", "--filename", "plan.png")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == "draft"
        assert {path.name for path in output.iterdir()} == {
            "source.png", "preprocessed.png", "draft-model.json", "preprocess-manifest.json", "ingest-manifest.json"}
        manifest = json.loads((output / "ingest-manifest.json").read_text())
        for key, filename in manifest["files"].items():
            assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == manifest["artifact_hashes"][key]
        model = json.loads((output / "draft-model.json").read_text())
        assert canonical_hash(model) == manifest["model_hash"]
        assert model["status"] == "draft"
        assert model["ingest"]["requires_human_review"]
        assert (output / "source.png").read_bytes() == source.read_bytes()
        manifests.append(manifest)
    assert manifests[0] == manifests[1] == manifests[2]


def test_worker_requires_scale_and_rejects_corruption_without_output(tmp_path):
    source = tmp_path / "plan.pdf"
    source.write_bytes(b"%PDF-1.7")
    output = tmp_path / "ingest"
    assert run_worker(source, output).returncode == 2
    assert run_worker(source, output, "--mm-per-pixel", "10").returncode == 3
    assert not output.exists()


def test_failed_publish_restores_old_complete_output(tmp_path, monkeypatch):
    data = plan_png()
    model, asset = ingest_bitmap(data, mm_per_pixel=10), load_bitmap(data)
    output = tmp_path / "ingest"
    _write_outputs(output, model, asset)
    previous = {file.name: file.read_bytes() for file in output.iterdir()}
    real_replace = os.replace
    call_count = 0

    def fail_publish(source, target):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("injected publication failure")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_publish)
    with pytest.raises(OSError, match="injected"):
        _write_outputs(output, model, asset)
    assert {file.name: file.read_bytes() for file in output.iterdir()} == previous
    assert sorted(file.name for file in tmp_path.iterdir()) == ["ingest"]
