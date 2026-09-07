# 阶段 4 ROI 候选检查点

日期：2026-09-07。独立报告：`docs/test-reports/stage-4-roi-independent.md`。

**ROI 候选生成：PASS（有界）；完整 ROI 检查点：PARTIAL；完整阶段 4：PARTIAL。**

## 已完成

- 从整张宣传页的正交线形态学连通组件提出最多 8 个 `floorplan_roi` 候选。
- 每个候选保存 bbox、暗像素/线像素比例、长线交叉数、算法参数、稳定 rank、来源 hash、
  `confidence<0.90`、`needs_review=true` 和 `selection=manual_crop_or_trace`。
- 候选只存在于 preprocessing/evidence，不进入 rooms/walls/openings，不消除
  `partial_plan_requires_manual_trace`。
- 用户图片三次复现稳定得到 bbox `[409,1337,2171,1655]`，模型仍为 1 room / 4 walls /
  1 opening，31 条未归属结构线继续阻断确认。
- 合成单 ROI、双 ROI 和原有完整回归通过；最终 Python 测试 150 项，Ruff 通过。

## 尚未完成

- 没有人工 ROI 选择/裁剪 API 或工作台交互。
- 选定 ROI 尚未生成新的 ingest identity、crop artifact、坐标回映射和操作者动作记录。
- 当前候选计算后仍由整图识别器生成几何；ROI 外线尚未真正从识别输入中过滤。
- 没有 `roi_required` 专用错误契约，也没有标注 ROI IoU `>=0.90` 的正式数据集门禁。

因此本检查点只解决“宣传页先提出可审查区域候选”，不解决整张真实四房户型的房间拓扑解析，
不允许进入家具布局或照片级生成。下一步需先实现人工裁剪闭环，再接入多房间墙图解析。
