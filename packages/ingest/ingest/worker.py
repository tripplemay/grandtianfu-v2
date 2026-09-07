"""Isolated CPU ingest worker with immutable, atomically published artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from spatial_core import canonical_hash

from .bitmap import (
    MAX_FILE_BYTES,
    BitmapAsset,
    BitmapError,
    canonical_json,
    ingest_bitmap,
    load_bitmap,
)

INPUT_ERROR = 2
INGEST_ERROR = 3
OUTPUT_ERROR = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recognize a reviewable orthogonal PNG/JPEG draft")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--filename", default="upload")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--mm-per-pixel", type=float, required=True)
    return parser


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (canonical_json(document) + "\n").encode("utf-8")


def _write_outputs(output: Path, model: dict[str, Any], asset: BitmapAsset, filename: str = "upload") -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    backup: Path | None = None
    try:
        files = {"source": "source.png" if asset.media_type == "image/png" else "source.jpg",
                 "preprocessed": "preprocessed.png", "draft_model": "draft-model.json",
                 "preprocessing": "preprocess-manifest.json"}
        preprocessing = {"schema_version": "ingest-preprocess-0.2", "source_sha256": asset.sha256,
                         **model["ingest"]["preprocessing"]}
        payloads = {"source": asset.data, "preprocessed": asset.normalized_png,
                    "draft_model": _json_bytes(model), "preprocessing": _json_bytes(preprocessing)}
        hashes = {key: hashlib.sha256(payload).hexdigest() for key, payload in payloads.items()}
        for key, payload in payloads.items():
            (temporary / files[key]).write_bytes(payload)
        manifest = {"schema_version": "ingest-0.2", "status": "draft", "source_sha256": asset.sha256,
                    "ingest_id": model["ingest"]["ingest_id"], "model_id": model["model_id"],
                    "revision": model["revision"], "model_hash": canonical_hash(model),
                    "filename": filename, **model["ingest"], "files": files, "artifact_hashes": hashes}
        (temporary / "ingest-manifest.json").write_bytes(_json_bytes(manifest))
        for key, artifact_name in files.items():
            if hashlib.sha256((temporary / artifact_name).read_bytes()).hexdigest() != hashes[key]:
                raise OSError(f"artifact verification failed: {key}")
        if output.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.previous.", dir=output.parent))
            backup.rmdir()
            os.replace(output, backup)
        try:
            os.replace(temporary, output)
        except OSError:
            if backup is not None:
                os.replace(backup, output)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.input.stat().st_size > MAX_FILE_BYTES:
            raise BitmapError("input_too_large: maximum file size is 20 MiB")
        data = args.input.read_bytes()
    except BitmapError as exc:
        print(f"worker ingest error: {exc}", file=sys.stderr)
        return INGEST_ERROR
    except OSError as exc:
        print(f"worker input error: {exc}", file=sys.stderr)
        return INPUT_ERROR
    try:
        model = ingest_bitmap(data, filename=args.filename, model_id=args.model_id,
                              revision=args.revision, mm_per_pixel=args.mm_per_pixel)
        asset = load_bitmap(data)
    except BitmapError as exc:
        print(f"worker ingest error: {exc}", file=sys.stderr)
        return INGEST_ERROR
    try:
        manifest = _write_outputs(args.output, model, asset, args.filename)
    except OSError as exc:
        print(f"worker output error: {exc}", file=sys.stderr)
        return OUTPUT_ERROR
    print(json.dumps({key: manifest[key] for key in ("model_id", "revision", "status", "source_sha256", "ingest_id")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
