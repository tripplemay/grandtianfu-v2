# 阶段 3：CPU 3D 场景垂直切片规格

状态：**规格冻结，待实现**。本文件定义契约，不代表 3D 渲染已经完成。

## 目标

把已经人工确认的 `SpatialModel v2`（`profile=orthogonal_v1`）确定性地展开为室内 3D 场景，并在固定相机下输出：

- `color.png`：基础颜色图；
- `depth.f32le`：线性深度通道；
- `normal.f32le`：世界坐标法线通道；
- `instance-mask.u32le`：实例 ID 通道；
- `render-manifest.json`：模型、相机、资产、渲染参数和像素实例映射。

阶段 3 只证明：

```text
confirmed SpatialModel -> 确定性建筑/家具几何 -> 固定相机投影 -> 四类通道
```

同一输入不得发生坐标漂移、隐式布局改变或不可复现输出。基础渲染是后续 AI 增强的几何事实基准。

## 范围与前置条件

### 允许

- 正交水平/垂直墙体和矩形房间；
- 使用 `merge_group_id` 表示的开放式相邻房间；
- 墙体厚度、底/顶标高；
- 门、窗、洞口和 passage 开口；
- `asset_ref.kind=parametric` 的参数化家具简模；
- 已存在的 `perspective` 相机和显式 CPU 渲染配置。

### 前置条件

1. 模型 `status` 必须是 `confirmed` 或 `locked`；`draft` 硬失败。
2. 模型必须通过阶段 1/2 的 schema、引用、正交范围、边界和 2D 保存校验。
3. 墙、开口和家具实例必须有稳定 ID；家具 `asset_ref` 必须可解析，或明确进入 preview-only 降级状态。
4. 相机 `position`、`look_at`、`up`、`image_size` 必须有限且有效；缺失时不得猜测视角。

### 不在本阶段

- 位图/PDF/CAD 识别、尺寸 OCR；
- 自动家具布局、自动纠偏、墙面吸附或 solver；
- 实拍照片标定、照片合成和背景替换；
- LLM、扩散模型、VLM 或任何随机 AI 调用；
- 斜墙、曲墙、自由多边形、多层建筑；
- 网络家具模型、网络纹理和真实资产搜索；
- 通过 prompt、颜色盒或自然语言修改几何。

## 坐标和变换契约

### Canonical 世界坐标

内部长度单位为 `mm`，角度单位为 `deg`。世界坐标是右手系：

```text
X：向东（east）
Y：向南（south）
Z：向上（up）
```

因此 `X × Y = Z`。原点沿用 `SpatialModel.coordinates.origin`（首期为项目西南角），不得由渲染器重新居中后写回模型。渲染器内部坐标必须通过显式 adapter 与该坐标系互转，并在 manifest 记录 adapter 名称和版本。

### 平面图与 3D 的关系

2D 平面直接使用 `(u, v) = (x, y)`：SVG 的 `u` 向右、`v` 向下，对应世界 `X` 向东、`Y` 向南；**2D 到 3D 不对 Y 取负**。世界 `Z` 只用于 3D 高度。

如果底层 renderer 采用不同 up 轴或图像坐标，必须在边界 adapter 显式转换；canonical 模型、2D 编辑器和 manifest 仍保持上述约定。交换轴时必须同时记录手性变化并有 round-trip 测试。

### 家具变换

沿用阶段 2 契约：家具 `transform.x/y` 是**旋转后平面 footprint 的最小角**，不是中心点；`rotation_z` 是绕世界 Z 轴的平面旋转。

给定目录尺寸 `width × depth × height`：

- `0/180` 度 footprint 为 `width × depth`；
- `90/270` 度 footprint 为 `depth × width`；
- footprint 中心为 `(x + footprint_width/2, y + footprint_depth/2)`；
- 参数模型以 footprint 中心为 XY 原点、底面为局部 Z=0，实例底面高度为 `transform.z`，模型中心 Z 为 `transform.z + height/2`。

adapter 只能把最小角转换为 renderer 所需的中心/矩阵表示，转换结果必须可逆验证；不得改变家具尺寸、旋转或位置。

## 场景几何

### 墙体

对 `Wall(axis, x, y, length, thickness, bottom_z, top_z)` 生成实体长方体：

