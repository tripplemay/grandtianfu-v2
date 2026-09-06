# scene3d

Stage 3 CPU-only 3D 垂直切片。实现是纯 Python 标准库软件光栅器，故意不在 API 进程中引入 Blender、GPU 或 Pillow；后续可将同一场景契约交给独立 render worker。

## 输入和坐标

输入是通过 `spatial_core.validate_model` 的 `SpatialModel v2`。只渲染 `confirmed` 或 `locked` revision，且必须提供一个显式 `cameras[0]`；`cameras=[]` 不再隐式生成相机。世界坐标保持规格定义：`X` 向东、`Y` 向南、`Z` 向上。

模型相机使用 v2 的 `projection: "perspective"` 字段；本阶段固定为 `cpu-perspective-v1`，采用 50° FOV、`near=10mm`、`far=100000mm` 的标准透视除法。参数及世界 basis 写入 manifest，保证渲染结果可复现。

## 输出

```python
from scene3d import render_model

manifest = render_model(model, "artifacts/render", width=800, height=600)
```

CPU worker 可独立运行，适合放入队列或 worker 容器；未提供 `--input` 时从 stdin 读取：

```bash
PYTHONPATH=packages/spatial_core:packages/scene3d \
  python -m scene3d.worker --input model.json --output artifacts/render \
  --width 800 --height 600
```

成功退出码为 `0` 并在 stdout 输出 manifest JSON；输入/JSON 错误退出 `2`，渲染校验错误退出 `3`，输出 I/O 错误退出 `4`。worker 不绑定端口、不读 secrets，也不提供认证。

输出目录包含：

- `color.png`：确定性 RGBA 基础渲染图（sRGB）。
- `depth.f32le`：每像素一个 little-endian float32，单位毫米，0 是背景。
- `normal.f32le`：每像素三个 little-endian float32，世界坐标 XYZ 法线。
- `instance-mask.u32le`：每像素一个 little-endian uint32，0 是背景，实例到 mask 值的映射写入 manifest。
- `manifest.json`：模型 revision/hash、相机 basis、FOV/near/far、对象 ID/角色/像素框、通道 dtype/shape 和文件 hash。

场景包含按 merge group 确定性 union 的 `z=0` 房间地面、墙体、真实墙洞、按边界墙最大标高生成的实体顶面和参数家具盒体；near/far 面采用相机空间多边形裁剪。opening 净空不覆盖像素，但保留 `opening:{id}` 的非零实例映射。家具网格和照片级材质不在本阶段范围内。

所有数值进入光栅器前都必须为有限数且绝对值不超过 `1_000_000_000`；单张输出最大 `4096x4096`。渲染先写入同级临时目录，所有 pass 和 manifest 成功后再原子发布，失败不会替换已有完整输出。

## 测试

```bash
PYTHONPATH=packages/spatial_core:packages/scene3d \
  python -m pytest packages/scene3d/tests -q
ruff check packages/scene3d
```
