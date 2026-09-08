# 阶段 4D 多房间位图候选识别独立验收

验收日期：2026-09-08  
工作目录：`/Users/yixingzhou/project/grandtianfu-v2`  
范围：当前工作树阶段 4D 改动；未修改产品代码，仅新增本报告。目标仓库不存在 `CLAUDE.md`，已按现有 `AGENTS.md`、阶段规格和当前 diff 继续验收。

## 最新结论

**PASS（修复后复验）**。

首轮验收曾判定 FAIL：`ingest.candidates` 中的 `kind=room` 条目错误继承了 `opencv_line_candidate` / `confidence=0.8`。当前修复已让 room candidate 继承 `face_source`；复验确认顶层对象和 candidates 清单均使用 `provenance=roi_structural_component`、`confidence=0.45`、`needs_review=true`。多房间输出、人工描图阻断、确定性和模型校验均满足本阶段范围。

## 命令摘要

| 检查 | 结果 |
|---|---|
| `uv run --frozen pytest -q packages/ingest/tests/test_bitmap.py` | **PASS：50 passed** |
| `uv run --frozen pytest -q` | **PASS：194 passed**，2 个第三方弃用 warning |
| `uv run ruff check packages/ingest/ingest/bitmap.py packages/ingest/tests/test_bitmap.py` | **PASS：All checks passed** |
| `uv run python` 直接 ingest 用户 JPEG，`mm_per_pixel=1.1`（修复后复验） | **PASS**：11 个 room、44 个 wall；`room_detection.mode=roi_structural_components`；`room_candidate_count=11` |
| 同一 JPEG 重复 ingest 两次 | **PASS**：两次 canonical hash 均为 `d10195ab9667473b836c43ca386352dd996e3b6561040119c953c42bfc5478b5` |
| 两次结果执行 `validate_model` | **PASS** |
| 临时 API `127.0.0.1:18765` 上传 JPEG（首轮修复前探针） | **PASS（HTTP）**：201；worker 工件和 manifest 正常写出；候选 provenance 缺口已在直接 ingest 修复后复验 |

## 直接 ingest 证据

- 输入：`/Users/yixingzhou/project/grandtianfu/7aa30e0b95c37aadd4d234f2b5d5a571.jpeg`，源 SHA-256 为 `73185950d40aff1683b28182f83cbfc2ad219d7307cb0b9c3a90ede3666fe7bf`。
- 输出 11 个 room 候选；每个顶层 `model.rooms[]` 和 `ingest.candidates[kind=room]` 的 `provenance=roi_structural_component`、`confidence=0.45`、`needs_review=true`。
- 每个顶层 `model.walls[]` 和 `ingest.candidates[kind=wall]` 同样为 `roi_structural_component`、`confidence=0.45`、`needs_review=true`。
- `ingest.hard_blockers` 保留 `partial_plan_requires_manual_trace`（count 35）；没有绕过人工描图阻断。

修复后两次 canonical hash 均为 `d10195ab9667473b836c43ca386352dd996e3b6561040119c953c42bfc5478b5`，且两次 `validate_model` 均通过。

HTTP 探针已在首轮失败版本上确认 API -> worker -> manifest 发布链路返回 201；本轮未重新启动临时端口，修复后的候选字段以同一 worker 调用的直接 ingest 结果核对，避免将修复前 manifest 误作修复后证据。

## 首轮失败记录（已修复）

`packages/ingest/ingest/bitmap.py` 的 room candidate 写入调用没有传递 `face_source`，因此候选列表中的 room 条目回退到 `source_ref`：

```text
kind=room
provenance=opencv_line_candidate
confidence=0.8
needs_review=true
```

同一问题经临时 HTTP worker 的 `manifest.candidates` 复现；例如首轮 `room-candidate-1` 在 manifest 中为 `opencv_line_candidate` / `0.8`，虽然对应的 `model.rooms[0]` 已是 `roi_structural_component` / `0.45`。这曾使对外的候选清单违反阶段规格的统一证据契约；当前修复已通过直接 ingest 的 candidates evidence 检查，且全量回归仍通过。

## 放行边界

本次 PASS 仅覆盖阶段 4D 候选识别验收；`partial_plan_requires_manual_trace`、低置信度和人工 review gate 仍必须保留，不能将候选几何视为已确认拓扑或直接进入精确布局/渲染。