- `axis=h`：中心线从 `(x,y)` 沿 `+X` 延伸；XY 范围为 `[x,x+length] × [y-thickness/2,y+thickness/2]`；
- `axis=v`：中心线从 `(x,y)` 沿 `+Y` 延伸；XY 范围为 `[x-thickness/2,x+thickness/2] × [y,y+length]`；
- Z 范围为 `[bottom_z, top_z]`；
- 实例 ID 为 `wall:{wall_id}`。

厚度、标高和长度均来自模型。越界、非正值或 `top_z <= bottom_z` 硬失败。

### 开口

开口引用 `host_wall_id`，沿宿主墙轴向偏移：

- 水平墙起点为 `(wall.x + opening.offset, wall.y)`；
- 垂直墙起点为 `(wall.x, wall.y + opening.offset)`；
- 宽度沿墙轴向，高度沿 Z，底标高为 `opening.bottom_z`。

renderer 必须将墙体切分为侧柱、下槛和过梁等实体，使开口成为真实空洞；绘制白色矩形不算实现。开口越过宿主长度或垂直范围、悬空引用和非正值硬失败。实例 ID 为 `opening:{opening_id}`。首期不强制生成门扇、窗框和开启动画，但不得以它们填回净空。

### 地面、顶面和 merge 房间

- 地面位于 `z=0`，由房间矩形生成；同一 `merge_group_id` 内相邻矩形做确定性矩形 union，避免重叠面和 z-fighting；
- merge union 只删除开放的内部隔断，不删除仍存在且未被 passage/opening 穿透的实体墙；
- 顶面位于该房间/merge 组边界墙的最大 `top_z`；无法得到明确顶标高时硬失败，不采用隐式 2700mm 默认；
- 房间 ID 和 merge group 保留为面元 metadata，即使地面已 union；
- 技术默认材质只能进入 manifest（`provenance=renderer_default`），不得回写 `SpatialModel`。

### 参数化家具

第一版至少实现 `sofa`、`coffee_table`、`bed` 和 generic box 四类 deterministic primitive。primitive 的细节和材质不影响几何验收；家具实例 ID 必须随所有网格面和输出 mask 传播。

无法解析的 `asset_ref`：精确渲染硬失败；preview-only 可以输出 placeholder，但 manifest 必须标记 `degraded=true`，不得作为阶段门通过。

## 固定相机和像素投影

### 相机有效性

阶段 3 只支持 `projection=perspective`。观察方向非零，`up` 非零且不与观察方向平行。图像尺寸来自 `camera.image_size`，单位为像素。

相机内参不能隐式猜测。垂直视场角、near/far 和颜色管理属于显式 `render_profile`；首期 profile 暂定：

```json
{
  "id": "cpu-perspective-v1",
  "vertical_fov_deg": 50,
  "near_mm": 10,
  "far_mm": 100000,
  "pixel_center": "(width-1)/2,(height-1)/2",
  "color_space": "sRGB"
}
```

profile 必须完整写入 manifest；调整必须通过 ADR，不能在代码中偷偷改默认值。

### 投影公式

令 `f = normalize(look_at-position)`，并使用：

```text
right = normalize(f × up)
camera_up = normalize(right × f)
q = p - camera.position
x_cam = dot(q, right)
y_cam = dot(q, camera_up)
z_cam = dot(q, f)
fy = H / (2 * tan(deg_to_rad(vertical_fov_deg) / 2))
fx = fy * W / H
u = cx + fx * x_cam / z_cam
v = cy - fy * y_cam / z_cam
```

`(u,v)` 是左上角原点、向右/向下为正的像素坐标。`v` 的负号只负责把相机“向上为正”转换为图像“向下为正”，不是对 canonical 平面 Y 取反。

`z_cam <= near_mm` 或 `z_cam >= far_mm` 的面元按裁剪规则处理。相机不得为了“看全”自动移动、改 FOV 或改变图像尺寸。选定基准点的投影误差目标为 `<=0.5px`。

## 输出通道格式

所有通道尺寸为 `W=camera.image_size.width`、`H=camera.image_size.height`，行优先、从上到下，像素中心与投影公式一致。

### `color.png`

