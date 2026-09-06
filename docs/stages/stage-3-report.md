# 阶段 3：CPU 3D 场景垂直切片报告

状态：**独立验收通过，等待用户确认**

## 已交付

- `scene3d` 标准库 CPU 光栅器：正交墙体、真实门窗墙洞、房间地面、实体顶面、参数化家具盒体。
- 固定 `cpu-perspective-v1` 相机：透视投影、50° FOV、near 10mm、far 100000mm，世界坐标 `X=east,Y=south,Z=up`。
- 独立 `scene3d.worker` 进程入口，JSON 输入、稳定退出码和 120 秒 API 超时边界。
- API `POST /api/models/{model_id}/renders`：只允许 confirmed/locked revision，输出目录按 model/revision/hash 幂等寻址。
- 工作台“生成 3D”入口，展示当前确认版本的基础颜色图；原始通道仍通过 artifact URL 保留。
- 输出 `color.png`（RGBA）、`depth.f32le`、`normal.f32le`、`instance-mask.u32le`、`manifest.json` 和 `render-manifest.json`。

## 阶段门证据

- `uv run pytest -q`：74 passed。
- `uv run ruff check apps/api apps/api/tests packages/scene3d packages/scene3d/tests`：通过。
- fixture `confirmed-orthogonal-merge` 800×600 smoke：两个家具均有非空、正宽高的唯一 mask；四类通道 hash 已写入 manifest。
- 同一 fixture、同一尺寸重复渲染：四类通道 hash 和 manifest 完全一致。
- draft、缺失相机、空墙体/房间、越界数值和 worker 输入错误均硬失败；原有完整产物不会被失败任务替换。
- 独立验收报告：`docs/test-reports/stage-3-acceptance-report.md`，最终结论 PASS。

## 明确边界

本阶段仍是几何可信的基础渲染，不包含位图/PDF 识别、自动家具布局、真实家具资产、照片级增强或 LLM。渲染器故意使用参数化盒体，不能作为最终实拍效果图；后续阶段必须以这些原始通道和 manifest 作为几何事实源。
