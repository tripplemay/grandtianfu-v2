"""Deterministic bitmap ingest primitives for SpatialModel drafts."""

from .bitmap import BitmapError, ingest_bitmap, preprocess_bitmap

__all__ = ["BitmapError", "ingest_bitmap", "preprocess_bitmap"]
