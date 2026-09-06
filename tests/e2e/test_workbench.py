"""Real browser acceptance against an isolated SQLite database per test."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "fixture-living-merge-001"
API = f"/api/models/{MODEL_ID}"


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture()
def workbench(browser, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {**os.environ, "GT_DB_PATH": str(tmp_path / "workbench.sqlite3")}
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "apps.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 960}, base_url=f"http://127.0.0.1:{port}"
        )
        errors = []
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/models", timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Isolated workbench did not start")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("/")
            expect(page.get_by_text("几何校验通过", exact=True)).to_be_visible()
            yield page
            assert errors == []
        finally:
            context.close()
            process.terminate()
            process.wait(timeout=10)


def head(page):
    response = page.request.get(f"{API}/latest")
    assert response.status == 200
    return response.json()


def edit_number(page, label, value):
    field = page.get_by_role("spinbutton", name=label, exact=True)
    field.fill(str(value))
    field.press("Tab")


def save(page):
    button = page.get_by_role("button", name="保存", exact=True)
    expect(button).to_be_enabled()
    button.click()
    expect(page.get_by_text("v2 已保存", exact=True)).to_be_visible()


def select_sofa(page):
    page.get_by_test_id("furniture-sofa-1").click()
    expect(page.get_by_role("spinbutton", name="X", exact=True)).to_be_visible()


def test_decimal_save_reload_and_history_restore(workbench):
    page = workbench
    original = head(page)
    select_sofa(page)
    edit_number(page, "X", 1537.125)
    edit_number(page, "宽度", 2199.875)
    save(page)
    saved = head(page)
    assert saved["model"]["status"] == "draft"
    sofa = saved["model"]["furniture_instances"][0]
    assert sofa["transform"]["x"] == 1537.125
    assert sofa["dimensions"]["width"] == 2199.875
    page.reload()
    expect(page.get_by_text("几何校验通过", exact=True)).to_be_visible()
    assert head(page) == saved
    select_sofa(page)
    expect(page.get_by_role("spinbutton", name="X", exact=True)).to_have_value("1537.125")
    page.get_by_role("combobox", name="历史版本").select_option("1")
    expect(page.get_by_text("正在查看历史版本 v1 · 只读", exact=True)).to_be_visible()
    select_sofa(page)
    expect(page.get_by_role("spinbutton", name="X", exact=True)).to_be_disabled()
    page.get_by_role("button", name="恢复为新版本", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="恢复为新版本", exact=True).click()
    expect(page.get_by_text("v3 已保存", exact=True)).to_be_visible()
    restored = head(page)
    assert restored["model"]["revision"] == 3
    assert restored["model"]["furniture_instances"] == original["model"]["furniture_instances"]
    assert page.request.get(f"{API}/revisions/2").json() == saved


def test_drag_after_zoom_pan_undo_and_save(workbench):
    page = workbench
    original = head(page)
    page.get_by_role("button", name="放大", exact=True).click()
    page.get_by_role("button", name="平移画布", exact=True).click()
    surface = page.locator("svg.plan-surface")
    bounds = surface.bounding_box()
    initial_view = surface.evaluate(
        "svg => ({x: svg.viewBox.baseVal.x, y: svg.viewBox.baseVal.y, scale: svg.getScreenCTM().a})"
    )
    page.mouse.move(bounds["x"] + 30, bounds["y"] + 50)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 90, bounds["y"] + 90, steps=5)
    page.mouse.up()
    final_view = surface.evaluate("svg => ({x: svg.viewBox.baseVal.x, y: svg.viewBox.baseVal.y})")
    assert final_view["x"] == pytest.approx(
        initial_view["x"] - 60 / initial_view["scale"], abs=0.002
    )
    assert final_view["y"] == pytest.approx(
        initial_view["y"] - 40 / initial_view["scale"], abs=0.002
    )
    assert head(page) == original
    page.get_by_role("button", name="选择家具", exact=True).click()
    sofa = page.get_by_test_id("furniture-sofa-1")
    bounds = sofa.bounding_box()
    scale = surface.evaluate("svg => svg.getScreenCTM().a")
    start_x, start_y = bounds["x"] + bounds["width"] / 2, bounds["y"] + 20
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 31, start_y + 9, steps=8)
    page.mouse.up()
    expected_x = round((1500 + 31 / scale) * 100) / 100
    expected_y = round((3300 + 9 / scale) * 100) / 100
    expect(page.get_by_role("spinbutton", name="X", exact=True)).to_have_value(
        str(expected_x).removesuffix(".0")
    )
    page.get_by_role("button", name="撤销", exact=True).click()
    expect(page.get_by_role("spinbutton", name="X", exact=True)).to_have_value("1500")
    page.get_by_role("button", name="重做", exact=True).click()
    save(page)
    transform = head(page)["model"]["furniture_instances"][0]["transform"]
    assert transform["x"] == expected_x
    assert transform["y"] == expected_y


def test_invalid_geometry_dirty_guard_and_conflict(workbench):
    page = workbench
    original = head(page)
    select_sofa(page)
    edit_number(page, "X", 5900)
    expect(page.get_by_text("1 项几何错误", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="保存", exact=True)).to_be_disabled()
    assert head(page) == original
    page.get_by_role("button", name="重新载入最新版本", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_role("button", name="取消", exact=True).click()
    expect(page.get_by_role("spinbutton", name="X", exact=True)).to_have_value("5900")
    edit_number(page, "X", 1520)
    updated = json.loads(json.dumps(original["model"]))
    updated["furniture_instances"][0]["transform"]["x"] = 1510
    result = page.request.post(
        f"{API}/revisions",
        data={
            "model": updated,
            "expected_revision": 1,
            "expected_hash": original["hash"],
            "action": "save",
            "note": "Concurrent edit",
        },
    )
    assert result.status == 201
    button = page.get_by_role("button", name="保存", exact=True)
    expect(button).to_be_enabled()
    button.click()
    expect(page.get_by_role("alert")).to_contain_text("保存冲突")
    expect(page.get_by_role("spinbutton", name="X", exact=True)).to_have_value("1520")
    assert head(page)["model"]["furniture_instances"][0]["transform"]["x"] == 1510


def test_opening_shared_room_edit_and_confirmation(workbench):
    page = workbench
    page.get_by_test_id("room-living").click(position={"x": 50, "y": 50})
    expect(page.get_by_role("spinbutton", name="房间宽度", exact=True)).to_be_disabled()
    page.get_by_test_id("room-foyer").click(position={"x": 50, "y": 50})
    edit_number(page, "房间宽度", 3200.125)
    expect(page.get_by_text("几何校验通过", exact=True)).to_be_visible()
    page.get_by_test_id("opening-window-1").click()
    edit_number(page, "沿墙偏移", 3350.5)
    button = page.get_by_role("button", name="确认版本", exact=True)
    expect(button).to_be_enabled()
    button.click()
    page.get_by_role("dialog").get_by_role("button", name="确认版本", exact=True).click()
    expect(page.get_by_text("v2 已确认", exact=True)).to_be_visible()
    model = head(page)["model"]
    assert model["rooms"][1]["rect"][2] == 3200.125
    assert next(w for w in model["walls"] if w["id"] == "wall-f-e")["x"] == 9200.125
    assert next(o for o in model["openings"] if o["id"] == "window-1")["offset"] == 3350.5
    assert model["furniture_instances"][0]["transform"]["x"] == 1500


def test_add_delete_and_cancel_numeric_input(workbench):
    page = workbench
    original = head(page)
    select_sofa(page)
    field = page.get_by_role("spinbutton", name="X", exact=True)
    field.fill("1600")
    field.press("Escape")
    expect(field).to_have_value("1500")
    expect(page.get_by_role("button", name="保存", exact=True)).to_be_disabled()
    field.fill("")
    expect(page.get_by_text("数值输入未完成", exact=True)).to_be_visible()
    page.get_by_role("button", name="重新载入最新版本", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
    expect(field).to_have_value("")
    field.press("Escape")
    page.get_by_role("button", name="添加家具", exact=True).click()
    expect(page.locator('[data-testid^="furniture-"]')).to_have_count(3)
    page.get_by_role("button", name="删除家具", exact=True).click()
    expect(page.locator('[data-testid^="furniture-"]')).to_have_count(2)
    expect(page.get_by_role("button", name="保存", exact=True)).to_be_disabled()
    assert head(page) == original


@pytest.mark.parametrize(
    "width,height,name", [(1440, 960, "desktop"), (390, 844, "mobile"), (360, 640, "compact")]
)
def test_responsive_visuals(workbench, width, height, name):
    page = workbench
    page.set_viewport_size({"width": width, "height": height})
    surface = page.locator("svg.plan-surface")
    expect(surface).to_be_visible()
    assert surface.bounding_box()["height"] > 200
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.get_by_test_id("furniture-sofa-1").bounding_box()["width"] > 40
    image_dir = ROOT / "artifacts/e2e"
    image_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(image_dir / f"stage-2-{name}.png"), full_page=True)
    if width < 900:
        page.get_by_test_id("furniture-sofa-1").click()
        page.get_by_role("button", name="属性", exact=True).click()
        expect(page.get_by_role("spinbutton", name="X", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        edit_number(page, "X", 1550.125)
        expect(page.get_by_text("几何校验通过", exact=True)).to_be_visible()
        page.screenshot(path=str(image_dir / f"stage-2-{name}-properties.png"), full_page=True)
        save(page)
        assert head(page)["model"]["furniture_instances"][0]["transform"]["x"] == 1550.125
