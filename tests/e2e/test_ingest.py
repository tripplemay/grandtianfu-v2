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
    # Overlay deliberately uses the immutable source bitmap so pixel evidence
    # remains in parent coordinates; only the normalized tab uses preprocessed.
    image = page.get_by_alt_text("原始户型位图")
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


def test_roi_candidate_selection_preserves_review_gate_and_surfaces_crop_failure(ingest_page):
    page = ingest_page
    upload(page)
    page.get_by_test_id("source-view").click()
    expect(page.get_by_test_id("roi-count")).to_have_text("1 个候选")
    candidate = page.get_by_test_id("roi-candidate-roi-candidate-1")
    expect(candidate).to_be_visible()
    expect(page.get_by_test_id("roi-crop-submit")).to_be_disabled()
    page.get_by_role("button", name="确认版本", exact=True).click()
    expect(page.get_by_test_id("review-submit")).to_be_disabled()
    page.get_by_role("dialog", name="人工校核").get_by_role("button", name="取消", exact=True).click()

    seen = {}

    def reject_crop(route):
        seen["method"] = route.request.method
        seen["body"] = route.request.post_data_json
        route.fulfill(status=422, content_type="application/json", body='{"detail":"ROI recognition rejected"}')

    page.route("**/api/ingests/*/crop", reject_crop)
    candidate.click()
    expect(page.get_by_test_id("roi-selected-status")).to_be_visible()
    expect(page.get_by_test_id("roi-crop-submit")).to_be_enabled()
    page.get_by_test_id("roi-crop-submit").click()
    expect(page.get_by_test_id("roi-crop-error")).to_contain_text("ROI recognition rejected")
    assert seen["method"] == "POST"
    assert seen["body"]["bbox"] == [36, 26, 329, 249]
    assert isinstance(seen["body"]["expected_source_sha256"], str)
    page.unroute("**/api/ingests/*/crop", reject_crop)


def test_roi_crop_success_creates_derived_draft_and_keeps_parent_source(ingest_page):
    page = ingest_page
    parent = upload(page)
    page.get_by_test_id("source-view").click()
    page.get_by_test_id("roi-candidate-roi-candidate-1").click()
    with page.expect_response(lambda response: response.url.endswith("/crop") and response.request.method == "POST") as response:
        page.get_by_test_id("roi-crop-submit").click()
    assert response.value.status == 201, response.value.text()
    expect(page.get_by_text("已按原图候选生成新草稿 · 原始证据保留", exact=True)).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("roi-derived-draft")).to_contain_text(parent["ingest_id"][:12])
    source = page.get_by_alt_text("原始户型位图")
    expect(source).to_be_visible()
    expect(source).to_have_js_property("naturalWidth", 400)


    page.get_by_role("button", name="规范化位图", exact=True).click()
    normalized = page.get_by_alt_text("规范化户型位图")
    expect(normalized).to_have_js_property("naturalWidth", 329)
    page.get_by_role("button", name="候选叠加", exact=True).click()
    expect(page.get_by_alt_text("原始户型位图")).to_have_js_property("naturalWidth", 400)


