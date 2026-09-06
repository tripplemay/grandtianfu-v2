# SpatialModel v2 规格（阶段 0 冻结版）

## 目标

定义一个与 UI、CAD、渲染器、LLM provider 无关的空间事实源。所有派生文件必须能够通过 `model_version` 和对象 ID 回溯到该事实源。

首期 profile 固定为 `orthogonal_v1`：只接受正交墙体、矩形房间和 merge 房间。斜墙、曲墙、自由多边形和多层模型属于后续 profile；导入时必须标记为超范围并进入人工处理，不能静默近似为正交几何。位图识别结果只能作为带置信度的 draft，必须人工确认后才能形成可用于精确布局的 revision。

## 单位和坐标

- 内部长度单位：毫米（`mm`）。
- 世界坐标：右手系，`X` 向东，`Y` 向南，`Z` 向上。
- 角度单位：度；绕 `Z` 轴为平面旋转。
- 所有外部单位必须在 ingest 边界显式转换并记录来源。

## 顶层结构

```json
{
  "schema_version": "2.0",
  "profile": "orthogonal_v1",
  "model_id": "...",
  "revision": 1,
  "status": "draft",
  "units": {"length": "mm", "angle": "deg"},
  "coordinates": {"origin": "project_south_west_corner", "handedness": "right"},
  "source": {"asset_id": "...", "kind": "bitmap", "sha256": "...", "provenance": "user_upload"},
  "confidence": 0.0,
  "rooms": [],
  "walls": [],
  "openings": [],
  "furniture_instances": [],
  "cameras": [],
  "materials": []
}
```

`status` 只能取 `draft`、`confirmed`、`locked`。只有 `confirmed` 或 `locked` revision 才能进入精确家具布局；revision 不可变，任何修正都创建新 revision。模型 hash 由规范化 JSON（UTF-8、排序 key、无空白）计算，派生物必须记录该 hash。

## 对象要求

### 墙体

`orthogonal_v1` 墙体使用水平或垂直实体轮廓，并包含厚度、底标高、顶标高和来源置信度。模型字段应为可扩展结构，后续 profile 才能加入任意多边形；业务代码不得把 AABB 当作所有未来 profile 的长期契约。

### 房间

房间引用边界对象，不能只保存一个矩形。房间必须有稳定 ID、名称、用途和可见性关系。

首期房间边界由正交墙体围合；merge group 使用稳定的 `merge_group_id`，组内房间允许共享开放边界，但不得存在重复或断开的边界。

### 开口

门、窗、洞口必须引用宿主墙体，并包含平面位置、宽度、高度、底标高、开启方向（适用时）和类型。

`host_wall_id` 不存在、开口越过宿主墙体范围或开口自身非正值均为硬失败。

### 家具实例

每件家具必须包含：

- `instance_id`：稳定实例 ID。
- `catalog_id`：目录或真实 SKU 引用。
- `transform`：世界坐标位置和旋转。
- `dimensions`：宽、深、高。
- `room_id`：逻辑归属。
- `attachment`：自由放置、贴墙或固定结构。
- `asset_ref`：参数模型或 3D 网格引用。
- `provenance`、`confidence`：来源和可信度。

`attachment` 首期取 `free`、`wall`、`fixed`；`asset_ref` 必须能解析到参数模型或网格资产。家具的 `room_id` 必须引用有效房间。

### 相机

相机必须包含 `projection`（首期为 `perspective`）、`image_size`、`position`、`look_at` 和 `up`。坐标使用同一世界坐标系，图像尺寸为像素。缺少必要参数的相机不能用于渲染。

### 材质

材质至少包含稳定 ID、颜色/纹理来源和 `provenance`。材质是外观数据，不得隐式改变墙体或家具几何。

## 派生物规则

- 2D 平面、CAD/DXF/IFC、glTF/USD、深度图、mask 和渲染图均从 `SpatialModel` 生成。
- 派生物不得回写核心坐标。
- 自动纠偏必须生成新 revision 或明确的 solver proposal，禁止静默修改。
- 每次渲染必须记录模型 revision、相机 revision、资产 hash 和渲染参数。

## 验证门

提交模型前必须通过：

1. 拓扑闭合和对象引用校验。
2. 单位、正值和有限数校验。
3. 墙体、开口和家具的碰撞/越界校验。
4. 门洞、通道和家具净空校验。
5. 3D 场景生成和相机投影 smoke test。

## 首期容差提案

以下阈值用于阶段门的第一版自动验收，实际渲染器确定后可以通过 ADR 调整，但不能无记录地放宽：

- 平面模型序列化/反序列化：坐标误差 `0mm`，稳定 hash 不变。
- 确定性 3D 投影：同一输入重复运行像素差为 `0`；几何测试投影误差不超过 `0.5px`。
- 家具实例 mask：基础渲染与期望投影的 IoU 不低于 `0.95`。
- 几何安全：穿墙、越界、阻门、无效引用为硬失败，不允许以 warning 交付。
- CPU worker：首期单房间 P95 和内存预算在渲染器 spike 后冻结，并记录在选型 ADR。
