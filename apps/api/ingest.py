"""Process-isolated bitmap ingest orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ingest import BitmapError


class IngestUnavailable(RuntimeError):
    """The ingest worker could not produce a draft."""


def ingest_bitmap_worker(data: bytes, filename: str, root: str | Path) -> dict[str, Any]:
    if len(data) > 20 * 1024 * 1024:
        raise BitmapError("bitmap upload exceeds 20 MiB")
    source_hash = hashlib.sha256(data).hexdigest()
    root_path = Path(root)
    final = root_path / source_hash
    existing = final / "draft-model.json"
    if existing.is_file():
        return json.loads(existing.read_text())
    root_path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ingest-", dir=root_path) as temp_dir:
        temp = Path(temp_dir) / "input"
        temp.write_bytes(data)
        output = Path(temp_dir) / "output"
        env = os.environ.copy()
        paths = [str(Path(__file__).resolve().parents[2] / "packages/ingest"), str(Path(__file__).resolve().parents[2] / "packages/spatial_core")]
        env["PYTHONPATH"] = os.pathsep.join(paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            result = subprocess.run([sys.executable, "-m", "ingest.worker", "--input", str(temp), "--output", str(output)], capture_output=True, text=True, timeout=120, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise IngestUnavailable("ingest worker timed out after 120 seconds") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "ingest worker failed").strip()[-2000:]
            if result.returncode == 3:
                raise BitmapError(detail)
            raise IngestUnavailable(detail)
        draft = json.loads((output / "draft-model.json").read_text())
        if draft.get("source", {}).get("sha256") != source_hash:
            raise IngestUnavailable("ingest worker source hash mismatch")
        extension = ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
        (output / f"source{extension}").write_bytes(data)
        try:
            os.replace(output, final)
        except FileExistsError:
            return json.loads((final / "draft-model.json").read_text())
        return draft
