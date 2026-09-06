# v2 工程规则

- `SpatialModel` 是唯一空间事实源；2D、CAD、3D、prompt、渲染图均为派生物。
- 任何自动推断必须记录 `provenance` 和 `confidence`，不得把默认值伪装成测量值。
- 精确模式下，LLM 不得直接修改家具位置、尺寸、旋转、墙体和门窗。
- 先完成可验证的单房间垂直切片，再扩展导入、多房间和全屋能力。
- 旧仓库仅用于只读参考，不建立运行时依赖，不复制旧的 relational/softref/geometry-lock 主流程。

