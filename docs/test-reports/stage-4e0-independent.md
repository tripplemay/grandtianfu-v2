# 阶段 4E-0 独立验收报告

日期：2026-09-08

结论：**PASS（复验后）。**

首轮验收曾为 FAIL；下方保留首轮问题和证据，复验结果见文末“复验结果（修复后）”。

本次验收只增加本报告，未修改产品代码或测试代码，未提交。验收基线为
`a846e90` 上的当前未提交 diff；已阅读 `AGENTS.md`、
`docs/specs/stage-4e-evaluation-baseline.md` 及全部相关变更。
本仓库未找到 `CLAUDE.md`。规格标题写作“阶段 4E-1”，而路线图与本次任务为
“阶段 4E-0”，阶段命名应在冻结前统一。

## 阻断项

### 1. 零预测时非法真值矩形未在评测前失败

位置：`packages/ingest/ingest/evaluation.py:134`、`:137`、`:139`。

真值矩形的 `_rect` 校验位于预测循环内。输入没有预测房间时，非法真值不会
被检查，评测器返回正常指标 JSON。这使“没有识别到房间”的真实场景可以吞掉
标注错误，违反非法评测输入应先失败、不得产生误导性指标的阶段门。

复现命令：

```sh
uv run --frozen python -c 'from ingest import evaluate_rooms; print(evaluate_rooms([], [{"id":"broken","rect":[0,0,-1,10]}]))'
```

实际结果：`truth_count=1`，`matched_count=0`，`precision=recall=f1=0.0`，
`matches=[]`，未抛出 `AnnotationError`。

### 2. 非数值型 IoU 阈值可通过校验

位置：`packages/ingest/ingest/evaluation.py:129`。

```sh
uv run --frozen python -c 'import json; from ingest import evaluate_rooms; print(json.dumps(evaluate_rooms([], [], True)))'
```

实际结果为普通指标对象，其中 `"iou_threshold": true`。
布尔值是 Python 的整数子类，但不应作为评测阈值被接受；同模块的有限数校验
已明确拒绝布尔值。该入口需与数值契约保持一致。

### 3. 非法枚举类型未统一转为 AnnotationError

位置：`packages/ingest/ingest/evaluation.py:84`、`:98`。

在合法标注文档中分别设置 `walls[0].axis=[]` 或 `openings[0].kind={}`：

- 前者抛出 `TypeError: unhashable type: 'list'`。
- 后者抛出 `TypeError: unhashable type: 'dict'`。

两者仍然拒绝文档，但未遵守公开 `AnnotationError` 的校验异常契约；调用端若
只捕获 `AnnotationError` 会漏接。应先校验字符串类型，再检查枚举成员。

## 指定命令结果

所有 Python 命令在 `/Users/yixingzhou/project/grandtianfu-v2` 执行；
Web 命令在该目录的 `apps/web` 执行。

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `uv run --frozen pytest -q packages/ingest/tests/test_evaluation.py` | PASS | `8 passed in 0.31s` |
| `uv run --frozen pytest -q` | FAIL，环境阻塞 | `1 failed, 197 passed, 2 warnings, 4 errors in 19.18s` |
| `uv run ruff check packages/ingest/ingest packages/ingest/tests tests/e2e` | PASS | `All checks passed!` |
| `npm test` | PASS | `Test Files 5 passed (5)`，`Tests 31 passed (31)` |
| `npm run build` | PASS | TypeScript 检查通过，Vite `1843 modules transformed`，`built in 215ms` |

全量 pytest 未通过，不能按全绿处理。其失败集中在 scene3d 渲染临时文件创建，
首个确定异常是 `OSError: [Errno 28] No space left on device`，不是评测模块
断言失败。失败条目为：

- `packages/scene3d/tests/test_renderer.py::test_failed_render_does_not_publish_partial_output`
- `packages/scene3d/tests/test_renderer.py::test_unknown_asset_kind_is_a_hard_failure`
- `packages/scene3d/tests/test_worker.py::test_worker_reads_stdin_and_prints_manifest`
- `packages/scene3d/tests/test_worker.py::test_worker_reads_input_file`
- `packages/scene3d/tests/test_worker.py::test_worker_input_and_render_failures_have_stable_codes`

本轮确切临时根目录为：

```text
/private/var/folders/rq/8682y70j5ys5w899ft_9mddw0000gn/T/pytest-of-yixingzhou/pytest-212
```

异常写入文件为该目录下
`test_failed_render_does_not_pu0/.render.9csnun4m/normal.f32le`。
后续 `df -h /tmp .` 显示同卷仅剩 `419Mi`，容量占用 `100%`。
临时目录清理命令被执行工具拒绝，未发生清理；按协调要求未再次运行全量测试，
避免继续消耗磁盘。需在恢复空间后重新跑全量测试。

