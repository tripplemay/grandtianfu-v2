# Stage 4 Bitmap Ingest 独立验收报告

验收日期：2026-09-07  
分支：`feat/stage-4-bitmap-ingest`  
基线：`3dc27aa`  
结论：**FAIL**

## 自动化检查

- `uv run pytest -q`：`88 passed`（含 API、ingest worker 和 bitmap 测试），2 个既有依赖弃用警告。
- `uv run ruff check apps/api packages/ingest`：通过。
- `python -m ingest.worker --help`：worker CLI 可用。

## API/worker 验收

使用临时 `GT_INGEST_ROOT` 和 2x1 PNG fixture 验证：

- `POST /api/ingests` 成功返回 `201`；`ingest_id == source.sha256`，draft model 的 `status` 为 `draft`，`requires_human_review` 为 `true`；随后 `GET /api/ingests/{id}` 返回同一 draft。
- 同一字节重复 POST 返回相同 `ingest_id`，复用内容寻址目录。
- worker valid fixture 返回 exit 0，输出 `draft-model.json`、`preprocess-manifest.json`、`ingest-manifest.json`；输出模型始终为 draft，保留 source hash 和人工复核标记。
- MIME/signature 不匹配（PNG bytes 声明 `image/jpeg`）返回 `422`；PDF（`application/pdf`）返回 `422`；不会生成 ingest draft。
- worker 对有效 JPEG 仅执行 `jpeg-header-only` 尺寸识别，低 confidence 且要求人工复核；这是规格明确的首期边界，不作为通过精确识别的证据。

## 阻断问题

### P1：截断 PNG 缺少 IEND 仍被接受

`packages/ingest/ingest/bitmap.py:_read_png` 在解析完 IDAT 并成功解压像素后，没有要求遇到 `IEND`，也没有拒绝文件末尾缺失 IEND 的情况。复现：把有效 PNG 的最后 5 字节（IEND chunk）去掉后，以 `Content-Type: image/png` POST `/api/ingests`，当前返回 `201`，生成 draft、source 和 manifest；预期应返回明确的损坏/截断错误（`422`），且不产生 draft。该行为违反 Stage 4 输入契约“完整读取、坏文件给出明确结果”，也使损坏源进入候选流水线。

当前 CRC 损坏测试能失败，但只覆盖 CRC，不覆盖关键 chunk 缺失；建议要求 `IEND`、拒绝尾部截断/不完整 chunk，并补充 API 与 worker 两层回归测试。

## 原子性与边界说明

worker 内部使用临时目录后 `os.replace` 发布，valid smoke 未观察到半成品；API 在 worker 返回后另外写入 `source.*`、`draft.json` 和 `ingest-manifest.json`，这些补充文件是逐个写入而非单次目录替换。进程在该窗口中止时，GET 可能看到 worker 文件但缺少 API 文件，建议后续将 API manifest/source/draft 写入临时目录后整体原子发布，或在 GET 校验完整集合。

本阶段明确未实现/不应误判为通过的边界：JPEG 目前是 header-only，不做像素解码、EXIF Orientation、OCR、CV 墙房间门窗识别或人工确认 API；PDF/CAD/IFC、透视校正、斜墙和非矩形区域均应继续拒绝或留在后续阶段。

## 放行结论

draft 生命周期、source hash、`requires_human_review`、幂等成功路径、MIME/signature/PDF 拒绝和 worker 隔离均通过；但损坏 PNG 的完整性门禁失败，故当前 Stage 4 不能放行，最终结论为 **FAIL**。修复 IEND/截断检查并补测后再复验。

## 最终复验（bounded slice）

复验日期：2026-09-07。当前工作区已加入 PNG IEND 完整性检查，并将 API 侧补充 artifact 改为复用 worker 的原子目录产物；本轮只验收明确的 bounded slice。

- `uv run pytest -q`：`89 passed`，2 个既有依赖弃用警告。
- `uv run ruff check apps/api packages/ingest`：通过。
- API 有效 PNG：`POST /api/ingests` 返回 `201`，模型 `status=draft`，`source.sha256 == ingest_id`，`requires_human_review=true`；随后 GET 返回 200 且模型一致；重复 POST 返回相同内容寻址 ID（201）。输出目录完整包含 `source.png`、`draft-model.json`、`preprocess-manifest.json`、`ingest-manifest.json`。
- API 截断 PNG（去掉 IEND）：返回 `422`，错误为 `PNG is missing IEND`，未污染已有成功目录。
- worker JPEG fixture：exit 0，输出模型为 draft，source hash 和人工复核标记保留；JPEG 仍是规格允许的 `header-only` 边界。

上述原阻断已关闭。当前 bounded slice 验收结论为 **PASS**。完整 Stage 4 仍明确不包含 JPEG 像素/EXIF Orientation、OCR、CV 墙房间门窗识别、透视校正或人工确认 API；这些能力不得从本报告的 PASS 推断已实现。
