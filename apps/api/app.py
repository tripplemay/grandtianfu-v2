"""FastAPI entrypoint for the local, unauthenticated Stage 2 workbench."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from ingest import BitmapError
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from .ingest import IngestUnavailable, ingest_bitmap_worker
from .rendering import RenderUnavailable, render_revision
from .revisions import (
    InvalidModel,
    MissingRevision,
    RevisionConflict,
    RevisionStore,
    StorageIntegrityError,
    checked_model,
    strict_json,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = ROOT / "packages/spatial_core/tests/fixtures/confirmed-orthogonal-merge.json"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_INGEST_BYTES = 20 * 1024 * 1024


async def _body(request: Request, fields: set[str]) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        raise InvalidModel("Content-Type must be application/json")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise InvalidModel("Request body exceeds 2 MiB")
        chunks.append(chunk)
    body = strict_json(b"".join(chunks))
    if not isinstance(body, dict):
        raise InvalidModel("Request body must be an object")
    if set(body) != fields:
        raise InvalidModel(f"Request fields must be: {', '.join(sorted(fields))}")
    return body


def create_app(
    db_path: str | Path | None = None,
    seed_path: str | Path | None = DEFAULT_SEED,
    static_dir: str | Path | None = None,
) -> FastAPI:
    store = RevisionStore(db_path or os.environ.get("GT_DB_PATH", str(ROOT / "data/workbench.sqlite3")))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await run_in_threadpool(store.initialize, seed_path)
        yield

    app = FastAPI(title="Grandtianfu v2 Local Workbench", lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(InvalidModel)
    async def invalid_model_handler(_: Request, exc: InvalidModel):
        return JSONResponse(status_code=422, content={"detail": str(exc), "errors": [{"message": str(exc)}]})

    @app.exception_handler(MissingRevision)
    async def missing_handler(_: Request, exc: MissingRevision):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(RevisionConflict)
    async def conflict_handler(_: Request, exc: RevisionConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc), "current_revision": exc.current_revision, "current_hash": exc.current_hash})

    @app.exception_handler(StorageIntegrityError)
    async def integrity_handler(_: Request, exc: StorageIntegrityError):
        return JSONResponse(status_code=500, content={"detail": str(exc), "code": "storage_integrity_error"})

    @app.exception_handler(RenderUnavailable)
    async def render_handler(_: Request, exc: RenderUnavailable):
        return JSONResponse(status_code=503, content={"detail": str(exc), "code": "render_unavailable"})

    @app.exception_handler(BitmapError)
    async def bitmap_handler(_: Request, exc: BitmapError):
        return JSONResponse(status_code=422, content={"detail": str(exc), "code": "invalid_bitmap"})

    @app.exception_handler(IngestUnavailable)
    async def ingest_handler(_: Request, exc: IngestUnavailable):
        return JSONResponse(status_code=503, content={"detail": str(exc), "code": "ingest_unavailable"})

    @app.get("/api/models")
    def list_models():
        return store.list_models()

    @app.get("/api/models/{model_id}/revisions")
    def list_revisions(model_id: str):
        return store.list_revisions(model_id)

    @app.get("/api/models/{model_id}/latest")
    @app.get("/api/models/{model_id}/revisions/latest")
    def latest(model_id: str):
        return store.get(model_id)

    @app.get("/api/models/{model_id}/revisions/{revision}")
    def get_revision(model_id: str, revision: int):
        return store.get(model_id, revision)

    @app.post("/api/models/{model_id}/renders")
    async def render(model_id: str, request: Request):
        body = await _body(request, {"revision", "width", "height"})
        revision = body["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise InvalidModel("revision must be a positive integer")
        envelope = await run_in_threadpool(store.get, model_id, revision)
        model = envelope["model"]
        if model["status"] not in {"confirmed", "locked"}:
            raise InvalidModel("only confirmed or locked revisions can be rendered")
        root = os.environ.get("GT_RENDER_ROOT", str(ROOT / "artifacts/renders"))
        manifest = await run_in_threadpool(render_revision, model, root, width=body["width"], height=body["height"])
        manifest["artifact_url"] = f"/render-artifacts/{model_id}/r{revision}-{envelope['hash'][:16]}"
        return manifest

    @app.post("/api/ingests", status_code=201)
    async def create_ingest(request: Request):
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type not in {"image/png", "image/jpeg"}:
            raise BitmapError("Content-Type must be image/png or image/jpeg")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_INGEST_BYTES:
                raise BitmapError("bitmap upload exceeds 20 MiB")
            chunks.append(chunk)
        data = b"".join(chunks)
        signature_type = "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if data.startswith(b"\xff\xd8") else None
        if signature_type != content_type:
            raise BitmapError("Content-Type does not match bitmap signature")
        filename = request.headers.get("x-filename", "upload.png" if content_type == "image/png" else "upload.jpg")
        root = Path(os.environ.get("GT_INGEST_ROOT", str(ROOT / "artifacts/ingests")))
        draft = await run_in_threadpool(ingest_bitmap_worker, data, filename, os.environ.get("GT_INGEST_ROOT", str(ROOT / "artifacts/ingests")))
        ingest_id = draft["source"]["sha256"]
        directory = root / ingest_id
        directory.mkdir(parents=True, exist_ok=True)
        extension = ".png" if content_type == "image/png" else ".jpg"
        (directory / f"source{extension}").write_bytes(data)
        (directory / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
        manifest = {
            "schema_version": "ingest-0.1",
            "ingest_id": ingest_id,
            "source": {"sha256": ingest_id, "media_type": content_type, "filename": filename},
            "draft_model": "draft.json",
            "requires_human_review": True,
        }
        (directory / "ingest-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        return {**manifest, "model": draft}

    @app.get("/api/ingests/{ingest_id}")
    def get_ingest(ingest_id: str):
        if len(ingest_id) != 64 or any(char not in "0123456789abcdef" for char in ingest_id):
            raise MissingRevision("Ingest not found")
        root = Path(os.environ.get("GT_INGEST_ROOT", str(ROOT / "artifacts/ingests")))
        manifest_path = root / ingest_id / "ingest-manifest.json"
        draft_path = root / ingest_id / "draft.json"
        if not manifest_path.is_file() or not draft_path.is_file():
            raise MissingRevision("Ingest not found")
        return {"manifest": json.loads(manifest_path.read_text()), "model": json.loads(draft_path.read_text())}

    @app.post("/api/models/{model_id}/validate")
    async def validate(model_id: str, request: Request):
        body = await _body(request, {"model"})
        await run_in_threadpool(store.get, model_id)
        try:
            checked_model(body["model"], model_id)
        except InvalidModel as exc:
            return {"ok": False, "errors": [{"message": str(exc)}]}
        return {"ok": True, "errors": []}

    @app.post("/api/models/{model_id}/revisions", status_code=201)
    async def append_revision(model_id: str, request: Request):
        body = await _body(request, {"model", "expected_revision", "expected_hash", "note", "action"})
        return await run_in_threadpool(store.append, model_id, **body)

    dist = Path(static_dir) if static_dir is not None else ROOT / "apps/web/dist"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets, follow_symlink=False), name="assets")
    render_root = Path(os.environ.get("GT_RENDER_ROOT", str(ROOT / "artifacts/renders")))
    render_root.mkdir(parents=True, exist_ok=True)
    app.mount("/render-artifacts", StaticFiles(directory=render_root, follow_symlink=False), name="render-artifacts")

    @app.get("/", include_in_schema=False)
    def index():
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return JSONResponse(status_code=503, content={"detail": "Frontend is not built. Build apps/web before opening the workbench."})

    return app


app = create_app()
