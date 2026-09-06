from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scene3d.worker import INPUT_ERROR, RENDER_ERROR

FIXTURE = Path(__file__).resolve().parents[2] / "spatial_core/tests/fixtures/confirmed-orthogonal-merge.json"


def run_worker(output: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": f"packages/spatial_core:packages/scene3d:{os.environ.get('PYTHONPATH', '')}"}
    return subprocess.run(
        [sys.executable, "-m", "scene3d.worker", "--output", str(output), *args],
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_worker_reads_stdin_and_prints_manifest(tmp_path):
    result = run_worker(tmp_path / "stdin-render", "--width", "120", "--height", "90", input_text=FIXTURE.read_text())
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["camera"]["width"] == 120
    assert (tmp_path / "stdin-render" / "manifest.json").is_file()
    assert set(manifest["files"]) == {"color", "depth", "normal", "instance_mask"}


def test_worker_reads_input_file(tmp_path):
    output = tmp_path / "file-render"
    result = run_worker(output, "--input", str(FIXTURE))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["model_id"] == "fixture-living-merge-001"


def test_worker_input_and_render_failures_have_stable_codes(tmp_path):
    malformed = run_worker(tmp_path / "bad-json", input_text="{bad")
    assert malformed.returncode == INPUT_ERROR
    assert not (tmp_path / "bad-json" / "manifest.json").exists()
    model = json.loads(FIXTURE.read_text())
    model["status"] = "draft"
    rejected = run_worker(tmp_path / "draft", input_text=json.dumps(model))
    assert rejected.returncode == RENDER_ERROR
    assert not (tmp_path / "draft" / "manifest.json").exists()


def test_worker_rejects_nonfinite_json(tmp_path):
    model = FIXTURE.read_text().replace('"confidence": 1.0', '"confidence": NaN')
    result = run_worker(tmp_path / "nan", input_text=model)
    assert result.returncode == INPUT_ERROR
    assert "non-finite" in result.stderr
