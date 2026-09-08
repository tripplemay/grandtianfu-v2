# 阶段 4D 多房间位图候选识别验收记录

日期：2026-09-08  
分支：`feat/stage-4-bitmap-ingest`  
提交：`4f2c94e`

## 验收结论

阶段 4D **通过**。

用户使用真实宣传页 JPEG 在本地工作台完成导入验收，确认系统不再只生成一个房间候选。独立复验记录见 `docs/test-reports/stage-4d-multi-room-independent.md`，结论为 PASS。

## 验收证据

- 输入：3000x3499 JPEG 户型宣传页。
- CPU worker 输出：11 个房间候选、44 面墙。
- `room_detection.mode=roi_structural_components`。
- 顶层 rooms/walls 与 `ingest.candidates` 的房间/墙候选均带 `provenance=roi_structural_component`、`confidence=0.45`、`needs_review=true`。
- 重复运行结果 hash 一致，`validate_model` 通过。
- `partial_plan_requires_manual_trace` 仍保留，未绕过人工拓扑审核。
- 本地前端 `http://127.0.0.1:5176/` 与 API `http://127.0.0.1:8026/` 验收通过。

## 边界

本阶段通过的是复杂宣传页的多房间候选识别，不代表房间语义、门窗分类、尺寸关联或拓扑已自动确认。部分组件仍可能需要人工拆分或 merge，不能直接进入精确家具布局和照片级渲染。
