"""Process-isolated CPU rendering orchestration for the local workbench."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .revisions import InvalidModel


class RenderUnavailable(RuntimeError):
    """The render worker failed or exceeded its bounded execution time."""


def _safe_component(value: str) -> str:
    if not value or value in {".", ".."} or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in value):
        raise InvalidModel("model_id contains unsupported path characters")
    return value


def render_revision(model: dict[str, Any], root: str | Path, *, width: int, height: int) -> dict[str, Any]:
    if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 2048:
        raise InvalidModel("width must be an integer between 1 and 2048")
    if isinstance(height, bool) or not isinstance(height, int) or not 1 <= height <= 2048:
        raise InvalidModel("height must be an integer between 1 and 2048")
    model_id = _safe_component(str(model["model_id"]))
    root_path = Path(root)
    model_hash = _model_hash(model)
    output = root_path / model_id / f"r{model['revision']}-{model_hash[:16]}"
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("model_hash") == model_hash and manifest.get("camera", {}).get("width") == width and manifest.get("camera", {}).get("height") == height:
                return manifest
        except (OSError, ValueError):
            pass

    root_path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-input-", dir=root_path) as temp_dir:
        input_path = Path(temp_dir) / "model.json"
        input_path.write_text(json.dumps(model, ensure_ascii=False, allow_nan=False))
        command = [
            sys.executable,
            "-m",
            "scene3d.worker",
            "--input",
            str(input_path),
            "--output",
            str(output),
            "--width",
            str(width),
            "--height",
            str(height),
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        source_paths = [str(Path(__file__).resolve().parents[2] / "packages/scene3d"), str(Path(__file__).resolve().parents[2] / "packages/spatial_core")]
        env["PYTHONPATH"] = os.pathsep.join(source_paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RenderUnavailable("render worker timed out after 120 seconds") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "render worker failed").strip()[-2000:]
        raise RenderUnavailable(detail)
    try:
        return json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise RenderUnavailable("render worker completed without a valid manifest") from exc


def _model_hash(model: dict[str, Any]) -> str:
    from spatial_core import canonical_hash

    return canonical_hash(model)
