# 阶段 4：位图导入与人工校核规格

状态：**实施中**

## 目标

把一张带有户型线稿、文字标注和门窗符号的平面位图，转换成可审查的
`SpatialModel v2` 草稿。识别器只产生候选几何和证据；只有用户在 2D 工作台
明确确认后，模型才可以进入阶段 3 的 3D 渲染或阶段 5 的精确布局。

首期输入只支持 **PNG 和 JPEG/JPG**。PDF、CAD/DXF/IFC、手机照片中的透视
校正、斜墙和自由多边形不属于本阶段；这些输入必须给出可解释的“不支持”结果，
不能静默转换成正交模型。

## 生命周期与事实边界

```text
原始位图（immutable asset）
  -> 解码/预处理 artifact
  -> 墙、房间、门窗、尺寸候选
  -> draft SpatialModel（含 provenance/confidence）
  -> 2D 工作台人工修正
  -> confirmed revision
  -> 阶段 3 3D / 阶段 5 布局
```

原始文件以 SHA-256 寻址并永久保留，预处理图和识别结果均为派生 artifact。
任何候选或修正都不得覆盖原始文件，也不得直接修改既有 revision。确认或修正
必须通过现有 revision/CAS 保存接口生成新 revision。

草稿必须使用 `status=draft`，且 `source.kind=bitmap`。识别器不得把置信度、
默认墙厚、默认层高或 OCR 结果伪装成测量事实；不确定值必须在对象上标出来源、
置信度和需要人工处理的原因。

## 输入契约

### 文件与像素

- 允许 MIME：`image/png`、`image/jpeg`；扩展名不能覆盖实际 MIME。
- 上传后先验证文件签名、解码、像素宽高和完整读取，再计算内容 hash。
- 首期建议硬上限：文件 20 MiB，单边 12,000 px，总像素 50 MP；超过上限返回
  `input_too_large`，不自动降采样后继续识别。
- 原始像素坐标原点在左上，`u` 向右、`v` 向下；保留 EXIF 原始信息，但按 EXIF
  Orientation 生成一个规范化预处理图并在 manifest 记录变换。
- PNG 的透明通道合成固定白色背景；JPEG 按 sRGB 解码。原图不做覆盖式增强。

### 预处理输出

预处理阶段输出 `preprocessed.png` 和 `preprocess-manifest.json`，至少记录：

- `source_sha256`、解码器版本、原始/规范化尺寸、颜色空间和 EXIF 变换；
- 灰度化、对比度、去噪、二值化、线宽估计等参数；
- 像素到输入位图的单应/仿射变换（首期只能是平移、等比缩放和 0/90/180/270
  度旋转；透视照片校正进入后续阶段）；
- 规范化 artifact 的 hash。相同输入和参数必须得到相同字节和 hash。

预处理不得改变模型事实。自动旋转或裁剪只能作为带证据的候选变换；若无法
判断图纸方向，保留原方向并要求人工确认。

## 尺寸、比例与坐标

所有写入 `SpatialModel` 的长度仍为 `mm`。识别器必须为每一个推断出的尺寸和
比例记录 `dimension_provenance`，并按以下优先级取值：

1. 用户在导入界面明确输入的比例尺或已知长度（最高可信）；
2. 图上可解析且与端点关联的尺寸标注（OCR + 尺寸线）；
3. 图纸明确的比例尺图例；
4. 仅有像素距离（只能作为 `pixel_measurement`，不能单独确认）。

建议的证据结构（允许作为扩展字段保存）：

```json
{
  "dimension_provenance": {
    "source": "ocr_dimension|user_scale|scale_legend|pixel_measurement",
    "source_asset_sha256": "sha256:...",
    "pixel_value": 125.0,
    "world_value_mm": 3000.0,
    "confidence": 0.93,
    "evidence_bbox": [100, 220, 80, 24],
    "needs_review": false
  }
}
```

当没有可靠比例尺时，草稿可以使用临时像素坐标，但必须将
`scale_status=unknown` 写入 ingest manifest，并阻断“确认后精确布局/3D”。
用户补充比例尺后应生成新 draft revision，不能重写旧草稿。

## 候选识别

识别流水线必须按固定顺序执行，并保存中间证据：

1. **线段提取**：从规范化图像提取长直线、线宽和端点；记录像素 bbox、方向、
   强度和算法版本。
