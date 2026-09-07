"""FastAPI entrypoint for the local, unauthenticated Stage 2 workbench."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from ingest import BitmapError
from ingest.bitmap import load_bitmap
from spatial_core import canonical_hash
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from .ingest import (
    IngestUnavailable,
    crop_ingest_worker,
    ingest_bitmap_worker,
    ingest_response,
    read_ingest,
)
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
from .topology import topology_ingest_worker
from .tracing import trace_ingest_worker

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
    ingest_root: str | Path | None = None,
) -> FastAPI:
    store = RevisionStore(db_path or os.environ.get("GT_DB_PATH", str(ROOT / "data/workbench.sqlite3")))

    def intake_root() -> Path:
        return Path(ingest_root or os.environ.get("GT_INGEST_ROOT", str(ROOT / "artifacts/ingests")))

    def verified_ingest(ingest_id: str):
        try:
            return read_ingest(intake_root(), ingest_id)
        except FileNotFoundError as exc:
            raise MissingRevision("Ingest not found") from exc

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
    async def create_ingest(request: Request, mm_per_pixel: float | None = None):
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
        filename = unquote(request.headers.get("x-filename", "upload"))
        if len(filename) > 255 or any(ord(char) < 32 for char in filename):
            raise BitmapError("invalid display filename")
        result = await run_in_threadpool(ingest_bitmap_worker, data, filename, intake_root(), mm_per_pixel=mm_per_pixel)
        envelope = await run_in_threadpool(store.import_draft, result["model"])
        return ingest_response(result, envelope)

    @app.get("/api/ingests/{ingest_id}")
    def get_ingest(ingest_id: str):
        result = verified_ingest(ingest_id)
        envelope = store.import_draft(result["model"])
        return ingest_response(result, envelope)

    @app.post("/api/ingests/{ingest_id}/crop", status_code=201)
    async def crop_ingest(ingest_id: str, request: Request):
        body = await _body(request, {"bbox", "expected_source_sha256"})
        parent = await run_in_threadpool(verified_ingest, ingest_id)
        if body["expected_source_sha256"] != parent["model"]["source"]["sha256"]:
            raise RevisionConflict({"model": parent["model"], "hash": canonical_hash(parent["model"])})
        result = await run_in_threadpool(crop_ingest_worker, parent, body["bbox"], intake_root())
        envelope = await run_in_threadpool(store.import_draft, result["model"])
        return ingest_response(result, envelope)

    @app.post("/api/ingests/{ingest_id}/trace", status_code=201)
    async def trace_ingest(ingest_id: str, request: Request):
        body = await _body(request, {"expected_source_sha256", "bbox", "rooms", "wall_thickness_mm", "wall_height_mm"})
        parent = await run_in_threadpool(verified_ingest, ingest_id)
        if body["expected_source_sha256"] != parent["model"].get("source", {}).get("sha256"):
            raise RevisionConflict({"model": parent["model"], "hash": canonical_hash(parent["model"])})
        result = await run_in_threadpool(
            trace_ingest_worker, parent, bbox=body["bbox"], rooms=body["rooms"],
            wall_thickness_mm=body["wall_thickness_mm"], wall_height_mm=body["wall_height_mm"], root=intake_root(),
        )
        envelope = await run_in_threadpool(store.import_draft, result["model"])
        return ingest_response(result, envelope)

    @app.post("/api/ingests/{ingest_id}/topology", status_code=201)
    async def review_topology(ingest_id: str, request: Request):
        body = await _body(request, {"expected_source_sha256", "openings", "merge_groups", "reviewed_object_ids"})
        parent = await run_in_threadpool(verified_ingest, ingest_id)
        if body["expected_source_sha256"] != parent["model"].get("source", {}).get("sha256"):
            raise RevisionConflict({"model": parent["model"], "hash": canonical_hash(parent["model"])})
        result = await run_in_threadpool(
            topology_ingest_worker, parent, openings=body["openings"], merge_groups=body["merge_groups"],
            reviewed_object_ids=body["reviewed_object_ids"], root=intake_root(),
        )
        envelope = await run_in_threadpool(store.import_draft, result["model"])
        return ingest_response(result, envelope)

    @app.get("/api/ingests/{ingest_id}/artifacts/{channel}")
    def ingest_artifact(ingest_id: str, channel: str):
        result = verified_ingest(ingest_id)
        if channel == "normalized-source":
            filename = result["manifest"]["files"]["source"]
            data = (intake_root() / ingest_id / filename).read_bytes()
            asset = load_bitmap(data, filename)
            return Response(content=asset.normalized_png, media_type="image/png",
                            headers={"X-Content-Type-Options": "nosniff",
                                     "X-Normalized-Sha256": asset.normalization["normalized_sha256"]})
        if channel not in {"source", "preprocessed", "draft_model", "preprocessing"}:
            raise MissingRevision("Artifact not found")
        filename = result["manifest"]["files"][channel]
        return FileResponse(intake_root() / ingest_id / filename, headers={"X-Content-Type-Options": "nosniff"})


    @app.post("/api/ingests/{ingest_id}/confirm", status_code=201)
    async def confirm_ingest(ingest_id: str, request: Request):
        body = await _body(request, {"expected_revision", "expected_hash", "reviewed_object_ids", "checks", "reviewer"})
        result = await run_in_threadpool(verified_ingest, ingest_id)
        from .topology_confirmation import verify_topology_reference

        reference = await run_in_threadpool(verify_topology_reference, result, intake_root())
        return await run_in_threadpool(store.confirm_ingest, result["model"]["model_id"], ingest_id,
                                      topology_reference=reference, **body)

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
