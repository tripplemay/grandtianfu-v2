# 阶段 4 ROI 候选检查点

日期：2026-09-07。独立报告：`docs/test-reports/stage-4-roi-independent.md`；裁剪闭环验收：`docs/test-reports/stage-4-roi-crop-acceptance.md`。

**ROI 候选与人工裁剪闭环：PASS（有界）；完整阶段 4：PARTIAL。**

## 已完成

- 从整张宣传页的正交线形态学连通组件提出最多 8 个 `floorplan_roi` 候选。
- 每个候选保存 bbox、暗像素/线像素比例、长线交叉数、算法参数、稳定 rank、来源 hash、
  `confidence<0.90`、`needs_review=true` 和 `selection=manual_crop_or_trace`。
- 候选只存在于 preprocessing/evidence，不进入 rooms/walls/openings，不消除
  `partial_plan_requires_manual_trace`。
- 用户图片三次复现稳定得到 bbox `[409,1337,2171,1655]`，模型仍为 1 room / 4 walls /
  1 opening，31 条未归属结构线继续阻断确认。
- 合成单 ROI、双 ROI 和原有完整回归通过；最终 Python 测试 150 项，Ruff 通过。
- 新增严格的 `POST /api/ingests/{ingest_id}/crop`：请求必须包含父源 hash 与规范化像素 bbox，
  CPU worker 原子生成新的 ingest identity；重复请求幂等，父 ingest 不可变。
- crop 的 source 保留父原图，preprocessed 保存裁剪图；墙体、房间、候选证据、OCR/线段 bbox
  映射回父坐标，并记录 parent ingest、父/裁剪 hash、候选评分和人工动作。
- 工作台支持候选列表、原图坐标、叠加框、处理中/失败状态和派生草稿追溯；未选择候选时确认仍禁用。
- 后端 155 项、前端 24 项、浏览器 E2E 6 项通过，包含桌面/移动端、失败和成功裁剪路径。

## 尚未完成

- 没有 `roi_required` 专用错误契约，也没有标注 ROI IoU `>=0.90` 的正式数据集门禁。
- 候选生成仍是启发式证据提取；用户真实图片的首选候选在裁剪后可能触发
  `overlapping_room_candidates` 并返回 422。系统保留父图与证据，不生成不可信几何，
  但尚未提供自由手工 bbox/trace 编辑器来继续处理该情况。

因此本检查点解决“宣传页先提出可审查区域候选并生成可追溯派生 ingest”，不解决整张真实四房户型的房间拓扑解析，
不允许进入家具布局或照片级生成。下一步需实现自由 ROI/trace 编辑与多房间墙图解析。