2. **正交墙候选**：将接近水平/垂直的平行线配对为墙体中心线和厚度。首期
   只能接受与水平/垂直夹角不超过 2 度的线；超出阈值标记
   `non_orthogonal_candidate`，不得静默吸附。
3. **房间候选**：由候选墙和端点构建平面图，寻找闭合矩形；相邻且共享边界的
   房间提出 `merge_group_id` 候选。开放边界、断线、重叠和非矩形区域进入人工处理。
4. **门窗候选**：从墙体缺口、门扇弧线、窗框重复线和尺寸文字生成候选，必须
   关联 `host_wall_id`；无法关联宿主墙时保留为 orphan candidate 并阻断确认。
5. **尺寸 OCR**：识别数字、单位和尺寸线端点，做墙长/房间长宽一致性检查；
   冲突值全部保留并标记冲突，不选择一个值后丢弃其他证据。

每个候选至少包含：稳定候选 ID、类型、像素几何、映射后的 mm 几何（若有比例）、
`provenance`、`confidence`、算法/模型版本、证据 bbox 和 `needs_review`。候选
集合、警告和拒绝原因写入 `ingest-manifest.json`，再由适配器生成 `status=draft`
的 SpatialModel。

## 置信度与人工门禁

- 置信度范围为 `[0,1]`，是候选可信度而非事实正确性的保证。
- 默认 `confidence < 0.90` 的对象必须人工确认；墙、房间边界、宿主开口和比例尺
  任一低于阈值，整个草稿保持不可确认状态。
- 以下任一条件硬阻断确认：未闭合边界、非正交墙、房间重叠、开口越界或无宿主、
  尺寸冲突未解决、比例未知、重复 ID、模型 schema/引用/碰撞校验失败。
- 人工确认界面必须同时显示原图、预处理图、候选叠加层、对象来源、置信度和
  警告；用户可以移动端点、改厚度/尺寸、删除误检、补画缺失对象、指定 merge
  组和录入比例尺。
- “确认”按钮只在所有硬阻断清除、必需对象已处理且 SpatialModel 校验通过时可用。
  确认动作生成不可变 `confirmed` revision，并记录操作者、时间、输入 draft hash、
  修改摘要和审核清单。

## API 与 artifact 边界

导入任务建议拆成两个幂等步骤：

- `POST /api/ingests`：上传 PNG/JPEG，返回 `ingest_id`、原始 hash 和任务状态；
- `GET /api/ingests/{id}`：返回预处理、候选、警告和 draft model；
- `POST /api/ingests/{id}/confirm`：仅接受完整审核清单，调用现有 revision 保存
  接口生成 confirmed revision；不在请求中调用 3D 或 AI。

识别耗时任务在独立 CPU worker 执行；API 进程只负责校验、排队、状态和 artifact
  访问。任务必须带 source hash、算法版本和参数 hash，重复请求复用同一结果；失败
  要返回结构化错误并保留原始输入。

## 阶段门

### 必须通过

1. PNG/JPEG MIME、签名、尺寸和坏文件测试均有明确结果；PDF/CAD 输入被拒绝且不
   产生 draft。
2. 同一输入重复预处理/识别三次，规范化图、候选 JSON 和 ingest manifest hash 一致。
3. 固定标注 fixture 中，墙中心线中位误差 `<=2 px`、房间矩形 IoU `>=0.95`、
   门窗候选召回率 `>=0.90`；尺寸换算相对误差 `<=1%` 或绝对误差 `<=10 mm`，
   取较宽松者并保留每项证据。
4. 非正交线、断边界、冲突尺寸、orphan opening、未知比例和低置信度对象全部能
   阻断确认，并显示对象级原因。
5. 人工修改只产生新 revision；draft 未确认时无法创建精确 3D 或家具布局任务。
6. confirmed draft 进入现有阶段 3 渲染后，墙/房间/开口 ID 和来源可从 manifest
   追溯到原始位图 hash。

### 不在阶段门内

- 透视拍摄图自动矫正；
- PDF 多页/矢量语义、CAD/IFC 交换；
- 斜墙、曲墙、非矩形房间和多层模型；
- 自动家具识别与落位；家具目录匹配；
- LLM、扩散模型或照片级效果图生成。
