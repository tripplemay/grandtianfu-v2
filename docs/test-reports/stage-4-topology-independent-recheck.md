# 阶段 4C2 独立复验报告

## 结论

**通过（修复后复验）**。本报告仅记录独立复验，不修改产品实现。复验范围覆盖后端拓扑约束、前端门窗编辑与证据展示、桌面/390px 浏览器流程，以及真实宣传页的初始阻断。

## 证据

- `uv run --frozen pytest -q`：177 passed，2 个依赖弃用 warning。
- `npm test -- --run`：5 个 test files / 29 tests passed。
- `npm run build`：TypeScript 检查与 Vite production build 通过。
- `uv run ruff check apps/api packages/ingest/ingest packages/ingest/tests apps/api/tests tests/e2e`：通过。
- `uv run --frozen pytest -q tests/e2e/test_ingest.py`：10 passed。拓扑编辑场景由同一测试以 `1440px` 和 `390px` 两个 viewport 参数化执行，包含添加、编辑、提交 opening、merge 组证据和确认/3D 阻断断言。

## 专项核查

### Opening 编辑与稳定 ID

通过。UI 使用 opening 自身 `id` 作为行 key；编辑时回填原对象，保存修改保留原 ID，不因 offset/width 等字段变化重新生成 ID。E2E 已实际添加 opening、进入编辑、修改宽度并提交，后端返回 `manual_topology` opening。

### Merge 证据

通过（修复后）。前端 `sharedWallEvidence` 按墙轴、房间矩形的实际共同区间过滤共享墙，并只展示 opening 与该共同区间相交的证据。E2E 断言合并组显示“共享墙”。

### Opening 与共同边界相交反例

通过。T 形房间 API 反例使用同一共享墙上、但落在两房间共同区间之外的 opening（offset 0、width 50），返回 `422 invalid_topology: opening 'outside' does not intersect the shared boundary`；将 opening 移入共同区间（offset 120、width 100）返回 `201`。因此墙体内但不属于两房间共同边界的 opening 不会被错误接受为 merge 证据。

### 幂等、完整性与阻断

通过。相同拓扑输入返回稳定 ingest ID；父 source 篡改返回 500；陈旧 source hash、未知对象、越界/重叠 opening、非邻接 merge 和 worker busy 均有拒绝路径。派生模型保留 `manual_trace_requires_topology_review`，确认版本与 3D 继续阻断。

### 真实宣传页

通过。使用 `/Users/yixingzhou/project/grandtianfu/7aa30e0b95c37aadd4d234f2b5d5a571.jpeg` 导入：API 返回 201，模型含 `partial_plan_requires_manual_trace` hard blocker；浏览器导入后“生成 3D”保持 disabled，源图审核区域显示待人工状态。系统没有将宣传页误判为可确认模型。

## 残余说明

官方拓扑 E2E 已覆盖 390px 交互且通过；该测试的横向溢出断言位于进入拓扑编辑器之前，未单独断言提交后的拓扑长列表 `scrollWidth`。当前 CSS 使用移动端两列/换行布局，未观察到运行时失败；建议后续回归补充提交后 `document.documentElement.scrollWidth <= innerWidth` 断言。

