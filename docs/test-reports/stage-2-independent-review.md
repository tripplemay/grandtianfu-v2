# 阶段 2 独立验收报告

## 首轮（2026-09-06）

审查范围：`apps/api`、`apps/web/src`、`packages/spatial_core` 与阶段 2 e2e；未修改产品代码。

### 自动化基线

- `source .venv/bin/activate && pytest -q`：54 passed。
- `apps/web: npm test -- --run`：17 passed。
- `apps/web: npm run build`：通过。
- `pytest -q tests/e2e/test_workbench.py`：6 passed、1 failed。

### 首轮问题

1. **P1：平移连续移动会发生视口坐标漂移。**
   `PlanCanvas` 平移开始时保存 `startWorld`，但每次 `pointermove` 用已经变化过的 SVG CTM 将当前 client 坐标转换为 world，再相对初始点计算并套回初始 `viewBox`。由于 CTM 会随上一次 `setViewBox` 改变，连续移动会重复抵消/错误累计；例如同一拖动首步 10px、次步累计 20px，第二次计算会接近首步位置，而不是累计 20px。该问题只影响视口，不直接写模型，但会使缩放后画布定位错误并影响后续家具操作。复现路径与 `tests/e2e/test_workbench.py::test_drag_after_zoom_pan_undo_and_save` 一致。

2. **P1（验收阻断）：构建产物的画布按钮可访问名称与 e2e 契约不一致。**
   源码首轮使用 `Zoom in` / `Zoom out` / `Fit plan` 等英文 `aria-label`，验收测试按中文名称 `放大`、`缩小`、`适合画布` 查找，导致 e2e 在点击放大按钮处 30 秒超时。首轮 e2e 的失败证据为该 locator timeout；root 已在源码中改为中文标签，需重建 dist 后复验。

3. **P2：数值输入 Escape 不能撤销已写入的中间值。**
   首轮源码中 `NumberField` 对每个有效 `onChange` 立即调用 `onChange` 写入 timeline；Escape 处理器只恢复输入框文本，不恢复模型。由此推导从 `1500` 输入到 `1600` 后按 Escape 可能保留中间模型值、状态变为未保存。若“取消”仅指确认弹窗，该项可降级为输入交互缺陷；否则违反取消不应改变模型状态的预期。该风险首轮尚未有专门 e2e，后续已由字段事务修复并覆盖。

### 设计澄清

- 房间属性的起点 X/Y 在本阶段禁用、仅允许宽度/深度调整；root 确认这是共享拓扑限制，应在规格中显式说明，不作为本轮阻断项。
- 共享墙段覆盖多个房间侧边是阶段 1 约定，不能以“墙段必须等于单房间边界长度”判错。

## 复验

2026-09-06 root 完成平移固定初始 CTM、中文画布按钮可访问名称、字段级 Escape timeline 恢复并重建 dist 后，我独立复跑：

- `source .venv/bin/activate && pytest -q`：54 passed。
- `apps/web: npm test -- --run`：17 passed。
- `source .venv/bin/activate && ruff check apps/api tests/e2e`：通过。
- `source .venv/bin/activate && pytest -q tests/e2e/test_workbench.py`：8 passed（含初始 CTM 多步平移、无效字段、Escape 恢复、添加/删除家具和移动端流程）。

复验确认首轮 P1 平移漂移和 aria-label 阻断已修复；新增 Escape 场景通过。当前未发现可复现的阶段门阻断问题。首轮问题与证据保留，不因修复删除或软化。
