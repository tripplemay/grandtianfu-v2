# scene3d

3D 场景和确定性渲染子系统的占位包。

首个 spike 的输出契约：

- 固定版本的 `SpatialModel` 输入
- 相机视角下的基础渲染图
- 每个 `instance_id` 的分割 mask
- 深度图和可选法线图
- 渲染 manifest（模型、相机、资产和参数 hash）

不要把 Blender 或其他渲染器直接嵌入 API 进程；生产实现应作为独立 render worker/service。

