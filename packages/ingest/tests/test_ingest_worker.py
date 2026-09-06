import json
import os
import subprocess
import sys
from pathlib import Path

from test_bitmap import minimal_jpeg


def run_worker(source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": "packages/spatial_core:packages/ingest"}
    return subprocess.run(
        [sys.executable, "-m", "ingest.worker", "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_worker_publishes_draft_artifacts_atomically(tmp_path):
    source = tmp_path / "plan.jpg"
    source.write_bytes(minimal_jpeg())
    output = tmp_path / "ingest"
    result = run_worker(source, output)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "draft"
    assert {path.name for path in output.iterdir()} == {"draft-model.json", "preprocess-manifest.json", "ingest-manifest.json"}
    model = json.loads((output / "draft-model.json").read_text())
    assert model["status"] == "draft"
    assert model["ingest"]["requires_human_review"] is True


def test_worker_rejects_unsupported_input_without_output(tmp_path):
    source = tmp_path / "plan.pdf"
    source.write_bytes(b"%PDF-1.7")
    output = tmp_path / "ingest"
    result = run_worker(source, output)
    assert result.returncode == 3
    assert not output.exists()
