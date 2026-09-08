# 阶段 4E-1 数据集入口独立验收报告

日期：2026-09-08

结论：**FAIL（阶段门阻断）**

本次为只读独立验收；除新增本报告外，未修改产品代码或测试代码，未提交。
验收前阅读了 `AGENTS.md`、`docs/specs/stage-4e-real-dataset.md`，并检查了
`packages/ingest/ingest/dataset.py`、`packages/ingest/ingest/evaluation.py`、
相关测试和 `data/datasets/stage4e-real/manifest.json`。

## 阻断项

### 1. 阶段门要求的真实授权样本尚不存在

`data/datasets/stage4e-real/manifest.json` 当前内容为：

```json
{
  "schema_version": "stage-4e-dataset-v1",
  "dataset_id": "stage4e-real-baseline-v1",
  "status": "intake_pending",
  "records": []
}
```

规格的阶段门 1 要求至少一条 `authorization.status=authorized` 的记录通过源图
和标注哈希、像素尺寸校验；阶段门 2 要求每条记录具备可复现的 draft
prediction artifact。当前没有任何记录，因此不能产生真实基线，也不能宣称阶段
4E-1 通过。该状态与目录 README 中“不能代表准确率基线”的声明一致。

这不是代码测试失败，而是交付物缺失；在首批真实授权样本、标注、复核信息和
prediction artifact 加入外置数据根目录并更新 manifest 前，阶段门不能解除。

### 2. 全量 ruff 未通过

`uv run --frozen ruff check .` 报 4 项错误，均在本阶段未修改的
`packages/spatial_core` 文件：

- `packages/spatial_core/spatial_core/model.py:207`：`RUF046`
- `packages/spatial_core/spatial_core/model.py:219`：`RUF046`
- `packages/spatial_core/spatial_core/model.py:289`：`F841`
- `packages/spatial_core/tests/test_model.py:1`：`I001`

这不是 4E-1 数据集入口逻辑的专项错误，但使仓库级 ruff 质量门未全绿。不得在
本次报告中替其修复或将其误记为通过。

## 已验证通过的实现行为

### Manifest 与安全入口

- `schema_version=stage-4e-dataset-v1`、dataset id、split、媒体类型、正整数像素
  尺寸、SHA-256 格式均有结构校验。
- reviewed 标注强制要求 `annotator` 与 `reviewer` 外部标识；授权记录强制
  `status=authorized` 和外部 `reference`；`provenance.source` 为必填。
- 绝对路径、`..` 父目录穿越、`~` 路径均被拒绝；运行时 symlink artifact
  也被拒绝。路径按 POSIX 相对路径解析，artifact 解析后必须仍位于数据根目录内。
- 同一源 SHA-256 在 manifest 中重复出现会被拒绝。

### 源图、标注和 prediction 校验

`inspect_dataset` 通过 `load_bitmap` 完整解码 PNG/JPEG，并核对：

- 源文件字节 SHA-256；
- manifest 声明的媒体类型和像素尺寸；
- 标注文件字节 SHA-256；
- 标注 `asset_sha256` 与源图 SHA-256；
- 标注像素尺寸与实际源图尺寸；
- prediction 文件 SHA-256 和 JSON 可读性。

专项 fixture 验证了有效记录可返回 `ready=true`，哈希或尺寸链路不一致会失败。

### 空 pending 与评测

- 空 `intake_pending` manifest 可被加载和检查，`inspect_dataset` 返回
  `ready=false`。
- 空数据集调用 `evaluate_dataset` 明确失败，不返回伪造的零指标。
- 非空 reviewed 记录逐样本调用 `evaluate_model`，返回每条记录的 `id`、`split`、
  metrics 和 prediction 字节数，同时返回固定的 rooms 聚合计数、precision、
  recall、F1、IoU threshold。
- 任一记录校验或评测失败时不会返回部分聚合指标。

## 命令结果

所有命令均在 `/Users/yixingzhou/project/grandtianfu-v2` 执行。

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `uv run --frozen pytest -q packages/ingest/tests/test_dataset.py packages/ingest/tests/test_evaluation.py` | PASS | `17 passed in 0.12s` |
| `uv run --frozen pytest -q` | PASS | `211 passed, 2 warnings in 18.50s`；仅 FastAPI/Starlette deprecation warnings |
| `uv run --frozen ruff check packages/ingest/ingest/dataset.py packages/ingest/ingest/evaluation.py packages/ingest/tests/test_dataset.py packages/ingest/tests/test_evaluation.py` | PASS | `All checks passed!` |
| `uv run --frozen ruff check .` | FAIL | 上述 4 个既有 `spatial_core` 错误 |

## 复验探针摘要

使用临时数据根目录执行无写入探针：

- `/abs/x`、`../x`、`a/../x`、`~/x` manifest 路径均抛出 `DatasetError`；
- 指向数据根目录外的 symlink 在 `inspect_dataset` 抛出 `DatasetError`；
- 空 pending manifest 正常规范化为 `records=[]`；
- 仓库 manifest 实际为 `status=intake_pending` 且空记录。

## 后续解除条件

在受控外置数据根目录加入至少一条经授权的 PNG/JPEG、对应
`stage-4e-annotation-v1` 标注、第二审核者外部标识和可复现 prediction artifact，
更新 manifest 为可评测状态，并重新运行上述专项/全量命令。仓库级 ruff 还需另行
清理 `spatial_core` 的 4 个既有问题，才能达到全绿质量门。
