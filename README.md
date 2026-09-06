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
- `packages/ingest`: PNG/JPEG 位图导入、预处理候选和 draft worker；OCR/CV 与人工确认仍在后续阶段。
- `apps/api`: 本地 2D 工作台 API、SQLite 不可变版本、几何校验和并发保存保护。
- `apps/web`: 2D 平面编辑、人工确认和历史版本工作台；3D 预览后续实现。

旧仓库 `grandtianfu` 只作为只读的失败案例、评测样本和需求参考，不作为 v2 的运行时依赖，也不迁移旧产物。

## 当前状态

阶段 0/1/2/3 已完成并通过验收；阶段 4 的首个 PNG/JPEG bounded slice 已实现，等待独立验收和用户确认。每阶段完成后等待用户确认，不自动进入下一阶段。

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

## 验证

```bash
uv run pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
uv run playwright install chromium
uv run pytest tests/e2e -q
```

浏览器测试每个用例创建临时数据库和独立端口，退出后关闭进程，不写入本地工作台数据库。桌面/移动端截图输出到被忽略的 `artifacts/e2e/`。GitHub Actions 执行这些检查，不执行部署。