## 独立行为核对

除已有测试外，通过 `uv run --frozen python -` 执行无文件写入的边界探针。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 文档有限数与布尔值 | PASS | `pixel_size.width=True`、无限房间坐标均抛 `AnnotationError` |
| 正尺寸 | PASS | 负房间宽、零墙长、负开口 offset、零开口宽均抛 `AnnotationError` |
| 唯一 ID 与宿主 | PASS | 重复墙 ID、未知开口宿主均抛 `AnnotationError` |
| 非法轴字符串 | PASS | `axis='z'` 抛 `AnnotationError` |
| 非法轴/开口种类的集合类型 | FAIL | 见阻断项 3 |
| 零预测时真值校验 | FAIL | 见阻断项 1 |
| 布尔阈值 | FAIL | 见阻断项 2 |
| IoU 一对一匹配 | PASS | 相同矩形竞争时预测 ID、真值 ID 各只出现一次 |
| 同分排序和排列确定性 | PASS | 3 个预测、2 个真值的 12 组排列产生完全相同的排序 JSON |
| 输入不变性 | PASS | `load_annotation`、`evaluate_rooms` 调用前后深拷贝相等，规范化结果容器与原输入分离 |

确定性探针的输入为：

```python
predicted = [
    {"id": "p-b", "rect": [0, 0, 100, 100]},
    {"id": "p-a", "rect": [0, 0, 100, 100]},
    {"id": "p-c", "rect": [200, 0, 100, 100]},
]
truth = [
    {"id": "t-b", "rect": [0, 0, 100, 100]},
    {"id": "t-a", "rect": [0, 0, 100, 100]},
]
```

12 组排列均输出 `p-a -> t-a`、`p-b -> t-b`，两者 IoU 均为 `1.0`；
`matched_count=2`、`precision=0.666667`、`recall=1.0`、`f1=0.8`。
比较使用 `json.dumps(..., sort_keys=True, allow_nan=False)`。

## ingest 输出与范围

已核对 diff：产品变更只有新增 `evaluation.py` 与 `ingest/__init__.py` 的公共
导出；`bitmap.py`、`topology.py`、算法版本、现有识别逻辑及 SpatialModel
生成路径均未修改。评测模块没有文件写入、原位赋值或 ingest 调用，独立探针
也证明输入对象没有被修改。

因此首轮的静态隔离与评测输入不变性检查为 PASS；首轮没有将全量回归结果或
任何未执行的基线 artifact 字节比较表述为通过。上述 FAIL 项已在复验前修复，
复验结论见下节。

## 复验结果（修复后）

父代理修复了首轮发现的三个边界，并清理了首轮的 pytest 临时产物；本轮未修改
产品代码，仅重新执行验证命令。修复包括：评测前预校验 predicted/truth 两侧
矩形、拒绝布尔 IoU 阈值、以及对 axis/kind 先做字符串类型检查；同时新增
`evaluate_model` 的模型到标注像素坐标映射及对应测试。

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `uv run --frozen pytest -q packages/ingest/tests/test_evaluation.py` | PASS | `10 passed in 0.09s` |
| `uv run --frozen pytest -q` | PASS | `204 passed, 2 warnings in 18.71s` |
| `uv run ruff check packages/ingest/ingest packages/ingest/tests tests/e2e` | PASS | `All checks passed!` |

复验边界探针结果：

- `evaluate_rooms([], [{"id":"broken","rect":[0,0,-1,10]}])` 现在抛出
  `AnnotationError`，不再产生零分指标。
- `evaluate_rooms([], [], iou_threshold=True)` 现在抛出 `AnnotationError`。
- `axis=[]/{}` 与 `kind=[]/{}` 现在均抛出 `AnnotationError`，不再逸出
  `TypeError`。
- 输入排列的一对一匹配、确定性排序和输入不变性仍保持通过。

首轮全量 pytest 因磁盘空间失败，本轮在清理
`/private/var/folders/rq/8682y70j5ys5w899ft_9mddw0000gn/T/pytest-of-yixingzhou/pytest-212`
后完整通过；因此首轮环境阻塞已解除。原先 Web `npm test`（31/31）与
`npm run build`（Vite 1843 modules transformed）结果仍有效，评测模块本轮
没有触及 Web 代码。

基于上述复验，阶段 4E-0 的标注 schema 严格校验、房间 IoU 一对一确定性、
不修改 ingest 输入/输出约束及指定回归命令均通过。报告仍为未提交工作树文件。