RGBA 8-bit、sRGB，使用固定颜色管理、抗锯齿和背景色。验收 hash 使用解码后的 canonical RGBA 字节，避免 PNG metadata 影响。

### `depth.f32le`

每像素一个 little-endian IEEE-754 float32；数值为沿 `f` 的正向 camera-space 深度，单位 `mm`，不是非线性 z-buffer，也不是欧氏距离。没有命中几何体的像素写 `0.0`，并在 manifest 标记 `invalid_value=0`。

### `normal.f32le`

每像素三个 little-endian float32，按 `Nx,Ny,Nz` 行优先；法线为 canonical 世界坐标中的单位向量，背景写 `(0,0,0)`。可视化 PNG 必须从该原始通道派生。

### `instance-mask.u32le`

每像素一个 little-endian unsigned 32-bit 整数；`0` 为背景。非零值通过 manifest `instance_table` 映射到 `room:{id}`、`wall:{id}`、`opening:{id}`、`furniture:{id}`。不使用 8-bit 调色板作为真源，避免实例数超过 255 时碰撞。

## Manifest 与确定性

每次渲染输出 `render-manifest.json`，至少包括：

```json
{
  "schema_version": "3.0",
  "model_id": "...",
  "model_revision": 1,
  "model_hash": "sha256:...",
  "camera_id": "...",
  "camera_hash": "sha256:...",
  "render_profile": "cpu-perspective-v1",
  "renderer": {"name": "...", "version": "...", "adapter": "..."},
  "asset_hashes": {},
  "image_size": {"width": 800, "height": 600},
  "channels": {},
  "instance_table": {},
  "geometry_checks": {},
  "determinism": {"seed": 0, "threads": 1},
  "artifact_hashes": {}
}
```

确定性要求：固定 renderer/version/profile、seed、线程、抗锯齿和颜色管理；不得读取当前时间、随机数、网络资产或未锁定文件。相同模型 revision、相机、资产 hash 和 profile 重复运行，canonical 通道字节和 manifest hash 必须一致。任何资产缺失、线程/版本不一致或通道尺寸不一致均失败。

## CPU worker 约束

### 部署模型

- 3D 渲染在独立 CPU worker 执行，不在 API 请求进程内执行；
- 默认单任务单进程；并发通过增加 worker 数量实现；
- 不要求 GPU、CUDA、Metal 或浏览器 WebGL；
- 任务带 model revision、camera revision、asset hash 和 render profile，重试不得修改模型。

### 首期预算

针对单房间、最多 100 个家具实例、最大输出 2048×2048：

- 默认验收输出 1024×768；CPU P95 `<=30s`；
- 单任务硬超时 `120s`；
- worker 峰值 RSS `<=2GB`；
- 单 worker 同时只运行 1 个渲染任务；
- 超出范围必须返回可解释失败，不自动降采样或删家具。

spike 需记录 CPU 型号、核数、线程、内存、输入规模、P50/P95、峰值 RSS 和失败率；最终预算只能通过 renderer 选型 ADR 冻结。

## 阶段门

### 硬性阻断

- `draft`、非法引用、非正交墙、开口越界、无效相机、缺失资产、墙/地/顶构建失败；
- 家具穿墙、越界或与开口净空冲突；
- 通道尺寸、dtype、单位、instance ID 表不一致；
- renderer 自动改动模型坐标、尺寸、旋转、相机或删除实例；
- 同一输入重复渲染产生不同 canonical 通道 hash。

### 可量化验收

1. 固定 fixture 的 2D→3D 变换 round-trip 坐标误差 `0mm`。
2. 基准点 3D→像素投影误差 `<=0.5px`。
3. 每件家具有非空 instance mask，实例表无丢失或碰撞。
4. 可见几何的 depth 顺序与测试场景预期一致，背景深度为 `0.0`。
5. 相同输入重复运行至少 3 次，所有 canonical 通道和总 hash 相同。
6. 在预算硬件上记录 P50/P95、RSS、超时和失败状态。
7. 用固定单房间/merge fixture 生成四类通道、manifest、截图和几何检查报告。

阶段门通过后，才允许进入阶段 4/5 的导入和家具布局；此前不得接入位图识别、自动布局或 AI 写实增强。
