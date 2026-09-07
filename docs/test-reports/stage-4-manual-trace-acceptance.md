# Stage 4C1 自由 ROI 与人工描图验收

日期：2026-09-07

## 实现结果

- 工作台支持整图坐标 ROI 数值编辑、反向拖框、候选框修改、移动端触控拖框。
- 自动裁剪失败后可保留原图并进入人工矩形房间描图；支持名称、类型、像素小数、添加、修改、删除、撤销和重做。
- `POST /api/ingests/{id}/trace` 生成新的不可变 ingest identity；原始 source/hash 保留，房间和墙体 provenance 为 `manual_trace`。
- 相邻或重叠边界去重为共享墙；分离房间不跨空白自动合并；不推断门窗和 merge。
- 派生草稿固定 `manual_trace_requires_topology_review`，确认和 3D 仍被阻断。

## 回归证据

- Python：`167 passed`，含 trace API、幂等、陈旧 hash、额外字段、NaN/bool、房间上限、重叠、锁忙和父源篡改。
- 前端 Vitest：`27 passed`；TypeScript/Vite build 通过。
- 浏览器 E2E：`10 passed`，覆盖原有导入回归、桌面/390px 移动端、反向拖框、失败后两房间人工描图、共享墙、撤销重做、未保存离开保护、确认/3D 门禁。
- 真实宣传图：首选自动 ROI 仍可安全返回 `overlapping_room_candidates`；随后在原图上人工生成两房间草稿，父源 hash 不变、墙体去重为 5 条、硬阻断保留。
- 代码 lint：`uv run ruff check apps/api packages/ingest/ingest packages/ingest/tests tests/e2e` 通过。

## 已知限制

本阶段只完成可追溯的矩形描图和共享墙生成；门窗、连通性、merge 分组及自动全屋拓扑仍未实现，不能进入家具布局或照片级生成。

独立 evaluator agent 因本机磁盘耗尽及后续服务传输错误未能写出独立报告；上述结果是主上下文执行的回归证据，不能替代正式独立签收。提交前应重新运行独立验收并补充 `stage-4-manual-trace-independent.md`。
