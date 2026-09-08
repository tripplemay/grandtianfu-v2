# Stage 4 ROI 检查点独立验收报告

验收日期：2026-09-07  
验收范围：当前工作树未提交的 ROI 增量（`packages/ingest/ingest/bitmap.py`、对应测试、ROI spec/ADR）  
验收身份：独立 Evaluator；本报告未修改产品代码、锁文件或已有报告。

## 结论

- **ROI 候选生成子项：PASS（有界）**。候选是 evidence，不会以 `floorplan_roi` 类型写入 `rooms`、`walls` 或 `openings`；bbox、评分、排序、`needs_review`、来源和原图 hash 可追溯且重复运行确定。
- **完整 ROI 检查点：PARTIAL**。当前只新增了候选检测和 evidence 输出；没有人工选择/裁剪接口、裁剪后重新识别、新 ingest identity、坐标回映射、操作者动作记录或结构化 `roi_required` 路径。更重要的是，候选计算后仍把整张图的 `raw` 线段送入几何识别，尚未实现 spec 所要求的“ROI 外线不进入该次几何识别”。
- **完整阶段 4：仍为 PARTIAL/不可放行**。真实标注精度、尺寸线关联与冲突处理、门窗分类召回、复杂断线修复、人工确认闭环和资源预算等既有缺口仍然存在；本检查点不能扩大原阶段结论。

## 执行环境与自动化结果

工作目录：`/Users/yixingzhou/project/grandtianfu-v2`，Python/依赖由 `uv.lock` 提供。

```text
uv run --frozen pytest -q
150 passed, 2 existing dependency deprecation warnings

uv run --frozen ruff check packages/ingest/ingest/bitmap.py packages/ingest/tests/test_bitmap.py
All checks passed!
```

## 真实图片复现

输入为 `/tmp/real-plan.jpeg`（仅读取，未复制或提交），`file` 确认为 3000x3499 JPEG；源 SHA-256 为
`73185950d40aff1683b28182f83cbfc2ad219d7307cb0b9c3a90ede3666fe7bf`。

使用 `uv run python` 调用 `ingest_bitmap(data, filename="real-plan.jpeg", mm_per_pixel=1)`，连续运行 3 次得到完全相同结果：

- `rooms=1`、`walls=4`、`openings=1`；`unassigned_lines=31`。
- 硬阻断仍为 `partial_plan_requires_manual_trace`，`count=31`；模型没有被当成可确认的完整户型。
- ROI 候选数为 1：`id=roi-candidate-1`、`rank=1`、`bbox=[409,1337,2171,1655]`、`confidence=0.627186`、`needs_review=true`、`selection=manual_crop_or_trace`、`intersecting_line_count=35`。
- `ingest.evidence.roi_candidates[0].source_asset_sha256` 与 `ingest.source_sha256` 一致；候选的 `provenance=orthogonal_line_component`、参数、暗像素/线像素比例均保留。
- 3 次规范化 JSON 的 SHA-256 均为 `74a8011987c15c18df905ddf06c1b5becabb44532d88372ffee93b53677150fa`，证明当前输入下 bbox/排序/评分和模型输出确定。

这满足“复杂真实图片不误报完整户型”的本轮反例：局部矩形虽被提出，31 条未归属结构线仍触发硬阻断。

## 合成多 ROI 复现

构造 800x500 白底图，绘制两个彼此分离的正交矩形，调用 `preprocess_bitmap(load_bitmap(...))` 3 次：每次均得到 2 个候选，分别为

```text
roi-candidate-1 rank=1 bbox=[446,96,319,309] confidence=0.547919
roi-candidate-2 rank=2 bbox=[36,56,319,389] confidence=0.537225
```

两候选均 `needs_review=true`，ID/rank/bbox 顺序稳定。随后调用完整 `ingest_bitmap`：模型中没有 `kind= floorplan_roi` 的 room/wall/opening；产生的 2 个 room 仅来自输入中实际绘制的两个闭合矩形，未发现 ROI 候选对象被直接伪造为几何事实。需要注意，这个结果同时暴露了下述过滤缺口：在没有人工选择 ROI 时，两个矩形都仍被全图识别器处理。

## 逐项核对与问题

### 已通过（有界）

1. `floorplan_roi` 只出现在 `preprocessing.roi_candidates` 和 `ingest.evidence.roi_candidates`，没有追加到顶层 `rooms`/`walls`/`openings`。
2. 候选包含 `evidence_bbox`/`pixel_geometry.bbox`、算法来源、`confidence<0.90`、`needs_review=true`、`selection=manual_crop_or_trace`、排序字段和可解释比例/相交线计数。
3. evidence 副本带 `source_asset_sha256`，与 ingest 源 hash 对齐；重复运行结果确定。
4. 真实图片的既有 `partial_plan_requires_manual_trace` 未被 ROI 候选绕过。

### 未通过或未覆盖（导致 PARTIAL）

1. **ROI 没有进入几何过滤链（重要）**：`_recognize` 在 `bitmap.py:345-346` 计算候选后，仍在 `bitmap.py:362-390` 用完整 `raw` 线段配对、闭合和生成 rooms。没有根据候选 bbox 裁剪/过滤，也没有“人工未选择时拒绝几何确认”的路径。因此 spec 不变量“ROI 外的线、文字和装饰不进入该次几何识别”尚未实现；本次双矩形复现会同时生成两个 room draft。
2. **人工操作闭环不存在**：代码库中没有 ROI 选择/裁剪 API、UI、裁剪 artifact 或操作者动作记录。`selection` 只是候选上的固定字符串，不是已发生的动作；没有重新识别时的原图坐标映射和新的 ingest identity。
3. **无稳定 ROI 的结构化结果缺失**：spec 要求 `roi_required` 并保留原图/evidence；当前无 ROI 或空白输入仍在识别层直接抛 `no_closed_rectangle`/其他 `BitmapError`，没有 ROI 专用错误契约。
4. **合成海报 IoU 门未被测试证明**：现有测试验证了候选存在、范围和双 ROI 排序，但没有标注 bbox 与候选计算 IoU `>=0.90` 的断言；因此该最小阶段门尚无证据。

## 完整阶段 4 遗留缺口

沿用上一轮 `docs/test-reports/stage-4-integration-independent.md` 的结论：没有真实授权标注集及墙/房间/门窗/尺寸精度报告；OCR 仍是未关联 evidence；墙缺口仍是未分类 passage；复杂断线、透视/PDF/CAD/IFC、人工确认闭环和资源/压力预算未完成。ROI 候选的 PASS 不能把这些缺口改判为 PASS，也不能进入阶段 5。

## 放行建议

保留当前候选 evidence 增量作为 **ROI 候选生成 PASS、完整 ROI 检查点 PARTIAL**。下一轮需先实现人工选择/裁剪及新 ingest identity/坐标映射，再将选定 bbox 接入几何识别过滤，并补充 `roi_required`、海报标注 IoU 和“ROI 外闭合装饰不生成 room”的回归测试；在此之前不得宣称 ROI 阶段门或完整 Stage 4 通过。
