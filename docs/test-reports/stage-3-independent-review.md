# Stage 3 CPU 3D 独立复核

复核日期：2026-09-06  
复核基线：`df9c5db`（包含 `691644a` 及其后续 packaging/render contract 修订）  
结论：**FAIL，存在阶段门阻断项**

## 已执行验证

- `uv run pytest -q`：`71 passed`，2 个依赖弃用警告。
- `uv run ruff check apps/api packages/scene3d`：`All checks passed!`。
- 先前独立验证的前端 Vitest：`17 passed`；前端 build 成功。
- 未在本轮启动长时间 Playwright；fixture smoke 由现有 scene3d 测试覆盖。

现有测试确认了 confirmed/locked 门禁、显式相机、四个原始通道、确定性 hash、原子发布和大于 254 个 mask 值等基本路径，但没有覆盖下列契约边界。

## 阻断项

### P1：API 缓存命中不校验 artifact 文件或 hash

`apps/api/rendering.py:35-40` 只读取 `manifest.json`，并以 model hash 与尺寸匹配即直接返回；不会检查 `color.png`、`depth.f32le`、`normal.f32le`、`instance-mask.u32le` 是否存在、尺寸/dtype 是否正确或 SHA-256 是否仍与 manifest 一致。这使已损坏或缺失的发布目录被当作成功结果返回，违反阶段门的 artifact/channel/hash 完整性要求。

可复现（当前代码）：

```text
POST /api/models/fixture-living-merge-001/renders {revision:1,width:64,height:48} -> 200
将返回目录的 color.png 改写为 b"corrupt"
重复同一 POST -> 200，返回 manifest 不变，color.png 仍为 b"corrupt"
```

因此这是数据损失/错误成功，不是仅缺少观测字段。

### P1：非方形画布的 FOV 解释与冻结公式不一致

`packages/scene3d/scene3d/renderer.py:257-267` 先把 50° 当作水平视场，再按宽高比推导垂直视场。冻结规格 `docs/specs/stage-3-cpu-3d.md:127-161` 明确 50° 是 `vertical_fov_deg`，并要求 `fy = H/(2*tan(vfov/2))`、`fx = fy*W/H`。当前 320x240/800x600 等非方形输出的投影坐标因此系统性偏移，不能满足基准点 `<=0.5px` 的阶段门。

### P1：不支持的 `asset_ref` 被静默当作 generic box

`renderer.py:229-235` 对每个家具直接用 `dimensions` 生成 box，没有校验或解析 `asset_ref.kind`、资产存在性，也没有在 placeholder 情况写入 `degraded=true`。例如把 fixture 的 `asset_ref.kind` 改成 `external` 或使用不存在的引用时仍会成功。规格 `stage-3-cpu-3d.md:115-119` 要求无法解析的资产精确渲染硬失败；阶段门 `:232-238` 将非法/缺失资产列为硬阻断。当前实现会产出看似成功且带 mask 的错误几何。

## 其他契约偏差（应修复后再放行）

- `renderer.py:188-192` 使用所有墙体的全局最大 `top_z` 作为每个房间的顶面高度；规格要求按房间/merge group 的边界墙计算，异高房间会生成错误 ceiling。
- `renderer.py:224-228` 将 opening 记录为 mask 0 且不进入 `instance_table`。规格 `:179-181` 要求非零实例值可映射到 `opening:{id}`；若产品决定 void 永远不可见，应在契约中明确例外并补验收，而不是同时写入 opening metadata 却产生不可映射实例。
- `renderer.py:264-274` 只要三角形任一顶点越过 near/far 就丢弃整面，没有按规格 `:161` 实施面元裁剪；相机近平面/远平面附近会出现几何孔洞。
- `_box` 生成 floor 的 Z 范围为 `[0,1]`（`renderer.py:191`），而冻结规格 `:109` 定义地面位于 `z=0`；当前厚地板会影响近距离深度和可见面语义。

## 复核结论

基础 happy path、worker 隔离、RGBA/raw channel 文件写出、manifest 字段和确定性测试均通过；但 P1 缓存完整性、投影内参和资产引用处理直接违反冻结契约/阶段门，故本阶段不能判定 PASS。修复后至少补充：缓存目录缺文件/篡改 hash 的 API 回归测试、非方形相机投影 golden test、非法/缺失 asset_ref 的硬失败测试，以及异高房间、opening instance table 和 near-plane clipping 的几何测试。

## 第二轮复验（`06b85ca`）

复验日期：2026-09-06。当前 HEAD 为 `06b85ca`，包含针对本报告三个 P1 的修复。

- `uv run pytest -q`：`72 passed`，2 个既有依赖弃用警告。
- 定向 scene3d/API 测试：`56 passed`。
- scoped `ruff check`（本次变更涉及的 API、renderer 与测试文件）：通过。
- 缓存完整性探针：首次渲染后将 `color.png` 改写为 `b"corrupt"`，重复同一请求返回 `200`，文件被重新生成并恢复为原 artifact hash。
- 资产探针：将 fixture 家具 `asset_ref.kind` 改为 `external`、引用 `missing`，`render_model` 返回 `RenderError: unsupported furniture asset kind`。
- 垂直 FOV：实现已改为垂直 50°并按 `width / height` 推导水平角，符合冻结公式；非方形 fixture 测试通过。

本轮结论：**三个原 P1 阻断均复验通过**。原报告列出的 ceiling 按全局 `max_top`、opening mask 不进入 `instance_table`、near/far 越界整三角形丢弃、floor 使用 `[0,1]` 厚度等契约偏差本轮未见修复；若这些仍属于阶段门要求，整体 Stage 3 仍应保持 `FAIL/conditional`，不能仅因 P1 修复改判无条件 PASS。
