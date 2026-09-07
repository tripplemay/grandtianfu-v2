# 阶段 4 集成交付契约

本文件记录本轮实现和验收边界，不替代 `stage-4-ingest.md` 的完整阶段门。
完整阶段 4 仍为 PARTIAL，不因以下闭环可用而自动进入阶段 5。

## 输入与识别

- PNG/JPEG 完整解码后才识别，Pillow 负责 EXIF 与透明白底/颜色规范化。
- 必须由用户输入有限正值 `mm_per_pixel`。未给比例直接拒绝，不把像素写成 mm；
  修订原规格中的“临时像素 SpatialModel”方案，避免破坏核心单位契约。
- OpenCV 提取长水平/垂直墙带、匹配双线墙、寻找闭合矩形、生成有宿主的缺口。
  闭合矩形以外的图形不补成整幅图片边框，长斜线和无有效闭合候选明确拒绝。
- 共享墙缺口给出 merge 候选证据，不自动写入确定的 merge 事实。
- Tesseract TSV 仅提供带 bbox/confidence 的数字证据；没有尺寸线端点关联，
  不自动选取比例，不宣称已完成 OCR 尺寸一致性检查。
- 缺口为 `wall_gap_unclassified`，不宣称自动区分门弧/窗框。层高和洞高分别暂用
  2800/2100 mm，来源为 `default_unmeasured`、置信度为 0，必须人工核验。
- 不生成默认相机；用户以 mm 显式录入相机后才能渲染。

依据的成熟组件：[Pillow 解码/校验](https://pillow.readthedocs.io/en/stable/reference/Image.html)、
[EXIF 规范化](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html)、
[OpenCV 形态学](https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html)、
[Tesseract TSV](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)。

## API 与状态

`POST /api/ingests?mm_per_pixel=10` 上传原始图片字节，`Content-Type: image/png|image/jpeg`，
`X-Filename` 为 URI 编码的显示名称，不用作路径。20 MiB / 12000 px / 50 MP 为硬上限。

返回 `ingest_id`、`model`、`envelope`、`manifest`、`source_url`、`preprocessed_url`。
任务 ID 包含源 SHA-256、比例、识别算法、Pillow/OpenCV/NumPy/OCR 版本，不等于源 hash。
文件名不改变模型 ID。重复上传复用初始识别证据，返回当前最新 revision，不覆盖人工修改。

`GET /api/ingests/{id}` 返回已验证证据与当前版本。固定 artifact 路由只接受
`source`、`preprocessed`、`draft_model`、`preprocessing`；每次读取校验完整文件集与 hash。
损坏缓存返回 `500 storage_integrity_error`，禁止用成功状态隐藏或自动重写损坏。

原始上传、规范化 PNG、预处理 JSON、候选草稿和 manifest 分离保存。受理后的 worker
失败在 `rejected/{id}` 保留 source.bin 和 failure.json。MIME/比例/大小入口校验失败不落盘。
120 秒超时、worker 故障或忙碌返回 503；识别失败返回 422。单机跨进程文件锁限制同时
运行一个识别任务，暂不提供持久队列、排队取消或作业查询。取消浏览器请求不承诺取消已受理任务。

保存修改复用 `/api/models/{id}/revisions`；来源和初始识别参数不可伪造，重新标定须重新导入。
人工审核是独立的 `POST /api/ingests/{id}/confirm`，请求形如：

```json
{
  "expected_revision": 2,
  "expected_hash": "当前草稿 hash",
  "reviewed_object_ids": ["当前所有 room/wall/opening ID，恰好各一次"],
  "checks": {"scale": true, "geometry": true, "openings": true, "heights": true},
  "reviewer": "local-user"
}
```

普通 confirm 接口不能绕过位图审核；审核必须基于最新已保存的草稿。服务端校验
CAS、全部对象清单、四项严格布尔检查和核心几何后生成新 confirmed revision。
审核 audit 记录源 hash、输入草稿 hash/revision、对象 ID、检查项、时间和自报本地操作者；
尚无认证，不能当作生产身份审计。后续保存返回 draft 并移除审核记录，必须重新审核。
低置信度原始证据不会被改成高置信度事实，审核记录是独立的人工作证。
确认版本中对象及尺寸/高度的 `needs_review` 设为 false；再保存为草稿时恢复 true。
初始 ingest 候选证据保持不可变，数值置信度始终表示识别来源，不表示已审核与否。

3D manifest 带 `source` 和 `review`，结合模型 hash、revision 和实例 ID 可追溯到位图。
2D confirmed 不要求相机，但调用渲染必须有显式有效相机；未保存修改不能渲染旧模型冒充当前模型。

## 本轮验收

1. 真实 PNG/JPEG 产生非图片边框的候选；原图/规范化/叠加都可读取。
2. 显式比例换算、EXIF/alpha、截断图像和坏文件拒绝、哈希重复性。
3. 草稿进入工作台，修改另存新 revision；逐对象与比例/边界/开口/高度审核，审核失效与 CAS。
4. 绕过审核、修改 source/ingest、缺对象、用数字 1 冒充 true 均不能确认。
5. 人工相机 + confirmed 进入 CPU 3D；原始 hash 与输入草稿 hash 可追溯。
6. 桌面及 390px 浏览器真实链路、截图与非空渲染像素检查。

## 未完成的完整阶段门

- 真实标注户型数据集与泛化精度、鲁棒性和资源预算；合成矩形数据不代表真实准确率。
- 尺寸线/端点关联、多个 OCR 尺寸冲突处理；自动门窗符号分类及相应召回率。
- 复杂断线/局部不支持区域的结构化修复；现阶段部分失败须修正图片再导入。
- 图上两点已知长度标定、原始候选和人工修订差异的交互增强。

上述缺口保留在阶段 4；不得将当前结果标记成完整阶段 4 PASS。
