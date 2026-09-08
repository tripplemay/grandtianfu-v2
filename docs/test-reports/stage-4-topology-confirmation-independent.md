# 阶段 4C3 拓扑确认独立验收

## 结论

**PASS**

验收基线为提交 `4c8983a`（`feat: add verified topology confirmation gate`）。本次在 fresh evaluator context 中执行，未修改产品代码；仅新增本报告。

## 自动化回归

| 命令 | 结果 |
|---|---|
| `uv run --frozen pytest -q` | **PASS**：193 passed，2 个已知 deprecation warnings，21.49s |
| `cd apps/web && npm test && npm run build` | **PASS**：Vitest 5 files / 31 tests passed；`tsc --noEmit` 及 Vite production build 成功（1843 modules） |
| `uv run ruff check apps/api packages/ingest/ingest packages/ingest/tests tests/e2e` | **PASS**：All checks passed |
| `uv run --frozen pytest -q tests/e2e/test_ingest.py` | **PASS**：10 passed，29.81s |

## 4C3 契约核查

- **原始 manual trace 不能确认**：trace 仍保留 `manual_trace_requires_topology_review` blocker；确认路径仅在服务端验证并重放 `manual_topology` recipe 后解除该单一 blocker。原始 trace 没有可用 topology reference，不能进入确认。
- **唯一 blocker / 完整拓扑证据**：确认 proof 的 `resolved_blocker_codes` 精确为 `['manual_trace_requires_topology_review']`，并记录 `topology_ingest_id`、topology model hash、parent ingest/model/source hash、geometry hash 与 `scope=traced_regions`；额外 blocker 会拒绝。
- **对象、merge、topology、coverage 全量检查**：确认要求 `scale`、`geometry`、`openings`、`heights`、`topology`、`coverage` 六项均为严格布尔 `true`；审核集合精确覆盖当前 rooms/walls/openings 以及 merge group，缺失、重复、未知 ID 均拒绝。
- **分类与几何一致性**：房间 `kind=unknown`、非法 opening kind（仅允许 `door/window/passage`）、当前几何与 topology reference 不一致均拒绝；replay 输出必须与已存 topology 工件 canonical hash 相等。
- **证据完整性与防伪**：父 trace model/source hash、source provenance、父工件内容被篡改，或伪造 review 字段均不能绕过校验；失败不追加 revision。测试覆盖 parent hash/source tamper、replay mismatch、forged review、stale hash/CAS、geometry mutation、unclassified room、非法 opening kind。
- **历史与确认后行为**：确认生成新的 `confirmed` revision；原始 source/ingest、历史 revision 和 calibration evidence 保持不变；确认后的显式 camera revision 可进入 CPU 3D render。保存为 draft 会移除 review，恢复 draft 状态并使 3D render 重新被拒绝；随后再次确认使用新 CAS。

## 浏览器与产物核查

已检查 `artifacts/stage4-confirmation-e2e/`：

- `confirmed-1440.png`（1440x960）：确认后的工作台、`v3 · 已确认`、对象属性与 3D 结果均可见，无明显遮挡。
- `confirmed-390.png`（390x844）：移动端确认工作台完整显示，底部导航和 3D 结果可见，无横向溢出或重叠。
- `shell-1440.png`（720x361）与 `shell-390.png`（358x270）：确认流程生成的 3D 图像非空，均可见墙体、房间体块和开口。

四张 PNG 均为有效 RGB 图像；确认前未渲染、确认后渲染成功的行为由 API/e2e 断言覆盖。

## 残余风险

本次未发现阻断项。Vitest/pytest 输出仅包含依赖弃用警告，不影响 4C3 验收结论。
