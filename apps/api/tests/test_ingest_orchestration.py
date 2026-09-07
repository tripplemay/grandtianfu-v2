import fcntl
import hashlib
import io
import subprocess
from unittest.mock import patch

import pytest
from ingest import BitmapError
from ingest.bitmap import ingest_key
from PIL import Image

from apps.api.ingest import IngestUnavailable, ingest_bitmap_worker
from apps.api.revisions import strict_json


def blank_png():
    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_no_room_retains_failure_evidence_without_publishing(tmp_path):
    data = blank_png()
    key = ingest_key(data, 10)
    with pytest.raises(BitmapError, match="no_closed_rectangle"):
        ingest_bitmap_worker(data, "blank.png", tmp_path, mm_per_pixel=10)
    assert not (tmp_path / key).exists()
    failed = tmp_path / "rejected" / key
    assert (failed / "source.bin").read_bytes() == data
    assert strict_json((failed / "failure.json").read_bytes())["source_sha256"] == hashlib.sha256(data).hexdigest()


def test_busy_worker_rejects_without_starting_another_process(tmp_path):
    data = blank_png()
    ingest_key(data, 10)  # Resolve OCR runtime before counting worker spawns.
    with (tmp_path / ".worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch("apps.api.ingest.subprocess.run") as run, pytest.raises(IngestUnavailable, match="busy"):
            ingest_bitmap_worker(data, "blank.png", tmp_path, mm_per_pixel=10)
        run.assert_not_called()


@pytest.mark.parametrize("failure", ["timeout", "start", "crash"])
def test_worker_failure_is_explicit_and_retained(tmp_path, failure):
    data = blank_png()
    key = ingest_key(data, 10)
    kwargs = {"side_effect": subprocess.TimeoutExpired("worker", 120)} if failure == "timeout" else (
        {"side_effect": OSError("cannot spawn")} if failure == "start" else
        {"return_value": subprocess.CompletedProcess("worker", 4, "", "worker failed")})
    with patch("apps.api.ingest.subprocess.run", **kwargs), pytest.raises(IngestUnavailable):
        ingest_bitmap_worker(data, "blank.png", tmp_path, mm_per_pixel=10)
    assert not (tmp_path / key).exists()
    assert (tmp_path / "rejected" / key / "source.bin").read_bytes() == data
    assert not list(tmp_path.glob(".ingest-*"))
