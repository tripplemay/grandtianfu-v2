"""Deterministic bitmap ingest primitives for SpatialModel drafts."""

from .bitmap import (
    ALGORITHM_VERSION,
    BitmapError,
    crop_ingest,
    ingest_bitmap,
    ingest_key,
    load_bitmap,
    preprocess_bitmap,
    roi_ingest_key,
)
from .evaluation import (
    ANNOTATION_SCHEMA_VERSION,
    AnnotationError,
    evaluate_model,
    evaluate_rooms,
    load_annotation,
    rect_iou,
)
from .topology import TOPOLOGY_VERSION, topology_ingest_from_parent, topology_ingest_key

__all__ = ["ALGORITHM_VERSION", "ANNOTATION_SCHEMA_VERSION", "TOPOLOGY_VERSION", "AnnotationError", "BitmapError", "crop_ingest", "evaluate_model", "evaluate_rooms", "ingest_bitmap", "ingest_key", "load_annotation", "load_bitmap", "preprocess_bitmap", "rect_iou", "roi_ingest_key", "topology_ingest_from_parent", "topology_ingest_key"]
