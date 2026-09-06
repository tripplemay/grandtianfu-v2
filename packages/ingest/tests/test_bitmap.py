import struct
import zlib

import pytest
from ingest import BitmapError, ingest_bitmap, preprocess_bitmap
from spatial_core import validate_model


def png(width: int, height: int, pixels: list[list[tuple[int, int, int]]], filter_type: int = 0) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    raw = b"".join(bytes([filter_type]) + bytes(channel for pixel in row for channel in pixel) for row in pixels)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def minimal_jpeg(width: int = 32, height: int = 16) -> bytes:
    # SOI + baseline SOF0 frame; the decoder intentionally needs no pixel decode.
    frame = bytes([8]) + struct.pack(">HH", height, width) + bytes([1, 0x11, 0])
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame + b"\xff\xd9"


def test_png_preprocessing_extracts_dark_rows_and_columns():
    pixels = [[(255, 255, 255) for _ in range(8)] for _ in range(6)]
    pixels[2] = [(0, 0, 0) for _ in range(8)]
    for row in pixels:
        row[4] = (0, 0, 0)
    model = ingest_bitmap(png(8, 6, pixels), filename="plan.png", mm_per_pixel=5)
    assert model["status"] == "draft"
    assert model["source"]["kind"] == "bitmap"
    assert model["ingest"]["pixel_size"] == {"width": 8, "height": 6}
    candidates = model["ingest"]["preprocessing"]["line_candidates"]
    assert 2 in candidates["horizontal_rows_px"]
    assert 4 in candidates["vertical_columns_px"]
    validate_model(model)


def test_preprocessing_is_deterministic():
    pixels = [[(10, 20, 30), (10, 20, 30)], [(10, 20, 30), (10, 20, 30)]]
    # Repeated preprocessing must preserve byte-for-byte equivalent statistics.
    asset_model = ingest_bitmap(png(2, 2, pixels), filename="same.png")
    assert preprocess_bitmap(type("Asset", (), {"data": png(2, 2, pixels), "media_type": "image/png"})()) == preprocess_bitmap(type("Asset", (), {"data": png(2, 2, pixels), "media_type": "image/png"})())
    assert asset_model["ingest"]["preprocessing"]["mean_luma"] == 18.0


def test_jpeg_dimensions_are_supported_but_have_low_confidence():
    model = ingest_bitmap(minimal_jpeg(), filename="scan.jpg")
    assert model["ingest"]["media_type"] == "image/jpeg"
    assert model["ingest"]["preprocessing"]["decoder"] == "jpeg-header-only"
    assert model["ingest"]["preprocessing"]["confidence"] < 0.2
    assert model["ingest"]["requires_human_review"] is True


def test_png_crc_corruption_fails_closed():
    data = bytearray(png(1, 1, [[(0, 0, 0)]]))
    data[29] ^= 0x01  # IHDR CRC byte
    with pytest.raises(BitmapError, match="CRC"):
        ingest_bitmap(bytes(data))


@pytest.mark.parametrize("payload", [b"", b"not-an-image", b"\x89PNG\r\n\x1a\n"])
def test_invalid_uploads_fail_closed(payload):
    with pytest.raises(BitmapError):
        ingest_bitmap(payload)


def test_truncated_png_without_iend_fails_closed():
    pixels = [[(255, 255, 255)]]
    payload = png(1, 1, pixels)[:-12]
    with pytest.raises(BitmapError, match="IEND"):
        ingest_bitmap(payload)


def test_invalid_calibration_fails_and_default_never_becomes_measured():
    with pytest.raises(BitmapError, match="mm_per_pixel"):
        ingest_bitmap(minimal_jpeg(), mm_per_pixel=0)
    model = ingest_bitmap(minimal_jpeg())
    assert model["status"] == "draft"
    assert model["ingest"]["calibration"]["confidence"] < 0.5
    assert model["ingest"]["calibration"]["provenance"] == "caller_default_or_input"


def test_model_id_and_revision_are_reproducible_inputs():
    first = ingest_bitmap(minimal_jpeg(), filename="a.jpg", model_id="model-1", revision=3)
    second = ingest_bitmap(minimal_jpeg(), filename="a.jpg", model_id="model-1", revision=3)
    assert first == second
    assert first["model_id"] == "model-1"
    assert first["revision"] == 3


def test_only_draft_is_emitted_even_if_caller_attempts_confirmation():
    model = ingest_bitmap(minimal_jpeg(), filename="a.jpg")
    assert model["status"] == "draft"
    assert model["ingest"]["requires_human_review"] is True
