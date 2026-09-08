"""Command-line CPU render worker for one SpatialModel document."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .renderer import RenderError, render_model

INPUT_ERROR = 2
RENDER_ERROR = 3
OUTPUT_ERROR = 4


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _parse_json(raw: str) -> dict[str, Any]:
    value = json.loads(raw, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise TypeError("input JSON must be an object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render one SpatialModel with the CPU scene3d worker")
    parser.add_argument("--input", type=Path, help="SpatialModel JSON path; omit to read stdin")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--width", type=int, help="Override output width (1..4096)")
    parser.add_argument("--height", type=int, help="Override output height (1..4096)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
        model = _parse_json(raw)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"worker input error: {exc}", file=sys.stderr)
        return INPUT_ERROR
    try:
        manifest = render_model(model, args.output, width=args.width, height=args.height)
    except RenderError as exc:
        print(f"worker render error: {exc}", file=sys.stderr)
        return RENDER_ERROR
    except (OSError, UnicodeError) as exc:
        print(f"worker output error: {exc}", file=sys.stderr)
        return OUTPUT_ERROR
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
