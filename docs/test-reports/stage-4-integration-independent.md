# 阶段 4 位图导入集成独立验收报告

验收对象：`feat/stage-4-bitmap-ingest` 相对 `ae7cc62` 的当前工作树增量

验收身份：独立 Evaluator；本报告只写验收产物，未修改产品代码、锁文件或其他报告。

## 结论

- **当前集成交付闭环：PASS（限定在 integration spec 的范围）**。在声明的 uv 环境中，位图签名/解码、显式比例、EXIF/透明白底规范化、CPU worker、不可变 artifact、工作台候选叠加、CAS 修订、逐对象人工确认和确认后 CPU 3D 均可复现。
- **完整阶段 4 指标：PARTIAL，不得标记为完整 PASS**。真实标注数据集精度门、尺寸线端点关联/冲突处理、门窗符号分类召回率、复杂断线修复和资源预算没有证据，且代码明确把 OCR 作为未关联证据、把墙缺口作为未分类通道候选。

## 实测证据

环境：`uv sync --frozen --extra dev --extra api`；Python 3.12.13；OpenCV 4.14.0；Playwright Chromium。`uv run pytest -q`：**144 passed**，2 个依赖弃用警告；`uv run pytest tests/e2e -q`：**13 passed**。E2E 覆盖 1440px 和 390px 视口、截图、叠加层、坏图、人工校核、相机、确认、CPU 3D 非空像素和无横向溢出。

关键反例/验证：

1. 未填写 `mm_per_pixel`、错误 MIME/签名、坏 PNG/JPEG、截断 JPEG、超限尺寸会拒绝且不创建 draft；同一源文件不同比例产生不同 ingest identity。
2. `GET /api/ingests/{id}` 和 artifact 路由读取前校验全部四类 artifact 及 hash；破坏 `preprocessed.png` 返回 `500 storage_integrity_error`，没有把损坏缓存当成功或自动覆盖。
3. 普通 `/api/models/{id}/revisions` 的 bitmap `confirm` 被拒绝；篡改 `source`、`ingest`/比例、缺对象、非布尔审核项、CAS 过期均拒绝。源与校准证据的不可变约束位于 `apps/api/revisions.py:293-297`。
4. 独立 confirm 记录 `source_sha256`、draft revision/hash、审核对象集合、四项检查、时间和本地自报 reviewer；确认后 revision 可进入 render，render manifest 保留 source/review 追溯信息。

## 重要实现核对

- Pillow 完整解码、EXIF orientation 变换、ICC/sRGB 和 alpha 白底位于 `packages/ingest/ingest/bitmap.py:94-166`；预处理 manifest 记录源 hash、像素尺寸、颜色/变换、阈值和算法版本（`bitmap.py:326-332`）。
- 候选均带 source hash、provenance、confidence、needs_review 和 evidence bbox；墙高/开口高明确为 `default_unmeasured`（`bitmap.py:377-428`）。
- 非正交线、无闭合矩形和重叠候选拒绝而不静默补图（`bitmap.py:271-323`）。OCR 明确为 `ocr_dimension_unassociated`，不自动选比例（`bitmap.py:338-365`）。
- 工作台显示原图/规范化图/候选叠加，审核列表显示对象来源和置信度（`apps/web/src/IngestWorkbench.tsx:190-248,357-403`）；导入 warning 在属性面板显示（`apps/web/src/App.tsx:1552-1575`）。
- bitmap 保存/确认使用追加 revision；确认后仅清除本 revision 的 `needs_review`，不提升历史 confidence，且重新保存会回到 draft（`apps/api/revisions.py:303-320`）。

## 完整阶段门未覆盖/未通过项

1. 当前 fixture 是合成矩形，不是阶段规格要求的固定真实标注户型数据集；没有墙中心线中位误差、房间 IoU、门窗召回率和尺寸误差的真实数据报告。因此不能据 144 个测试 PASS 声称完整精度指标达标。
2. OCR 只有带 bbox/confidence 的数字证据，没有尺寸线端点关联，也没有多尺寸冲突保留/一致性求解；这与 `docs/specs/stage-4-integration.md` 的未完成项一致。
3. 缺口始终生成 `passage`/`wall_gap_unclassified` 候选，自动门/窗识别和对应召回率尚未实现；人工可以在工作台分类后再保存。
4. 复杂断线/局部不支持区域不是可交互修复流，而是拒绝并要求修图后重新导入；透视照片、PDF/CAD/IFC、斜墙和自由多边形也仍在范围外。
5. worker 是单机 `flock` 单任务、无持久队列/取消/作业查询；120 秒超时和失败证据已验证，但没有阶段完整资源预算或压力/Soak 证据。

## 支持环境外观察（不计入 v2 阶段结论）

直接使用系统 Python 3.9.6（OpenCV 5.0.0）时，API 因 `datetime.UTC`/PEP604 注解不能收集，ingest 因 OpenCV Hough 返回二维 shape 触发 `bitmap.py:274` 的索引错误。v2 `pyproject.toml` 明确要求 Python `>=3.12`，故该观察不是 v2 声明支持环境的验收失败；它仅说明不能用旧项目 Python 3.9 命令替代 `uv run` 验收。

**最终判定：当前集成闭环 PASS；完整阶段 4 PARTIAL。**
