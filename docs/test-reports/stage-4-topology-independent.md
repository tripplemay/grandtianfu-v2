# 阶段 4C2 独立验收报告

## 结论

**部分通过，不建议将 4C2 标记为完成或解除阶段门。**

本次验收以独立 evaluator 身份执行，仅读取代码、运行测试和验证运行时行为；除本报告外未修改产品代码。后端的门窗/merge 输入校验、父工件保护、幂等和硬阻断均有可复现证据，桌面与移动端主流程也可提交拓扑草稿。但规格阶段门要求 UI 支持“添加/编辑/删除门窗”并显示每个 merge 组的邻接解释，当前实现只支持新增/删除，不支持已加入开口的编辑，且只显示一条通用提示，未显示实际共享墙/开口证据。因此本阶段应保持 `building`，先补齐 UI 验收缺口和几何边界回归。

## 执行环境与命令

工作目录：`/Users/yixingzhou/project/grandtianfu-v2`。Python 3.12、uv 锁定依赖、Node/npm 工作区依赖、Playwright Chromium。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 全量 | `uv run --frozen pytest -q` | **175 passed**，2 个既有 Starlette/AnyIO 弃用警告 |
| 拓扑后端专项 | `uv run --frozen pytest -q apps/api/tests/test_ingest_topology.py packages/ingest/tests/test_topology.py` | **8 passed**，2 个同上警告 |
| Web 单测 | `cd apps/web && npm test -- --run` | **5 files, 29 tests passed** |
| Web 构建 | `cd apps/web && npm run build` | **成功**，TypeScript 与 Vite 均通过 |
| 静态检查 | `uv run ruff check apps/api packages/ingest/ingest packages/ingest/tests apps/api/tests tests/e2e` | **All checks passed** |
| 拓扑 E2E | `uv run --frozen pytest -q tests/e2e/test_ingest.py -k free_roi_failure_then_manual_multiroom_trace --tb=short` | **2 passed**，覆盖 1440px 与 390px |
| 全量 ingest E2E | `uv run --frozen pytest -q tests/e2e/test_ingest.py --tb=short` | **10 passed** |

另外用真实宣传页 JPEG（3000x3499，711 KiB，仅临时目录）执行 bitmap ingest：HTTP 201，得到 1 room/4 walls，保留 `partial_plan_requires_manual_trace`，未误报为可确认完整户型。

## 已通过的 4C2 要求

- API 路由 `/api/ingests/{ingest_id}/topology` 接受严格的 `expected_source_sha256`、`openings`、`merge_groups`、`reviewed_object_ids` 契约；未知字段、未知 room/wall、非有限数、越界开口和无效 merge 返回 422。
- 开口校验覆盖宿主墙体、水平跨度、墙高范围、正宽高、非负偏移/底标高及同墙重叠；后端不依赖前端校验。
- merge group 至少两个房间，房间不能重复归组；相邻共享墙和分离房间拒绝路径均有测试。
- 陈旧 source hash 返回 409；父 source 篡改返回 500 `storage_integrity_error`；worker 锁占用返回 503；失败路径未发布半成品。
- 相同拓扑请求返回相同 ingest identity；输出 `source.provenance=manual_topology`、`parent_ingest_id`、父 source/model hash、算法版本、动作参数和 `reviewed_object_ids`；父 trace 草稿和原始 source 未被覆盖。
- 4C1 的 `manual_trace_requires_topology_review` 被保留。拓扑输出仍有 blocker，确认和 3D 按现有 review gate 继续禁用。E2E 在拓扑提交后断言“生成 3D”仍 disabled。
- UI 能从描图草稿进入拓扑视图，选择墙体、设置门/窗/通行开口尺寸和标高、删除开口、选择至少两个房间建立 merge 组并提交；桌面/390px 移动视口均无横向溢出，提交后能看到 `manual_topology` 派生草稿。

## 未通过或风险

### P1：UI 不支持已加入开口的编辑

`apps/web/src/TopologyEditor.tsx:63-73` 对已有开口只渲染文本和删除按钮；宿主墙、类型、offset、width、height、bottom_z 只能在“新增草稿”表单修改，加入审核后无法编辑。阶段门明确要求“添加/编辑/删除门窗”，因此当前 UI 不能满足完整审核闭环。后端允许的修改也只能通过重新提交整组输入，界面没有实现该能力。

### P1：UI 没有显示实际邻接解释

`apps/web/src/TopologyEditor.tsx:75-80` 只显示通用文案“仅允许有共享边界或明确开口证据的相邻房间合并”，没有针对每个候选/已建 merge 组列出共享 wall ID、共同边界区间或对应 opening。用户无法在提交前确认为什么两个房间可连通；这直接缺少阶段门要求的“显示邻接解释”。

### P1：后端显式开口连通性未校验开口跨度与共同边界相交

`packages/ingest/ingest/topology.py:189-194` 只判断 opening 的 `host_wall_id` 是否属于两房间共享墙，未判断 opening 的 offset/width 是否落在两房间共同边界区间内。若同一长墙上开口位于共享区间之外，仍可能被当作组内连通证据。应增加“开口水平 span 与 shared boundary overlap > 0”的校验，并补一条反例测试。

### P2：本轮 E2E 对 T 形和分离房间覆盖不足

专项 API 测试覆盖了相邻矩形和一个分离房间的拒绝，但浏览器 E2E 只走两房间相邻矩形；阶段规格还要求合成相邻/T 形/分离房间及真实宣传页验收。真实宣传页本轮只验证初始 ingest 的安全阻断，未在浏览器中完成人工描图到拓扑提交的完整链路。建议补充 T 形三房间、共享边界部分重叠、开口跨界/非跨界以及真实图 UI 回归。

## 放行建议

暂不通过 4C2 阶段门，保持 `manual_trace_requires_topology_review`、确认禁用和 3D 禁用。下一次提交至少应：

1. 为每个已加入 opening 提供编辑表单，并保持删除/新增后的稳定 ID 与幂等 hash。
2. 在 merge 选择和已建组旁显示实际邻接解释（共享墙 ID/边界区间/审核 opening ID），无证据时在提交前明确阻断。
3. 后端检查显式 opening 与两房间共同边界的跨度相交，并添加对应 API 测试。
4. 增加 T 形、分离房间、非相交开口和真实宣传页的桌面/移动 E2E，再由新的独立 evaluator 复验。
