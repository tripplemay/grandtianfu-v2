# Stage 2 Workbench API

本目录提供 v2 阶段 2 的本地工作台 API。它只负责 SpatialModel 版本、校验和本地持久化；不包含生产认证、部署、计费、AI 调用或 3D 渲染。

## 本地启动

需要 Python 3.12 和 uv：

```bash
uv sync --extra dev --extra api --frozen
uv run uvicorn apps.api.app:app --host 127.0.0.1 --port 8000
```

服务只绑定 `127.0.0.1`。默认 SQLite 文件为 `data/workbench.sqlite3`，可用 `GT_DB_PATH` 指定路径：

```bash
GT_DB_PATH=/tmp/grandtianfu-workbench.sqlite3 \
  uv run uvicorn apps.api.app:app --host 127.0.0.1 --port 8000
```

应用启动时只对尚无该 `model_id` 的数据库执行一次显式 seed，默认 seed 是
`packages/spatial_core/tests/fixtures/confirmed-orthogonal-merge.json`。传入 `create_app(seed_path=None)` 可关闭 seed；seed 不会覆盖已有版本。

## API contract

所有写请求必须使用 `Content-Type: application/json`。模型必须符合 `SpatialModel v2`，`rooms` 和 `walls` 不能为空，所有 JSON 数值必须是有限数且绝对值不超过 `1_000_000_000`。

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/models` | 返回每个模型的最新 revision、状态和 hash |
| `GET` | `/api/models/{model_id}/revisions` | 返回历史版本摘要（倒序） |
| `GET` | `/api/models/{model_id}/latest` | 返回最新模型 envelope |
| `GET` | `/api/models/{model_id}/revisions/latest` | `/latest` 的别名 |
| `GET` | `/api/models/{model_id}/revisions/{revision}` | 返回指定不可变版本 |
| `POST` | `/api/models/{model_id}/validate` | 只校验，不写数据库 |
| `POST` | `/api/models/{model_id}/revisions` | CAS 保存或确认并追加新版本 |

保存请求格式：

```json
{
  "model": {"...": "SpatialModel v2"},
  "expected_revision": 1,
  "expected_hash": "sha256...",
  "note": "人工调整客厅沙发",
  "action": "save"
}
```

`action` 只能是 `save` 或 `confirm`。服务端始终分配 `latest + 1`：`save` 产生 `draft`，`confirm` 产生 `confirmed`。客户端提交的 `model.revision` 只能引用一个已有版本，用于编辑或历史恢复；历史恢复也只会追加新版本，不会覆盖或回退旧版本。`content_hash` 是服务端字段，客户端不得提交。

每次写入都在 SQLite `BEGIN IMMEDIATE` 事务中比较 `expected_revision` 和 `expected_hash`。旧写入返回 `409`，不会覆盖较新的版本；数据库 revision 行由触发器禁止 `UPDATE` 和 `DELETE`。

## 错误

- `200`：`/validate` 对结构合法但模型无效的输入返回 `{ "ok": false, "errors": [{"message": "..."}] }`。
- `201`：新 revision 创建成功，响应为 `{model, hash, note, created_at}`。
- `404`：模型或 revision 不存在。
- `409`：CAS 过期，响应包含 `current_revision` 和 `current_hash`。
- `422`：JSON、字段、枚举、有限数、模型结构或请求参数无效；不会写入。
- `500`：检测到持久化数据完整性错误，响应带 `code: "storage_integrity_error"`。

## 测试

```bash
uv run pytest -q
uv run ruff check apps/api
```

这是本地无认证工作台，不应直接暴露到公网；认证、授权和生产数据库属于后续阶段。
