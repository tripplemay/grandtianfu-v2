# 旧仓库参考清单

旧仓库路径：`/Users/yixingzhou/project/grandtianfu`。

## 只读参考

- `docs/AIGC链路核查-带评论效果图根因-20260717.md`：历史错位案例和失败模式。
- `docs/3D模型引导-出图质变评估-20260717.md`：现有数据和 L1 简模可行性评估。
- `docs/test-reports/route-eval-real-render-2026-07-23.md`：不同实拍路线的对照基线。
- `packages/floorplan_core/floorplan_core/geometry.py`：墙、房间、开口派生算法参考。
- `packages/floorplan_core/floorplan_core/catalog.py`：家具类型和 2D 外形元数据参考。

## 不迁移的内容

- 旧项目/方案/照片/标定和 renders 数据。
- `relational`、`softref`、`geometry_lock` 作为 v2 主流程。
- `placement_brief` 作为精确布局协议。
- `axon.py` 作为生产 3D 引擎。

## 可提取为测试样本

旧仓库中的输入几何和家具数据可在离线脚本中转换为 v2 fixture，但每个转换字段必须标记 `provenance=legacy_import`，缺失高度、材质或网格时标记为 `inferred` 或 `unknown`。

