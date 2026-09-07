# 阶段 4 集成检查点

日期：2026-09-07。分支：`feat/stage-4-bitmap-ingest`，PR #3。

**本轮集成闭环独立验收 PASS；完整阶段 4 PARTIAL。等待用户确认，未进入阶段 5。**

## 已交付

- 真实 PNG/JPEG 完整像素解码、EXIF 与颜色/alpha 规范化；移除整图边框充当户型的占位逻辑。
- OpenCV 墙线/墙带、双轮廓、矩形房间、共享墙和有宿主的未分类缺口候选。
- 显式比例尺，带来源/置信度的像素到 mm 换算；可选 Tesseract 数字 bbox 证据，不自动选尺寸。
- 独立 CPU worker，完整 artifact hash、参数版本幂等、单机跨进程锁、超时与失败输入保留。
- 上传预览、原图/规范化/候选叠加、既有数值编辑、开口类型人工分类和显式相机。
- 草稿自动进入工作台不可变版本库；逐对象和四项审核、服务端 CAS、来源/比例不可伪造。
- 确认后对象标记已审核但不抬高识别置信度；再次编辑必须重新审核，旧 revision 不覆盖。
- confirmed + 显式相机接入 CPU 3D，render manifest 追溯原图 hash 和审核所依据的草稿 hash。

## 验证与独立性

- 最终 `uv run pytest -q`：146 passed，2 个现有 Starlette 依赖弃用警告。
- `npm --prefix apps/web test`：21 passed；TypeScript/Vite build 通过。
- 最终 `uv run pytest tests/e2e -q`：13 passed，包含原工作台 9 项及新增导入 4 项。
- Ruff（API、ingest、新增 E2E、样例生成脚本）及 `git diff --check` 通过。
- 桌面 1440px / 移动 390px：实际源图加载、叠加、审核和 3D 截图，无横向溢出；canvas 采样验证渲染非空。
- 识别单测包含 5 张显式标注的合成线稿：中心线误差 <=2 px、矩形 IoU >=0.95、
  已标注缺口召回 >=0.90、尺寸误差 <=max(1%,10 mm)。这不是门窗分类精度，也不是实际户型泛化评测。
- 独立 evaluator 使用隔离上下文，报告原样保留于
  `docs/test-reports/stage-4-integration-independent.md`。其全量快照为 144 项；
  随后的两项损坏 manifest 测试使最终数目为 146。不能把多轮测试数相加。

本轮修复了厚正交墙被 Hough 误判为斜线、形态学偶数核导致端点偏移、
提前 EOI 的坏 JPEG 被容错接受、确认后 needs_review 标志不一致等实际问题。

## 用户真实图片复现

对用户提供的 3000 x 3499 JPEG（未提交到仓库）复现了原始失败。Pillow 解码正常，
失败根因是尺寸标注/页面线条被错误配对为 124/147 px 伪墙，导致 `no_closed_rectangle`。
收紧平行线配对后可生成草稿，但当前只得到右侧局部候选（1 room / 4 walls / 1 opening），
并保留 31 条未归属结构线。系统写入 `partial_plan_requires_manual_trace` 硬阻断，
前后端都不允许确认。这修复了错误拒绝，不等同于完成该真实四房户型的全图解析。

## 手工复现

按 README 构建并启动工作台。导入 `examples/synthetic-room.png`，比例填写 `10 mm/px`。
候选房间应约为 `(420,320,3160,2360) mm`，墙厚 50 mm，不是图片外框。
逐对象核验、保存修改并审核；需要 3D 时显式录入相机。详细步骤见 `examples/README.md`。
该样例是合成图，不是工程测量数据。

本机本轮验收地址：`http://127.0.0.1:8034`。数据/图片/截图均留在被忽略的本地目录，
没有旧项目运行时依赖，没有生产资产迁移或部署。

## 下一检查点仍属于阶段 4

1. 建立真实授权户型标注集与可重复质量/资源报告，再冻结可接受的输入范围。
2. 尺寸线端点关联、多 OCR 尺寸一致性与冲突处理；图上两点已知长度标定。
3. 实际门窗符号候选分类及召回评测，复杂断线/局部不支持区域的可交互修复。

完整未完成项见 `docs/specs/stage-4-integration.md`。未实现认证授权、持久任务队列、
生产审计或照片级 AI 增强；本机自报 reviewer 不能替代生产身份。不得据本轮 PASS 提前进入家具布局。
