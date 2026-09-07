from __future__ import annotations

import io

from ingest import crop_ingest, ingest_bitmap, load_bitmap
from ingest.bitmap import _map_roi_coordinates
from PIL import Image, ImageDraw
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


def test_roi_coordinate_mapping_covers_nested_evidence_and_dict_geometry():
    model = {
        "model_id": "bitmap-local",
        "source": {"sha256": "crop-hash"},
        "walls": [{"x": 1.23456789, "y": 2.34567891,
                   "dimension_provenance": {"source_asset_sha256": "crop-hash"}}],
        "rooms": [{"rect": [1.1, 2.2, 3.3, 4.4], "world_rect_mm": [1.1, 2.2, 3.3, 4.4],
                   "dimension_provenance": {"pixel_rect": [1, 2, 3, 4],
                                              "world_rect_mm": [1.1, 2.2, 3.3, 4.4],
                                              "source_asset_sha256": "crop-hash"}}],
        "openings": [],
        "ingest": {
            "mm_per_pixel": 10,
            "warnings": [],
            "candidates": [{"evidence_bbox": [1, 2, 3, 4],
                            "pixel_geometry": {"bbox": [1, 2, 3, 4], "x": 1, "y": 2},
                            "geometry_mm": {"x": 1.1, "y": 2.2, "world_rect_mm": [1, 2, 3, 4]},
                            "source_asset_sha256": "crop-hash"}],
            "evidence": {"ocr": {"dimensions": [{"evidence_bbox": [3, 4, 5, 6]}]},
                         "unassigned_lines": [{"axis": "v", "coordinate": 5, "start": 6, "end": 14,
                                                "intervals": [[6, 10]], "gaps": [[10, 14]],
                                                "evidence_bbox": [5, 6, 7, 8],
                                                "paired_evidence": [[9, 10, 2, 2]]}]},
            "preprocessing": {"line_candidates": [{"evidence_bbox": [7, 8, 9, 10],
                                                       "source_asset_sha256": "crop-hash"}]},
        },
    }
    mapped = _map_roi_coordinates(model, [10, 20, 30, 40], "parent", "root-hash", "roi-id")
    assert mapped["walls"][0]["x"] == 101.234568
    assert mapped["rooms"][0]["world_rect_mm"] == [101.1, 202.2, 3.3, 4.4]
    candidate = mapped["ingest"]["candidates"][0]
    assert candidate["pixel_geometry"]["bbox"] == [11, 22, 3, 4]
    assert candidate["geometry_mm"]["world_rect_mm"] == [101, 202, 3, 4]
    assert mapped["ingest"]["evidence"]["ocr"]["dimensions"][0]["evidence_bbox"] == [13, 24, 5, 6]
    assert mapped["ingest"]["evidence"]["unassigned_lines"][0]["paired_evidence"] == [[19, 30, 2, 2]]
    line = mapped["ingest"]["evidence"]["unassigned_lines"][0]
    assert (line["coordinate"], line["start"], line["end"]) == (15, 26, 34)
    assert line["intervals"] == [[26, 30]] and line["gaps"] == [[30, 34]]
    assert mapped["ingest"]["preprocessing"]["line_candidates"][0]["evidence_bbox"] == [17, 28, 9, 10]
    assert mapped["ingest"]["candidates"][0]["source_asset_sha256"] == "root-hash"


def test_exif_orientation_is_normalized_before_roi_crop():
    image = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(image).rectangle((20, 30, 280, 170), outline="black", width=4)
    exif = image.getexif()
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=exif)
    source = output.getvalue()
    asset = load_bitmap(source)
    assert (asset.width, asset.height) == (200, 300)
    parent = ingest_bitmap(source, mm_per_pixel=10)
    model, cropped = crop_ingest(source, parent_ingest_id=parent["ingest"]["ingest_id"],
                                 parent_source_sha256=parent["source"]["sha256"],
                                 bbox=[10, 10, 180, 280], mm_per_pixel=10)
    assert (cropped.width, cropped.height) == (180, 280)
    assert model["ingest"]["pixel_size"] == {"width": 200, "height": 300}
