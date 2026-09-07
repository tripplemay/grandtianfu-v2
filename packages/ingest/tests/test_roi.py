from __future__ import annotations

from ingest import crop_ingest, ingest_bitmap, load_bitmap
from test_bitmap import plan_png


def test_crop_ingest_maps_local_geometry_and_preserves_parent_provenance():
    source = plan_png()
    parent = ingest_bitmap(source, mm_per_pixel=10)
    parent_asset = load_bitmap(source)
    bbox = [36, 26, 329, 249]
    model, cropped = crop_ingest(parent_asset.normalized_png, parent_ingest_id=parent["ingest"]["ingest_id"],
                                 parent_source_sha256=parent["source"]["sha256"], bbox=bbox, mm_per_pixel=10)
    assert model["ingest"]["ingest_id"] != parent["ingest"]["ingest_id"]
    assert model["source"]["sha256"] == parent["source"]["sha256"]
    assert model["source"]["parent_ingest_id"] == parent["ingest"]["ingest_id"]
    assert model["rooms"][0]["rect"][0] >= bbox[0] * 10
    assert model["ingest"]["preprocessing"]["source_sha256"] == parent["source"]["sha256"]
    assert cropped.width == bbox[2] and cropped.height == bbox[3]
