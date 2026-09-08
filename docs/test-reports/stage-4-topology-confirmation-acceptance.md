# Stage 4C3 实现与回归记录

日期：2026-09-08。

## 验收状态

独立 evaluator fresh context 复验结论：**PASS**。报告见
`docs/test-reports/stage-4-topology-confirmation-independent.md`。

## 本轮交付

- 复用现有确认接口，验证原始 topology 工件、父 trace/source/model hash 并重放 recipe 后生成服务端确认依据。
- 原始阻断、source、ingest 和历史 revision 不改写。新 confirmed revision 的 review 记录被解除的单一 blocker、父/拓扑/几何 hash、审核检查项、审阅者和时间。
- 审核对象包含所有房间、墙、开口及 merge 组；拓扑、覆盖范围需额外明确确认。范围固定为人工描绘区域，不是自动全屋认证。
- 未分类对象、未完成拓扑、额外 blocker、缺漏审核、陈旧 revision/hash、父工件篡改、修改几何后复用旧证据被拒绝。
- 相机可单独保存。保存后撤销 review，恢复 draft；必须再次审核才能渲染。确认之后固定相机 CPU 3D 沿用现有渲染链路。

## 开发回归

- `uv run --frozen pytest -q`：193 passed，2 个第三方弃用 warning。
- `npm test`（apps/web）：31 passed；`npm run build` 通过。
- `uv run ruff check apps/api packages/ingest/ingest packages/ingest/tests tests/e2e`：通过。
- `uv run --frozen pytest -q tests/e2e/test_ingest.py`：10 passed。
- 桌面 1440px 与移动端 390px 完成手工描图、拓扑、相机保存、全量人工确认、CPU 3D；像素色数检查通过，页面无横向溢出。
- 渲染与页面截图位于忽略目录 `artifacts/stage4-confirmation-e2e/`。

## 不扩大范围

仍未交付自动全屋识别精度门、尺寸线自动关联、家具求解和照片级增强。当前只是人工描绘区域的工程模型确认闭环。几何改变后须重新生成拓扑证据，不能把原始审核直接迁移到新几何。
