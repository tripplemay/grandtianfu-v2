# ingest

`ingest` 是位图导入的确定性 CPU 切片。当前仅接受 PNG/JPEG：

```text
原始字节 -> 格式/尺寸校验 -> 预处理统计与线候选 -> draft SpatialModel -> 人工校核
```

输出始终为 `status=draft`，不能直接用于精确家具布局。图像边界、像素比例和暗线候选都是推断结果，均在 `ingest` 元数据中保存 `provenance` 与 `confidence`。当前 JPEG 只解析尺寸，像素候选为空，必须人工校核。

CPU worker：

```bash
PYTHONPATH=packages/spatial_core:packages/ingest \
  .venv/bin/python -m ingest.worker --input plan.png --output artifacts/ingest-1
```

输出 `draft-model.json`、`preprocess-manifest.json` 和 `ingest-manifest.json`；worker
始终以 `draft` 状态退出，重复输入和参数会得到相同 JSON 内容。
