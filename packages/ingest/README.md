# ingest

`ingest` 是受限正交线稿的 CPU 导入器，接收 PNG/JPEG：

```text
原始字节 -> Pillow 完整解码/EXIF/白底合成 -> OpenCV 墙线/矩形/缺口候选
        -> 带证据的 draft SpatialModel -> 人工校核
```

输出始终为 `status=draft` 且 `requires_human_review=true`，不生成相机，也不能
直接用于精确家具布局。没有显式、有限且大于零的 `mm_per_pixel` 时失败；不会
再把图像边界当房间，也不会默认每像素等于 10 mm。

规范化图左上角是模型原点：`x=u*mm_per_pixel`、`y=v*mm_per_pixel`，EXIF 1-8
方向变换和原始尺寸均保存在 manifest。PNG 透明像素合成到白色，嵌入 ICC 转换到
sRGB，没有 ICC 时显式记录 `untagged_assumed_srgb`。文件限制为 20 MiB、单边
12,000 px、总像素 50 MP，并在完整解码前检查。JPEG 另用隔离的 OpenCV/libjpeg
解码检查可恢复损坏警告，拒绝提前结束的像素流。

OpenCV 固定阈值和方向形态学提取实际长墙线，支持厚实线、成对轮廓线和多个
闭合矩形。受限间断线产生宿主明确的 `passage` 候选，不声称能分类门和窗；墙高
2,800 mm 和开口高 2,100 mm 都明确标记为 `default_unmeasured`。空白、缺少整条
边界、长斜墙、不支持的重叠几何均失败，不产生替代模型。

Tesseract 是可选系统组件：从 TSV 保留数字、置信度和 bbox，不自动关联尺寸线
端点、不由 OCR 改比例。缺少工具、超时或失败都有明确警告。照片透视纠正、
曲墙、任意多边形、门窗符号分类和完整尺寸 OCR 不在当前识别能力内。

CPU worker：

```bash
PYTHONPATH=packages/spatial_core:packages/ingest \
  .venv/bin/python -m ingest.worker --input plan.png --output artifacts/ingest-1 \
  --mm-per-pixel 10 --filename plan.png
```

输出 `source.png|jpg`、`preprocessed.png`、`draft-model.json`、
`preprocess-manifest.json` 和 `ingest-manifest.json`。`files` 映射和四类
`artifact_hashes` 均经过发布前校验，manifest 不包含自身 hash。发布失败会恢复旧
完整目录；原始文件保持字节不变。

`ingest_key(data, mm_per_pixel)` 同时覆盖原始 hash、比例、算法版本、Pillow、
OpenCV、NumPy 和可选 OCR 版本。文件显示名仅进入 ingest manifest，不进入模型
和模型 hash。重复输入、参数和运行时得到相同模型与 artifact 字节。API 负责
worker 的 120 秒超时、排队和并发限制，worker 不直接承担 HTTP 请求。

测试中固定标注的 5 张合成偏移/缩放/不同线宽/缺口线稿分别验证墙中心线中位
误差不超过 2 px、矩形 IoU 不低于 0.95、已标注缺口召回不低于 0.9 和 mm 换算
误差。另测多房间、成对轮廓、EXIF、透明 PNG、完整 JPEG、损坏和原子发布。
这些指标仅代表受控合成 fixture，不代表真实复杂户型图的泛化准确率。
