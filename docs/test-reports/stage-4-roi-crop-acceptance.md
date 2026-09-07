# Stage 4 ROI 裁剪闭环验收

日期：2026-09-07

## 结果

ROI 人工选择、派生 ingest、工件追溯和 UI 门禁通过；真实宣传页的完整墙体解析仍保持安全阻断。

## 证据

- `uv run --frozen pytest -q`：155 passed。
- `apps/web` Vitest：24 passed；TypeScript/Vite build 通过。
- `tests/e2e/test_ingest.py`：6 passed，覆盖桌面/390px、候选选择、失败提示、成功派生草稿、
  原图回放和 crop 后规范化图。
- 真实图片 `/tmp/real-plan.jpeg`：父 ingest 稳定生成候选
  `[409, 1337, 2171, 1655]`；该 bbox 触发 `overlapping_room_candidates` 时返回 422，
  父 artifact 未覆盖，错误可重现。
- 真实图片使用较窄的人工 bbox 可生成新 ingest；新 ingest identity、父源 hash、ROI bbox
  和父坐标映射均可验证，陈旧父 hash 返回 409。

## 门禁

- 自动候选不进入 `rooms/walls/openings`，不能绕过人工确认。
- 父 ingest 与原始 source 不可变；crop 结果使用新 identity，重复请求幂等。
- source/preprocessed/manifest/model hash 完整性校验失败时拒绝继续。
- 真实图片无法安全解析时保留硬阻断，不宣称已完成完整户型拓扑。

## 未完成

当前没有自由手工 bbox/trace 编辑器；下一阶段需要支持在候选失败时细化 ROI，并继续多房间墙图解析。
