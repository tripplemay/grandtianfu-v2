# Grandtianfu v2

生产级家装空间系统的全新实现。

## 产品契约

系统的唯一事实源是版本化的 `SpatialModel`，而不是 prompt、轴测图或某一张效果图：

```text
位图/PDF/CAD/扫描
  -> 结构化平面模型（含置信度和来源）
  -> 可编辑 3D 场景
  -> 家具精确落位与几何验收
  -> 确定性渲染
  -> 受控 AI 外观增强
```

LLM 不拥有精确家具位置的最终决定权。几何由场景模型和渲染器负责，AI 只在深度、法线、分割 mask 等受控输入下增强材质、灯光和照片质感。

## 仓库边界

- `packages/spatial_core`: Canonical Spatial Model v2、单位、版本和确定性校验。
- `packages/scene3d`: 3D 场景适配器、相机、深度/mask 输出和确定性渲染。
- `packages/ingest`: Pillow 完整解码、OpenCV 正交线稿候选、Tesseract 数字证据和独立 CPU draft worker。
- `apps/api`: 本地 2D 工作台 API、SQLite 不可变版本、几何校验和并发保存保护。
- `apps/web`: 位图/候选叠加、2D 编辑、逐对象人工校核、历史版本与 CPU 3D 通道预览。

旧仓库 `grandtianfu` 只作为只读的失败案例、评测样本和需求参考，不作为 v2 的运行时依赖，也不迁移旧产物。

## 当前状态

阶段 0/1/2/3 已完成并通过验收；阶段 4 的“真实像素识别 + 人工校核”集成检查点已通过独立验收。完整阶段 4 仍为 PARTIAL，不进入阶段 5。当前停下等待用户确认，结果见 [`集成报告`](docs/stages/stage-4-integration-report.md)。

当前识别范围是清晰、轴对齐的矩形线稿，支持共享边界和墙带缺口候选。导入必须显式填写 `mm/px`，不猜比例、层高或相机。墙高/洞高草稿暂用带 `default_unmeasured` 来源的值，必须人工核验。OCR 只收集数字证据，尚不关联尺寸端点；缺口默认是未分类 `passage`，须人工改为实际门/窗/通道。真实复杂户型准确率尚未建立。

真实宣传页或多房间图如果留下未归属结构线，会生成局部候选并标记
`partial_plan_requires_manual_trace`；确认按钮和服务端审核都会阻断，不能把局部矩形当作全屋模型。

本阶段仅用于本机开发验收，未实现生产认证授权。现有几何校验不等于完整工程验收：merge 连通拓扑、家具与墙厚碰撞、三维净空及门洞通行约束仍需后续补齐。

完整路线见 [`docs/roadmap.md`](docs/roadmap.md)。

## 本地运行

要求 Python 3.12+、Node 22.12+、uv。先构建前端，再启动同源 API/静态文件服务：

```bash
uv sync --frozen --extra dev --extra api
npm --prefix apps/web ci
npm --prefix apps/web run build
uv run uvicorn apps.api.app:app --host 127.0.0.1 --port 8026
```

打开 `http://127.0.0.1:8026`。首次启动只插入本仓手工样例；后续启动保留 `data/workbench.sqlite3`，不会从 fixture 覆盖已有版本。可用 `GT_DB_PATH` 指定独立数据库。没有旧仓运行时依赖，无 API 密钥要求。

数字 OCR 可选依赖系统 `tesseract`（英语数字模型）；macOS 可用 `brew install tesseract`，Ubuntu 可用 `sudo apt-get install tesseract-ocr`。缺失或超时会显示证据不可用警告，不自动推导比例。`GT_INGEST_ROOT` 指定导入证据目录，默认 `artifacts/ingests`；成功产物按源 hash、显式比例和运行时版本组合寻址，失败输入保留在 `rejected/`，损坏缓存明确报错，不覆盖原证据。

校核与接口说明见 [`docs/specs/stage-4-integration.md`](docs/specs/stage-4-integration.md)。

## 验证

```bash
uv run pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
uv run playwright install chromium
uv run pytest tests/e2e -q
```

浏览器测试每个用例创建临时数据库和独立端口，退出后关闭进程，不写入本地工作台数据库。桌面/移动端截图输出到被忽略的 `artifacts/e2e/`。GitHub Actions 执行这些检查，不执行部署。
