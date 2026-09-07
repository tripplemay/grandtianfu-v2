"""Bitmap import and explicit review in a real browser, with isolated storage."""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ingest_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture()
def ingest_page(ingest_browser, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        **os.environ,
        "GT_DB_PATH": str(tmp_path / "workbench.sqlite3"),
        "GT_INGEST_ROOT": str(tmp_path / "ingests"),
        "GT_RENDER_ROOT": str(tmp_path / "renders"),
    }
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "apps.api.app:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        context = ingest_browser.new_context(viewport={"width": 1440, "height": 960}, base_url=f"http://127.0.0.1:{port}")
        errors = []
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/models", timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Isolated ingest workbench did not start")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("/")
            page.wait_for_load_state("networkidle")
            expect(page.get_by_text("几何校验通过", exact=True)).to_be_visible()
            yield page
            assert errors == []
        finally:
            context.close()
            process.terminate()
            process.wait(timeout=10)


def bitmap():
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, 360, 270), outline="black", width=5)
    draw.rectangle((175, 25, 200, 36), fill="white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def upload(page):
    page.get_by_test_id("open-ingest").click()
    page.get_by_test_id("ingest-file").set_input_files({"name": "plan.png", "mimeType": "image/png", "buffer": bitmap()})
    expect(page.get_by_test_id("ingest-scale")).to_have_value("")
    expect(page.get_by_test_id("ingest-submit")).to_be_disabled()
    page.get_by_test_id("ingest-scale").fill("10")
    with page.expect_response(lambda response: response.url.endswith("/api/ingests?mm_per_pixel=10") and response.request.method == "POST") as response:
        page.get_by_test_id("ingest-submit").click()
    assert response.value.status == 201, response.value.text()
    result = response.value.json()
    expect(page.get_by_role("dialog", name="导入户型图")).not_to_be_visible()
    expect(page.get_by_text("户型图已导入 · 待人工校核", exact=True)).to_be_visible()
    return result


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 960}, {"width": 390, "height": 844}])
def test_import_overlay_review_and_explicit_camera(ingest_page, viewport):
    page = ingest_page
    page.set_viewport_size(viewport)
    result = upload(page)
    model = result["envelope"]["model"]
    assert model["status"] == "draft"
    assert model["rooms"] and model["walls"]
    expect(page.get_by_role("button", name="生成 3D", exact=True)).to_be_disabled()
    page.get_by_test_id("source-view").click()
    overlay = page.get_by_test_id("candidate-overlay")
    expect(overlay).to_be_visible()
    assert overlay.locator("rect").count() >= len(model["walls"]) + len(model["rooms"])
    image = page.get_by_alt_text("规范化户型位图")
    expect(image).to_be_visible()
    expect(image).to_have_js_property("complete", True)
    expect(image).to_have_js_property("naturalWidth", 400)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshots = ROOT / "artifacts/stage4-e2e"
    screenshots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshots / f"ingest-overlay-{viewport['width']}.png"), full_page=True)
    page.get_by_role("button", name="确认版本", exact=True).click()
    expect(page.get_by_test_id("review-submit")).to_be_disabled()
    page.get_by_test_id("review-all").check()
    for key in ("scale", "geometry", "openings", "heights"):
        page.get_by_test_id(f"review-{key}").check()
    review = page.get_by_role("dialog", name="人工校核")
    assert review.evaluate("dialog => dialog.scrollWidth <= dialog.clientWidth")
    bounds = review.bounding_box()
    assert 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= viewport["width"]
    page.screenshot(path=str(screenshots / f"ingest-review-{viewport['width']}.png"), full_page=True)
    page.get_by_role("dialog", name="人工校核").get_by_role("button", name="取消", exact=True).click()
    page.get_by_role("button", name="固定相机", exact=True).click()
    expect(page.get_by_test_id("camera-position-x")).to_have_value("")
    expect(page.get_by_test_id("camera-save")).to_be_disabled()
    for group, coordinates in {"position": (1000, 1000, 1800), "look_at": (2200, 2000, 700)}.items():
        for axis, value in zip("xyz", coordinates):
            page.get_by_test_id(f"camera-{group}-{axis}").fill(str(value))
    page.get_by_test_id("camera-save").click()
    expect(page.get_by_role("button", name="生成 3D", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="保存", exact=True)).to_be_enabled()
    page.get_by_role("button", name="确认版本", exact=True).click()
    expect(page.get_by_test_id("review-submit")).to_be_disabled()
    expect(page.get_by_test_id("review-all")).not_to_be_checked()
    page.get_by_role("dialog", name="人工校核").get_by_role("button", name="取消", exact=True).click()
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_text("v2 已保存", exact=True)).to_be_visible()
    page.get_by_role("button", name="确认版本", exact=True).click()
    page.get_by_test_id("review-all").check()
    for key in ("scale", "geometry", "openings", "heights"):
        page.get_by_test_id(f"review-{key}").check()
    expect(page.get_by_test_id("review-submit")).to_be_enabled()
    page.get_by_test_id("review-submit").click()
    expect(page.get_by_text("v3 人工校核已确认", exact=True)).to_be_visible()
    latest = page.request.get(f"/api/models/{model['model_id']}/latest").json()
    assert latest["model"]["status"] == "confirmed"
    assert latest["model"]["cameras"][0]["position"] == {"x": 1000, "y": 1000, "z": 1800}
    expect(page.get_by_role("button", name="生成 3D", exact=True)).to_be_enabled()
    page.get_by_role("button", name="生成 3D", exact=True).click()
    rendered = page.get_by_alt_text("空间模型三维渲染结果")
    expect(rendered).to_be_visible(timeout=30000)
    expect(rendered).to_have_js_property("complete", True)
    assert rendered.evaluate("""img => {
      const canvas = document.createElement('canvas');
      canvas.width = 32; canvas.height = 24;
      const context = canvas.getContext('2d');
      context.drawImage(img, 0, 0, 32, 24);
      const pixels = context.getImageData(0, 0, 32, 24).data;
      const colors = new Set();
      for (let i = 0; i < pixels.length; i += 4) colors.add(`${pixels[i]},${pixels[i+1]},${pixels[i+2]}`);
      return colors.size > 2;
    }""")
    page.screenshot(path=str(screenshots / f"ingest-render-{viewport['width']}.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_import_cancel_and_decode_error(ingest_page):
    page = ingest_page
    page.get_by_test_id("open-ingest").click()
    page.get_by_test_id("ingest-file").set_input_files({"name": "broken.png", "mimeType": "image/png", "buffer": b"broken"})
    expect(page.get_by_text("图像无法解码", exact=True)).to_be_visible()
    expect(page.get_by_test_id("ingest-submit")).to_be_disabled()
    page.get_by_role("dialog", name="导入户型图").get_by_role("button", name="取消", exact=True).click()
    expect(page.get_by_role("dialog", name="导入户型图")).not_to_be_visible()
    expect(page.get_by_text("几何校验通过", exact=True)).to_be_visible()


def test_opening_candidate_can_be_classified_and_saved(ingest_page):
    page = ingest_page
    result = upload(page)
    model = result["model"]
    opening = model["openings"][0]
    assert opening["kind"] == "passage"
    page.get_by_test_id(f"opening-{opening['id']}").click()
    kind = page.get_by_role("combobox", name="开口类型", exact=True)
    expect(kind).to_have_value("passage")
    kind.select_option("door")
    expect(page.get_by_role("button", name="保存", exact=True)).to_be_enabled()
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_text("v2 已保存", exact=True)).to_be_visible()
    latest = page.request.get(f"/api/models/{model['model_id']}/latest").json()["model"]
    assert latest["status"] == "draft"
    assert latest["openings"][0]["kind"] == "door"
    assert latest["openings"][0]["offset"] == opening["offset"]
    assert latest["ingest"]["ingest_id"] == result["ingest_id"]
