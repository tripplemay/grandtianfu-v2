import io
import subprocess

import pytest
from ingest import BitmapError, bitmap, ingest_bitmap, ingest_key, load_bitmap, preprocess_bitmap
from PIL import Image, ImageDraw
from spatial_core import canonical_hash, validate_model


def encode(image, format="PNG", **options):
    buffer = io.BytesIO()
    image.save(buffer, format=format, **options)
    return buffer.getvalue()


def plan_image(*, door=False, multiple=False):
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, 360, 270), outline="black", width=5)
    if door:
        draw.rectangle((175, 25, 200, 36), fill="white")
    if multiple:
        draw.line((220, 30, 220, 270), fill="black", width=5)
    return image


def plan_png(*, door=False, multiple=False):
    return encode(plan_image(door=door, multiple=multiple))


def minimal_jpeg():
    return encode(plan_image(), format="JPEG", quality=95)


def test_offset_pixel_rectangle_not_image_bounds_and_measured_scale():
    model = ingest_bitmap(plan_png(), filename="plan.png", mm_per_pixel=10)
    assert model["rooms"][0]["rect"] == [420, 320, 3160, 2360]
    assert model["coordinates"]["origin"] == "normalized_bitmap_top_left"
    assert len(model["walls"]) == 4
    assert model["ingest"]["calibration"]["provenance"] == "user_scale"
    assert all(item["needs_review"] for item in model["walls"] + model["rooms"])
    assert model["cameras"] == []
    validate_model(model)


def test_shared_wall_produces_two_elementary_nonoverlapping_rooms():
    model = ingest_bitmap(plan_png(multiple=True), mm_per_pixel=10)
    assert [room["rect"] for room in model["rooms"]] == [[420, 320, 1780, 2360], [2200, 320, 1380, 2360]]
    assert len(model["walls"]) == 5
    assert len(set(model["rooms"][0]["boundary_wall_ids"]) & set(model["rooms"][1]["boundary_wall_ids"])) == 3


@pytest.mark.parametrize("size,rect,stroke,scale,gap", [
    ((400, 300), (40, 30, 360, 270), 1, 10, (175, 200)),
    ((400, 300), (40, 30, 360, 270), 5, 12.5, (175, 200)),
    ((500, 400), (80, 90, 430, 350), 7, 8, (230, 255)),
    ((640, 480), (60, 50, 580, 420), 9, 5, (250, 300)),
    ((800, 600), (80, 60, 720, 540), 9, 5, (350, 400)),
])
def test_annotated_synthetic_fixture_accuracy_gate(size, rect, stroke, scale, gap):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(rect, outline="black", width=stroke)
    draw.rectangle((gap[0], rect[1] - 2, gap[1], rect[1] + stroke + 2), fill="white")
    model = ingest_bitmap(encode(image), mm_per_pixel=scale)
    inset = (stroke - 1) / 2
    expected = [rect[0] + inset, rect[1] + inset, rect[2] - rect[0] - 2 * inset, rect[3] - rect[1] - 2 * inset]
    actual = [value / scale for value in model["rooms"][0]["rect"]]
    expected_axes = [("h", expected[1]), ("h", expected[1] + expected[3]),
                     ("v", expected[0]), ("v", expected[0] + expected[2])]
    errors = [min(abs(wall["y" if axis == "h" else "x"] / scale - position)
                  for wall in model["walls"] if wall["axis"] == axis) for axis, position in expected_axes]
    assert sorted(errors)[len(errors) // 2] <= 2
    intersection = max(0, min(actual[0] + actual[2], expected[0] + expected[2]) - max(actual[0], expected[0]))
    intersection *= max(0, min(actual[1] + actual[3], expected[1] + expected[3]) - max(actual[1], expected[1]))
    union = actual[2] * actual[3] + expected[2] * expected[3] - intersection
    assert intersection / union >= 0.95
    matching_gaps = [opening for opening in model["openings"] if abs(opening["width"] / scale - (gap[1] - gap[0] + 1)) <= 2]
    assert len(matching_gaps) / 1 >= 0.9
    for measured, expected_pixels in zip(model["rooms"][0]["rect"][2:], expected[2:], strict=True):
        assert abs(measured - expected_pixels * scale) <= max(10, expected_pixels * scale * 0.01)


def test_gap_becomes_hosted_passage_candidate_without_claiming_door_class():
    model = ingest_bitmap(plan_png(door=True), mm_per_pixel=10)
    opening = model["openings"][0]
    assert opening["kind"] == "passage"
    assert opening["host_wall_id"] in {wall["id"] for wall in model["walls"]}
    assert opening["width"] == 260
    assert opening["provenance"] == "wall_gap_unclassified"
    assert opening["height_provenance"]["source"] == "default_unmeasured"
    assert opening["needs_review"]


@pytest.mark.parametrize("size,rect,width", [((400, 320), (40, 40, 360, 280), 9), ((320, 240), (40, 40, 280, 200), 7)])
@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_thick_orthogonal_walls_are_not_hough_diagonal_false_positives(size, rect, width, format):
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle(rect, outline="black", width=width)
    assert len(ingest_bitmap(encode(image, format=format), mm_per_pixel=10)["rooms"]) == 1


def test_merge_candidate_requires_a_gap_in_shared_partition_not_external_wall():
    exterior_gap = ingest_bitmap(plan_png(multiple=True, door=True), mm_per_pixel=10)
    assert not any(candidate["kind"] == "merge_group" for candidate in exterior_gap["ingest"]["candidates"])
    image = plan_image(multiple=True)
    ImageDraw.Draw(image).rectangle((216, 120, 224, 145), fill="white")
    partition_gap = ingest_bitmap(encode(image), mm_per_pixel=10)
    assert len([candidate for candidate in partition_gap["ingest"]["candidates"] if candidate["kind"] == "merge_group"]) == 1


def test_double_outline_is_paired_to_centerline_and_pixel_thickness():
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, 360, 270), outline="black", width=1)
    draw.rectangle((48, 38, 352, 262), outline="black", width=1)
    model = ingest_bitmap(encode(image), mm_per_pixel=10)
    assert model["rooms"][0]["rect"] == [440, 340, 3120, 2320]
    assert all(wall["thickness"] == 90 for wall in model["walls"])


