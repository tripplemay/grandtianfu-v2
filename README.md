# Grandtianfu v2

生产级家装空间系统的全新实现。

## 产品契约

系统的唯一事实源是版本化的 `SpatialModel`，而不是 prompt、轴测图或某一张效果图：

```text
位图/PDF/CAD/扫描
  -> 结构化平面模型（含置信度和来源）
  -> 可编辑 3D 场景
  -> 家具精确落位与几何验收
  -> 确定性渲染
  -> 受控 AI 外观增强
```

LLM 不拥有精确家具位置的最终决定权。几何由场景模型和渲染器负责，AI 只在深度、法线、分割 mask 等受控输入下增强材质、灯光和照片质感。

## 仓库边界

- `packages/spatial_core`: Canonical Spatial Model v2、单位、版本和确定性校验。
- `packages/scene3d`: 3D 场景适配器、相机、深度/mask 输出和确定性渲染（后续实现）。
- `apps/ingest`: 位图、PDF、CAD 和扫描数据的导入、解析、人工校核任务（后续实现）。
- `apps/api`: 面向产品的 API 编排层（后续实现）。
- `apps/web`: 2D 校核、3D 预览和审批工作台（后续实现）。

旧仓库 `grandtianfu` 只作为只读的失败案例、评测样本和需求参考，不作为 v2 的运行时依赖，也不迁移旧产物。

## 当前状态

阶段 0 的文档基线已完成：首期范围、空间模型契约、验收标准和阶段门已冻结。`spatial_core` 当前仍是最小校验基线，下一阶段实现完整事实源和版本校验；3D、位图解析和 AI 增强必须等待对应阶段门通过。

完整路线见 [`docs/roadmap.md`](docs/roadmap.md)。

## 本地验证

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e 'packages/spatial_core[dev]'
pytest
```
