# SpatialModel v2 规格草案

## 目标

定义一个与 UI、CAD、渲染器、LLM provider 无关的空间事实源。所有派生文件必须能够通过 `model_version` 和对象 ID 回溯到该事实源。

## 单位和坐标

- 内部长度单位：毫米（`mm`）。
- 世界坐标：右手系，`X` 向东，`Y` 向南，`Z` 向上。
- 角度单位：度；绕 `Z` 轴为平面旋转。
- 所有外部单位必须在 ingest 边界显式转换并记录来源。

## 顶层结构

```json
{
  "schema_version": "2.0",
  "model_id": "...",
  "revision": 1,
  "units": {"length": "mm", "angle": "deg"},
  "source": {"asset_id": "...", "kind": "bitmap", "sha256": "..."},
  "confidence": 0.0,
  "rooms": [],
  "walls": [],
  "openings": [],
  "furniture_instances": [],
  "cameras": [],
  "materials": []
}
```

## 对象要求

### 墙体

墙体使用任意多边形中心线或实体轮廓，不以 AABB 作为长期契约。必须包含厚度、底标高、顶标高和来源置信度。

### 房间

房间引用边界对象，不能只保存一个矩形。房间必须有稳定 ID、名称、用途和可见性关系。

### 开口

门、窗、洞口必须引用宿主墙体，并包含平面位置、宽度、高度、底标高、开启方向（适用时）和类型。

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

