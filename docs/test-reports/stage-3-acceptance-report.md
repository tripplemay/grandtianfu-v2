# Stage 3 CPU 3D 验收报告

验收日期：2026-09-06  
基线：`cb62d74`  
范围：API -> CPU worker -> artifact/manifest，fixture smoke，以及失败门禁。未运行长时间 Playwright。

## 结果

**CONDITIONAL**：本次验收覆盖的发布链路和三项失败门禁均通过；但此前独立复核记录的几何契约风险（房间顶面、opening instance table、near/far clipping、floor 厚度）在本基线未重新证明已修复，因此不作无条件 PASS。

## 自动化检查

- `uv run pytest -q`：`72 passed`，2 个既有依赖弃用警告。
- `uv run ruff check apps/api packages/scene3d`：通过。
- `uv run python -m scene3d.worker --help`：worker CLI 可用。

## 关键 smoke 与失败门禁

使用 `confirmed-orthogonal-merge.json`，通过独立 subprocess 调用 `scene3d.worker`：

| 场景 | 结果 |
| --- | --- |
| confirmed + perspective fixture，64x48 | exit 0；写出 `manifest.json` 与四个通道文件 |
| `status=draft` | exit 3；`render requires a confirmed or locked model revision` |
| `asset_ref.kind=external` / missing ref | exit 3；`unsupported furniture asset kind for 'sofa-1'` |
| `camera.projection=orthographic` | exit 3；`cameras[0].projection must be 'perspective' in orthogonal_v1` |

API `render_revision` 对后三种输入均将 worker 错误转换为 `RenderUnavailable`，没有发布 manifest。API 缓存篡改探针先成功渲染，再将 `color.png` 改写为 `b"corrupt"` 后重复同一请求；请求返回 200 且 artifact 被重新生成，恢复原 `artifact_hash`，证明缓存命中会校验文件完整性。

## 剩余风险 / 放行条件

以下项目来自前一轮独立报告，当前 commit 只包含三项 blocker 修复，未观察到对应几何实现或 golden tests：

- ceiling 仍可能使用跨房间全局 `max_top`，而规格要求按 room/merge group 计算。
- opening 仍以 mask 0 表示且不进入 `instance_table`，与规格的 opening 实例映射存在冲突。
- near/far 面元目前按整三角形跳过，尚未证明满足裁剪规则。
- floor box 的 Z 范围为 `[0,1]`，需确认是否允许偏离规格定义的 `z=0` 地面。

在补充上述几何验收或由规格明确这些实现限制前，建议保持 **CONDITIONAL**；不影响本轮已验证的 worker/API 发布链路和失败门禁结论。
