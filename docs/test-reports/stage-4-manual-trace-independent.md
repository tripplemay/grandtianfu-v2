# 阶段 4C1 独立验收报告

## 结论

**通过（功能验收通过，保留规格要求的硬阻断）**。

验收对象为 `/Users/yixingzhou/project/grandtianfu-v2` 当前工作区的阶段 4C1 实现。此次仅执行测试和只读代码审查，未修改产品代码。实现仍正确保留 `manual_trace_requires_topology_review`，未把人工矩形描图误宣称为已完成门窗、连通性或 merge 拓扑校核，也未解除进入 3D 的门禁。

## 执行结果

执行环境：macOS，Python 3.12.13，pytest 9.1.1，Node/npm 使用工作区现有依赖，Playwright Chromium 可用。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 全套 | `uv run pytest` | **167 passed**, 2 个依赖弃用警告 |
| Web 单测 | `cd apps/web && npm test -- --run` | **4 files, 27 tests passed** |
| Web 构建 | `cd apps/web && npm run build` | **成功**，`tsc --noEmit` 与 Vite build 均通过 |
| 指定 E2E | `uv run pytest tests/e2e/test_ingest.py -q` | **10 passed in 25.25s** |

Python 警告来自 Starlette/TestClient 对 `httpx`/AnyIO API 的弃用提示，不影响本次结果，但应在依赖升级时处理。

## 对阶段门的核验

- 自由 ROI：`SourceEditor` 支持数值输入和 SVG 拖框，整图坐标约束、正数尺寸、越界状态会禁用提交；E2E 覆盖有效/越界 ROI、候选选择、裁剪失败后错误保留。
- 失败后人工描图：裁剪 422 后原图和 ROI 状态仍保留，E2E 覆盖随后进入人工多房间描图路径。
- 多房间编辑：支持最多 64 个矩形房间、名称/类型、像素坐标编辑、添加、删除、撤销和重做；重叠、空名称、越界、未应用编辑和无效墙厚/墙高会阻止提交。
- 后端契约：`packages/ingest/ingest/tracing.py` 严格校验 bbox 整数、房间范围/重叠/数量、有限数字及正墙厚/墙高；API 测试覆盖陈旧 source hash（409）、额外字段/非法输入（422）、NaN、重叠、超量、忙锁和父源篡改。
- 共享墙与坐标：同线且端点相接或重叠的边界合并，存在空白间隙时不合并；墙和房间均使用父 ingest 的显式 `mm_per_pixel` 换算，并记录 `dimension_provenance`。
- 追溯与数据保护：trace identity 将父 ingest、父源 hash、参数和 `TRACE_VERSION` 纳入 hash；已存在 trace 返回同一结果；写入使用临时目录后原子替换，父任务原图不覆盖，派生结果继续保存整图源。
- 硬阻断：生成模型的 `ingest.hard_blockers` 明确包含 `manual_trace_requires_topology_review`，人工描图没有 openings，确认接口仍拒绝未完成拓扑审查的模型。
- 响应式/运行时：指定 E2E 覆盖 1440px 和 390px 视口、横向溢出检查、解码错误、相机固定、人工校核、保存和 3D 渲染结果。

## 剩余事项

本检查点按规格应暂停在 4C1。下一阶段仍需实现门窗、连通性和 merge 拓扑对象的编辑与可执行校核，之后才可重新评估是否解除人工描图草稿的硬阻断。
