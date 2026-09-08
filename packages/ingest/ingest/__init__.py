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
from .dataset import (
    DATASET_SCHEMA_VERSION,
    DatasetError,
    dataset_manifest_hash,
    evaluate_dataset,
    inspect_dataset,
    load_dataset_manifest,
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

__all__ = ["ALGORITHM_VERSION", "ANNOTATION_SCHEMA_VERSION", "DATASET_SCHEMA_VERSION", "TOPOLOGY_VERSION", "AnnotationError", "BitmapError", "DatasetError", "crop_ingest", "dataset_manifest_hash", "evaluate_dataset", "evaluate_model", "evaluate_rooms", "ingest_bitmap", "ingest_key", "inspect_dataset", "load_annotation", "load_bitmap", "load_dataset_manifest", "preprocess_bitmap", "rect_iou", "roi_ingest_key", "topology_ingest_from_parent", "topology_ingest_key"]
