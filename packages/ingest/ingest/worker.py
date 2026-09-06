"""Standalone CPU worker for deterministic bitmap ingest."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .bitmap import BitmapError, ingest_bitmap

INPUT_ERROR = 2
INGEST_ERROR = 3
OUTPUT_ERROR = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a draft SpatialModel from a PNG/JPEG bitmap")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--mm-per-pixel", type=float, default=10.0)
    return parser


def _write_outputs(output: Path, model: dict[str, Any]) -> None:
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=parent))
    try:
        (temporary / "draft-model.json").write_text(json.dumps(model, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (temporary / "preprocess-manifest.json").write_text(json.dumps({
            "schema_version": "ingest-preprocess-0.1",
            "source_sha256": model["source"]["sha256"],
            "preprocessing": model["ingest"]["preprocessing"],
            "pixel_size": model["ingest"]["pixel_size"],
        }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (temporary / "ingest-manifest.json").write_text(json.dumps({
            "schema_version": "ingest-0.1",
            "status": "draft",
            "source_sha256": model["source"]["sha256"],
            "model_id": model["model_id"],
            "revision": model["revision"],
            "requires_human_review": True,
            "files": {"draft_model": "draft-model.json", "preprocessing": "preprocess-manifest.json"},
        }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        backup = output.with_name(f".{output.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            os.replace(output, backup)
        os.replace(temporary, output)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        data = args.input.read_bytes()
    except (OSError, UnicodeError) as exc:
        print(f"worker input error: {exc}", file=sys.stderr)
        return INPUT_ERROR
    try:
        model = ingest_bitmap(data, filename=args.input.name, model_id=args.model_id, revision=args.revision, mm_per_pixel=args.mm_per_pixel)
    except BitmapError as exc:
        print(f"worker ingest error: {exc}", file=sys.stderr)
        return INGEST_ERROR
    try:
        _write_outputs(args.output, model)
    except OSError as exc:
        print(f"worker output error: {exc}", file=sys.stderr)
        return OUTPUT_ERROR
    print(json.dumps({"model_id": model["model_id"], "revision": model["revision"], "status": "draft", "source_sha256": model["source"]["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