def fill_rect(page, prefix, values):
    for axis, value in zip("xywh", values):
        page.get_by_test_id(f"{prefix}-{axis}").fill(str(value))


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 960}, {"width": 390, "height": 844}])
def test_free_roi_failure_then_manual_multiroom_trace(ingest_page, viewport):
    page = ingest_page
    page.set_viewport_size(viewport)
    parent = upload(page)
    page.get_by_test_id("source-view").click()
    fill_rect(page, "roi", [20, 20, 360, 260])
    expect(page.get_by_test_id("roi-crop-submit")).to_be_enabled()
    fill_rect(page, "roi", [20, 20, 400, 260])
    expect(page.get_by_test_id("roi-crop-submit")).to_be_disabled()
    fill_rect(page, "roi", [20, 20, 360, 260])

    def reject(route):
        route.fulfill(status=422, content_type="application/json", body='{"detail":"overlapping_room_candidates"}')

    page.route("**/api/ingests/*/crop", reject)
    page.get_by_test_id("roi-crop-submit").click()
    expect(page.get_by_test_id("roi-crop-error")).to_contain_text("overlapping_room_candidates")
    page.unroute("**/api/ingests/*/crop", reject)
    expect(page.get_by_test_id("roi-x")).to_have_value("20")
    page.get_by_test_id("trace-room-name").fill("Living")
    page.get_by_role("combobox", name="描图房间类型", exact=True).select_option("living")
    fill_rect(page, "trace-room", [40.25, 40, 139.75, 200])
    page.get_by_test_id("trace-room-apply").click()
    expect(page.get_by_test_id("trace-room-select-0")).to_have_text("Living")
    page.get_by_role("button", name="新增房间", exact=True).click()
    page.get_by_test_id("trace-room-name").fill("Dining")
    page.get_by_role("combobox", name="描图房间类型", exact=True).select_option("dining")
    fill_rect(page, "trace-room", [180, 40, 170, 200])
    page.get_by_test_id("trace-room-apply").click()
    page.get_by_role("button", name="撤销描图", exact=True).click()
    expect(page.get_by_test_id("trace-room-select-1")).not_to_be_visible()
    page.get_by_role("button", name="重做描图", exact=True).click()
    expect(page.get_by_test_id("trace-room-select-1")).to_have_text("Dining")
    page.get_by_test_id("trace-wall-thickness").fill("120.5")
    page.get_by_test_id("trace-wall-height").fill("2800")
    expect(page.get_by_test_id("trace-submit")).to_be_enabled()
    page.get_by_role("button", name="二维平面", exact=True).click()
    expect(page.get_by_role("dialog", name="放弃未保存的修改？")).to_be_visible()
    page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
    expect(page.get_by_test_id("trace-room-select-1")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshots = ROOT / "artifacts/stage4-trace-e2e"
    screenshots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshots / f"manual-trace-{viewport['width']}.png"), full_page=True)
    with page.expect_response(lambda r: r.url.endswith("/trace") and r.request.method == "POST") as response:
        page.get_by_test_id("trace-submit").click()
    assert response.value.status == 201, response.value.text()
    child = response.value.json()
    model = child["model"]
    assert child["ingest_id"] != parent["ingest_id"]
    assert model["source"]["sha256"] == parent["model"]["source"]["sha256"]
    assert model["rooms"][0]["rect"] == [402.5, 400, 1397.5, 2000]
    shared = [w for w in model["walls"] if w["axis"] == "v" and w["x"] == 1800]
    assert len(shared) == 1
    assert all(shared[0]["id"] in r["boundary_wall_ids"] for r in model["rooms"])
    assert model["openings"] == []
    assert model["ingest"]["hard_blockers"][0]["code"] == "manual_trace_requires_topology_review"
    expect(page.get_by_text("人工描图草稿已生成 · 待拓扑校核", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="生成 3D", exact=True)).to_be_disabled()
    page.get_by_role("button", name="确认版本", exact=True).click()
    expect(page.get_by_test_id("review-submit")).to_be_disabled()
    page.get_by_role("dialog", name="人工校核").get_by_role("button", name="取消", exact=True).click()
    page.get_by_test_id("topology-view").click()
    expect(page.get_by_test_id("topology-editor")).to_be_visible()
    host_wall = next(wall for wall in model["walls"] if wall["length"] >= 900)
    page.get_by_role("combobox", name="宿主墙体", exact=True).select_option(host_wall["id"])
    page.get_by_test_id("topology-add-opening").click()
    page.get_by_test_id("topology-opening-0").get_by_role("button", name="编辑开口", exact=True).click()
    page.get_by_label("宽度", exact=True).fill("800")
    page.get_by_test_id("topology-add-opening").click()
    expect(page.get_by_test_id("topology-opening-0")).to_contain_text("0 + 800")
    page.get_by_label("Living", exact=True).check()
    page.get_by_label("Dining", exact=True).check()
    page.get_by_test_id("topology-add-group").click()
    expect(page.get_by_test_id("topology-group-0")).to_contain_text("共享墙：")
    with page.expect_response(lambda r: r.url.endswith("/topology") and r.request.method == "POST") as response:
        page.get_by_test_id("topology-submit").click()
    assert response.value.status == 201, response.value.text()
    topology = response.value.json()
    assert topology["model"]["source"]["provenance"] == "manual_topology"
    assert topology["model"]["openings"]
    assert topology["model"]["rooms"][0]["merge_group_id"]
    expect(page.get_by_text("拓扑审核草稿已生成 · 待人工确认", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="生成 3D", exact=True)).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("button", name="固定相机", exact=True).click()
    for group, coordinates in {"position": (-3000, -3500, 5000), "look_at": (1900, 1400, 1000)}.items():
        for axis, value in zip("xyz", coordinates):
            page.get_by_test_id(f"camera-{group}-{axis}").fill(str(value))
    page.get_by_test_id("camera-save").click()
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_text("v2 已保存", exact=True)).to_be_visible()
    page.get_by_role("button", name="确认版本", exact=True).click()
    expect(page.get_by_test_id("topology-review-scope")).to_be_visible()
    page.get_by_test_id("review-all").check()
    for key in ("scale", "geometry", "openings", "heights", "topology"):
        page.get_by_test_id(f"review-{key}").check()
    expect(page.get_by_test_id("review-submit")).to_be_disabled()
    page.get_by_test_id("review-coverage").check()
    page.get_by_test_id("review-submit").click()
    expect(page.get_by_text("v3 人工校核已确认", exact=True)).to_be_visible()
    latest = page.request.get(f"/api/models/{topology['model']['model_id']}/latest").json()
    assert latest["model"]["review"]["topology_confirmation"]["scope"] == "traced_regions"
    assert latest["model"]["ingest"] == topology["model"]["ingest"]
    page.get_by_role("button", name="生成 3D", exact=True).click()
    rendered = page.get_by_alt_text("空间模型三维渲染结果")
    expect(rendered).to_be_visible(timeout=30000)
    expect(rendered).to_have_js_property("complete", True)
    assert rendered.evaluate("""img => {
      const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 24;
      const context = canvas.getContext('2d'); context.drawImage(img, 0, 0, 32, 24);
      const data = context.getImageData(0, 0, 32, 24).data, colors = new Set();
      for (let i = 0; i < data.length; i += 4) colors.add(`${data[i]},${data[i+1]},${data[i+2]}`);
      return colors.size > 2;
    }""")
    screenshots = ROOT / "artifacts/stage4-confirmation-e2e"
    screenshots.mkdir(parents=True, exist_ok=True)
    rendered.screenshot(path=str(screenshots / f"shell-{viewport['width']}.png"))
    page.screenshot(path=str(screenshots / f"confirmed-{viewport['width']}.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("touch", [False, True])
def test_roi_reverse_drag_and_room_drag(ingest_page, touch):
    page = ingest_page
    if touch:
        page.set_viewport_size({"width": 390, "height": 844})
    upload(page)
    page.get_by_test_id("source-view").click()
    page.get_by_role("button", name="绘制户型区域", exact=True).click()
    surface = page.get_by_test_id("candidate-overlay")
    surface.scroll_into_view_if_needed()
    bounds = surface.bounding_box()
    def position(x, y):
        return bounds["x"] + x / 400 * bounds["width"], bounds["y"] + y / 300 * bounds["height"]
    def drag(first, last):
        if touch:
            session = page.context.new_cdp_session(page)
            session.send("Emulation.setTouchEmulationEnabled", {"enabled": True})
            x, y = position(*first)
            session.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            x, y = position(*last)
            session.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
            session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            session.detach()
        else:
            page.mouse.move(*position(*first))
            page.mouse.down()
            page.mouse.move(*position(*last), steps=8)
            page.mouse.up()
    drag((380, 280), (20, 20))
    assert abs(float(page.get_by_test_id("roi-x").input_value()) - 20) <= 1
    expect(page.get_by_test_id("roi-crop-submit")).to_be_enabled()
    page.get_by_role("button", name="绘制矩形房间", exact=True).click()
    surface.scroll_into_view_if_needed()
    bounds = surface.bounding_box()
    drag((40, 40), (180, 240))
    expect(page.get_by_test_id("trace-room-select-0")).to_have_text("房间 1")
    page.get_by_role("button", name="删除描图房间", exact=True).click()
    expect(page.get_by_test_id("trace-room-select-0")).not_to_be_visible()
    expect(page.get_by_test_id("trace-submit")).to_be_disabled()
