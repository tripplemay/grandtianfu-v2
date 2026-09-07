# Stage 4C2 门窗与拓扑审核验收

日期：2026-09-07

## 实现结果

- 增加 `POST /api/ingests/{id}/topology`，以严格四字段请求从人工描图草稿派生不可变拓扑草稿。
- 门窗开口显式记录宿主墙、类型、偏移、宽度、高度和底标高；检查墙体范围、标高、同墙重叠、有限数与额外字段。
- Merge 组显式选择房间；只接受几何上存在共享边界或已审核宿主开口的相邻房间，禁止凭空连接分离房间。
- 派生模型保留父 source/hash、parent ingest、人工拓扑 provenance、审核 evidence 与原有 `manual_trace_requires_topology_review` 阻断。
- 前端增加桌面/移动端拓扑审核视图，所有审核对象可见；确认和 3D 仍保持禁用。

## 回归证据

- Python：`177 passed`。
- 前端 Vitest：`29 passed`；TypeScript/Vite build 通过。
- 浏览器 E2E：`10 passed`，包含 1440px 和 390px 的人工描图后拓扑提交、开口与 merge 组、幂等后端及确认/3D 门禁。
- `uv run ruff check apps/api packages/ingest/ingest packages/ingest/tests tests/e2e` 通过。
- API 专项：覆盖幂等、陈旧 source hash、非法几何、非相邻 merge、T 形共享边界开口跨度、父工件篡改和 worker 忙。

## 阶段边界

本阶段只生成可追溯的拓扑审核草稿，不解除人工确认阻断，不进入家具布局、3D 家具落位或照片级效果图。
完全分离房间暂不支持通过 opening 直接声明连通，需未来扩展显式 `from_room_id/to_room_id` 或等价空间关系字段。

独立 evaluator 报告：`docs/test-reports/stage-4-topology-independent.md`。