def test_distant_parallel_page_lines_are_not_paired_as_a_wall():
    lines = [
        {"axis": "h", "coordinate": 100.0, "start": 40.0, "end": 960.0, "thickness": 2.0,
         "evidence_bbox": [40, 99, 921, 2], "strength": 1.0, "intervals": [[40.0, 960.0]], "gaps": []},
        {"axis": "h", "coordinate": 220.0, "start": 40.0, "end": 960.0, "thickness": 2.0,
         "evidence_bbox": [40, 219, 921, 2], "strength": 1.0, "intervals": [[40.0, 960.0]], "gaps": []},
    ]
    paired = bitmap._pair_parallel(lines, maximum_thickness=180)
    assert len(paired) == 2
    assert all("paired_evidence" not in line for line in paired)


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_complete_png_and_jpeg_have_real_pixel_geometry(format):
    data = encode(plan_image(), format=format)
    asset = load_bitmap(data)
    model = ingest_bitmap(data, mm_per_pixel=10)
    assert model["ingest"]["preprocessing"]["decoder"] == "Pillow"
    assert model["rooms"][0]["rect"] == [420, 320, 3160, 2360]
    assert preprocess_bitmap(asset)["line_candidates"]


@pytest.mark.parametrize("orientation", range(1, 9))
def test_exif_is_applied_with_replayable_pixel_transform(orientation):
    image = plan_image()
    exif = Image.Exif()
    exif[274] = orientation
    asset = load_bitmap(encode(image, format="JPEG", exif=exif, quality=95))
    assert (asset.width, asset.height) == ((300, 400) if orientation >= 5 else (400, 300))
    assert asset.normalization["exif_orientation"] == orientation
    assert len(asset.normalization["source_to_normalized_transform"]) == 3
    assert ingest_bitmap(asset.data, mm_per_pixel=10)["rooms"]


def test_transparent_and_palette_png_are_composited_white():
    image = plan_image().convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y][:3] == (255, 255, 255):
                pixels[x, y] = (0, 0, 0, 0)
    for candidate in (image, image.convert("P")):
        asset = load_bitmap(encode(candidate))
        with Image.open(io.BytesIO(asset.normalized_png)) as normalized:
            assert normalized.mode == "RGB"
            assert normalized.getpixel((0, 0)) == (255, 255, 255)
        assert ingest_bitmap(asset.data, mm_per_pixel=10)["rooms"]


