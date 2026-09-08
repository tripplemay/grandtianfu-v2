# 阶段 4E-1：真实授权户型图数据集基线

状态：实现中，当前处于数据采集准备；仓库内 manifest 仍为空，未宣称真实准确率。

## 边界

阶段 4E-0 冻结了单张标注格式和房间 IoU 评测。本阶段只建立一批经过授权、可
复现、可审计的真实样本及其预测基线，不修改识别算法，不把人工标注写回
`SpatialModel`，也不把旧仓库的测试产物迁入新系统。

数据集 manifest 使用 `stage-4e-dataset-v1`，每条记录包含：

- `source.path`、源文件 SHA-256 和像素尺寸；
- `annotation.path`、标注文件 SHA-256；
- `annotation.review_status`；正式基线必须有外部标识形式的 `annotator` 和
  `reviewer`，不把姓名或联系方式写入仓库；
- `authorization.status=authorized` 和外部审计编号；
- `provenance.source`，用于区分授权上传、公开许可等来源；
- 可选 `prediction.path` 及 ingest draft 的 SHA-256；
- `split=baseline|holdout`。

路径只能相对于外置数据根目录，禁止绝对路径和父目录穿越。程序会完整解码
PNG/JPEG，核对源图字节哈希、像素尺寸、标注源哈希和标注像素尺寸，再允许
进入评测。同一源图 SHA-256 只能出现一次，避免不同缩放、ROI 或算法运行被
误计为多个样本；`dataset_manifest_hash` 为规范化 manifest 提供稳定身份。
任何不一致均失败，不返回部分指标。

## 数据采集要求

首批建议至少覆盖：清晰 CAD/线稿、带标题栏的宣传页、断线/门洞、共享墙和
多房间布局。每张图由第二名审核者确认房间矩形、墙中心线、开口宿主和像素坐标。
授权凭证保存在外部审计系统；仓库只记录不可反推个人身份的编号。

## 阶段门

1. 至少一条 `authorized` 记录通过源图/标注哈希和像素尺寸校验；
2. 每条记录有可复现的 draft prediction artifact；
3. `evaluate_dataset` 能输出固定的按房间聚合指标，并保留逐样本结果；
4. 完成真实基线报告后，才进入 4E-2 算法改进。当前空 manifest 只能表示
   `intake_pending`，不能通过本阶段门。
