# 阶段 1 报告：Canonical SpatialModel

状态：**通过**

## 已完成

- `orthogonal_v1` profile 和 `draft/confirmed/locked` 状态校验。
- 毫米/度单位、右手坐标系和固定原点契约。
- 墙体正交轴、长度、厚度和 Z 高度校验。
- 房间矩形、四边墙覆盖、merge group 和边界墙引用校验。
- 开口宿主墙引用、墙段范围和开口高度校验。
- 家具 room/asset/attachment/provenance 引用、尺寸、旋转和房间内边界校验。
- 同房间家具 AABB 碰撞校验。
- 相机投影、尺寸、位置、look-at 和 up 向量校验。
- 跨集合全局 ID 唯一性校验。
- 规范化 JSON 的稳定 `canonical_hash()`。
- 正例 fixture 和 11 个负例/稳定性测试。

## 验证

```text
python3 -m pytest -q  -> 12 passed
python3 -m compileall -q packages/spatial_core -> passed
git diff --check -> passed
```

## 有意未包含

- 2D 编辑器和 revision 持久化服务。
- 真实多边形拓扑、斜墙、曲墙和多层空间。
- 家具求解器、3D 网格、相机投影渲染和 AI 增强。
- 生产数据库、对象存储和任务队列。

这些能力分别属于后续阶段，不能通过本阶段的模型字段校验视为已完成。