def test_three_runs_and_display_filename_do_not_change_model_or_normalized_hash():
    data = plan_png(door=True)
    models = [ingest_bitmap(data, filename=name, mm_per_pixel=10) for name in ("first.png", "other.png", "third.png")]
    assert len({canonical_hash(model) for model in models}) == 1
    assert len({load_bitmap(data).normalization["normalized_sha256"] for _ in range(3)}) == 1
    assert models[0]["model_id"] == f"bitmap-{ingest_key(data, 10)[:24]}"
    assert ingest_key(data, 10) != ingest_key(data, 20)


@pytest.mark.parametrize("scale", [None, 0, -1, True, float("inf"), float("nan"), "10", 1e20])
def test_missing_invalid_or_unbounded_scale_is_rejected(scale):
    with pytest.raises(BitmapError, match="scale"):
        ingest_bitmap(plan_png(), mm_per_pixel=scale)


@pytest.mark.parametrize("data", [b"", b"not-an-image", b"%PDF-1.7", b"\xff\xd8\xff\xd9", b"\x89PNG\r\n\x1a\n"])
def test_invalid_images_are_rejected(data):
    with pytest.raises(BitmapError):
        ingest_bitmap(data, mm_per_pixel=10)


def test_header_only_and_truncated_jpeg_are_not_admitted():
    jpeg = minimal_jpeg()
    for data in (jpeg[:100] + b"\xff\xd9", jpeg[:-20], jpeg[:len(jpeg) // 2] + b"\xff\xd9"):
        with pytest.raises(BitmapError):
            load_bitmap(data)


def test_png_crc_and_truncation_are_not_admitted():
    payload = bytearray(plan_png())
    payload[29] ^= 1
    for data in (bytes(payload), plan_png()[:-12]):
        with pytest.raises(BitmapError):
            load_bitmap(data)


def test_limits_are_checked_before_full_decode(monkeypatch):
    monkeypatch.setattr(bitmap, "MAX_PIXELS", 100)
    with pytest.raises(BitmapError, match="input_too_large"):
        load_bitmap(plan_png())
    monkeypatch.setattr(bitmap, "MAX_FILE_BYTES", 10)
    with pytest.raises(BitmapError, match="input_too_large"):
        load_bitmap(plan_png())


def test_blank_open_boundary_and_diagonal_never_invent_a_room():
    blank = Image.new("RGB", (400, 300), "white")
    opened = plan_image()
    ImageDraw.Draw(opened).rectangle((0, 0, 399, 45), fill="white")
    diagonal = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(diagonal).polygon(((50, 80), (340, 30), (360, 250), (70, 280)), outline="black", width=3)
    for image in (blank, opened):
        with pytest.raises(BitmapError, match="no_closed_rectangle"):
            ingest_bitmap(encode(image), mm_per_pixel=10)
    with pytest.raises(BitmapError, match="non_orthogonal_candidate"):
        ingest_bitmap(encode(diagonal), mm_per_pixel=10)


def test_unassigned_structural_lines_block_confirmation_instead_of_becoming_facts():
    image = plan_image()
    ImageDraw.Draw(image).line((10, 10, 390, 10), fill="black", width=5)
    model = ingest_bitmap(encode(image), mm_per_pixel=10)
    assert model["ingest"]["hard_blockers"][0]["code"] == "partial_plan_requires_manual_trace"
    assert model["ingest"]["hard_blockers"][0]["count"] > 0
def test_optional_ocr_missing_runtime_is_explicit(monkeypatch):
    monkeypatch.setattr(bitmap.shutil, "which", lambda _: None)
    model = ingest_bitmap(plan_png(), mm_per_pixel=10)
    assert "ocr_unavailable" in {warning["code"] for warning in model["ingest"]["warnings"]}


def test_ocr_tsv_is_evidence_only_and_never_changes_calibration(monkeypatch):
    tsv = "level\tleft\ttop\twidth\theight\tconf\ttext\n5\t70\t10\t40\t15\t94\t3000\n"
    monkeypatch.setattr(bitmap, "_ocr_runtime", lambda: {"engine": "tesseract", "version": "test"})
    monkeypatch.setattr(bitmap.shutil, "which", lambda _: "/test/tesseract")
    monkeypatch.setattr(bitmap.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, tsv.encode(), b""))
    model = ingest_bitmap(plan_png(), mm_per_pixel=10)
    evidence = model["ingest"]["evidence"]["ocr"]["dimensions"][0]
    assert evidence["text"] == "3000"
    assert evidence["association"] is None
    assert evidence["needs_review"]
    assert model["ingest"]["calibration"]["value"] == 10
    assert model["rooms"][0]["rect"][2] == 3160
