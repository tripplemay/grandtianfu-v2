# 阶段 4：位图导入首个垂直切片

状态：**首个 bounded slice 独立验收通过，等待用户确认**

## 已交付

- PNG/JPEG 文件签名、尺寸、CRC 和大小校验；拒绝 PDF/CAD 或 MIME/签名不一致输入。
- 独立 `ingest.worker` CPU 进程，临时目录原子发布，失败不覆盖旧产物。
- PNG 灰度化、暗线行列候选、RGBA/alpha 白底合成和稳定源 hash。
- 生成始终为 `status=draft` 的 SpatialModel，房间/墙体候选带 `provenance`、`confidence`。
- API `POST /api/ingests` 和 `GET /api/ingests/{ingest_id}`，按原始位图 SHA-256 幂等寻址。
- 原始位图、draft model、预处理 manifest 和 ingest manifest 分离保存。

## 验证

- `uv run pytest -q`：89 passed。
- `uv run ruff check apps/api apps/api/tests packages/ingest packages/ingest/tests`：通过。
- 前置 Stage 3 的前端测试与构建保持通过。
- API 上传 smoke：返回 draft、源 hash 和 `requires_human_review=true`；重复上传复用同一 ingest id。
- 独立验收报告：`docs/test-reports/stage-4-acceptance-report.md`，bounded slice 结论 PASS。

## 当前边界

这是阶段 4 的首个可验收切片，不是完整户型识别系统。JPEG 当前只读取尺寸并以低置信度进入人工校核；尚未实现 EXIF 规范化、OCR 尺寸识别、完整墙/房间/门窗 CV 识别和人工确认 API。所有导入结果均必须经过现有 2D 工作台人工修正和确认，不能直接进入精确布局或照片级生成。
