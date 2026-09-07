"""Append-only local revision storage with optimistic concurrency."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spatial_core import ModelValidationError, canonical_hash, validate_model


class InvalidModel(ValueError):
    """Untrusted input cannot satisfy the stored model contract."""


class MissingRevision(LookupError):
    """The requested model or revision does not exist."""


class RevisionConflict(Exception):
    def __init__(self, current: dict[str, Any]):
        super().__init__("The model has a newer revision; reload before saving.")
        self.current_revision = current["model"]["revision"]
        self.current_hash = current["hash"]


class StorageIntegrityError(RuntimeError):
    """Persisted bytes no longer match their recorded identity or hash."""


_MAX_JSON_NUMBER = 1_000_000_000


def _reject_constant(value: str) -> None:
    raise InvalidModel(f"Non-finite JSON number is not allowed: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidModel(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite_json(value: Any) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidModel("All JSON numbers must be finite")
        if abs(value) > _MAX_JSON_NUMBER:
            raise InvalidModel(f"JSON numbers must be within +/-{_MAX_JSON_NUMBER}")
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise InvalidModel("JSON strings must contain valid Unicode scalar values") from exc
    if isinstance(value, dict):
        for key, nested in value.items():
            _finite_json(key)
            _finite_json(nested)
    elif isinstance(value, list):
        for nested in value:
            _finite_json(nested)


def strict_json(raw: bytes | str) -> Any:
    try:
        value = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        _finite_json(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InvalidModel(str(exc) or "Invalid JSON") from exc


def checked_model(value: Any, model_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidModel("model must be an object")
    if "content_hash" in value:
        raise InvalidModel("content_hash is server-managed; omit it from the model")
    if model_id is not None and value.get("model_id") != model_id:
        raise InvalidModel("model.model_id must match the requested model")
    try:
        _finite_json(value)
        # A renderable Stage 2 model always has a physical shell. Empty drafts
        # are reserved for a future ingest workflow, not this workbench.
        if not isinstance(value.get("rooms"), list) or not value["rooms"]:
            raise InvalidModel("model.rooms must be a non-empty array")
        if not isinstance(value.get("walls"), list) or not value["walls"]:
            raise InvalidModel("model.walls must be a non-empty array")
        validate_model(value)
        # Check unknown extension fields as well as fields validated by spatial_core.
        json.dumps(value, allow_nan=False)
    except (ModelValidationError, TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise InvalidModel(str(exc) or "Invalid model structure") from exc
    return value


class RevisionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self, seed_path: str | Path | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS revisions (
                    model_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    status TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (model_id, revision)
                );
                CREATE TRIGGER IF NOT EXISTS revisions_no_update
                BEFORE UPDATE ON revisions BEGIN
                    SELECT RAISE(ABORT, 'revisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS revisions_no_delete
                BEFORE DELETE ON revisions BEGIN
                    SELECT RAISE(ABORT, 'revisions are immutable');
                END;
            """)
        if seed_path is not None:
            model = checked_model(strict_json(Path(seed_path).read_bytes()))
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    if db.execute("SELECT 1 FROM revisions WHERE model_id = ? LIMIT 1", (model["model_id"],)).fetchone() is None:
                        self._insert(db, model, "Initial hand-authored fixture")
                    db.commit()
                except Exception:
                    db.rollback()
                    raise

    @staticmethod
    def _envelope(row: sqlite3.Row) -> dict[str, Any]:
        try:
            model = strict_json(row["payload"])
            if (
                not isinstance(model, dict)
                or model.get("model_id") != row["model_id"]
                or model.get("revision") != row["revision"]
                or model.get("status") != row["status"]
                or canonical_hash(model) != row["content_hash"]
            ):
                raise StorageIntegrityError("Stored revision identity or hash mismatch")
        except (InvalidModel, TypeError, ValueError) as exc:
            raise StorageIntegrityError("Stored revision JSON is invalid") from exc
        return {"model": model, "hash": row["content_hash"], "note": row["note"], "created_at": row["created_at"]}

    @classmethod
    def _latest(cls, db: sqlite3.Connection, model_id: str) -> dict[str, Any]:
        row = db.execute("SELECT * FROM revisions WHERE model_id = ? ORDER BY revision DESC LIMIT 1", (model_id,)).fetchone()
        if row is None:
            raise MissingRevision("Model not found")
        return cls._envelope(row)

    @staticmethod
    def _insert(db: sqlite3.Connection, model: dict[str, Any], note: str) -> dict[str, Any]:
        content_hash = canonical_hash(model)
        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        db.execute(
            "INSERT INTO revisions (model_id, revision, status, content_hash, payload, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (model["model_id"], model["revision"], model["status"], content_hash, json.dumps(model, ensure_ascii=False, allow_nan=False, separators=(",", ":")), note, created_at),
        )
        return {"model": model, "hash": content_hash, "note": note, "created_at": created_at}

    def list_models(self) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("""
                SELECT r.* FROM revisions r JOIN (
                    SELECT model_id, MAX(revision) AS revision FROM revisions GROUP BY model_id
                ) latest USING (model_id, revision) ORDER BY r.model_id
            """).fetchall()
        result = []
        for row in rows:
            envelope = self._envelope(row)
            model = envelope["model"]
            title = model.get("title")
            result.append({"model_id": model["model_id"], "title": title if isinstance(title, str) and title.strip() else model["model_id"], "latest_revision": model["revision"], "status": model["status"], "hash": envelope["hash"]})
        return result

    def list_revisions(self, model_id: str) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM revisions WHERE model_id = ? ORDER BY revision DESC", (model_id,)).fetchall()
        if not rows:
            raise MissingRevision("Model not found")
        return [{"revision": entry["model"]["revision"], "status": entry["model"]["status"], "hash": entry["hash"], "note": entry["note"], "created_at": entry["created_at"]} for entry in map(self._envelope, rows)]

    def get(self, model_id: str, revision: int | None = None) -> dict[str, Any]:
        with self._connection() as db:
            if revision is None:
                return self._latest(db, model_id)
            row = db.execute("SELECT * FROM revisions WHERE model_id = ? AND revision = ?", (model_id, revision)).fetchone()
        if row is None:
            raise MissingRevision("Revision not found")
        return self._envelope(row)

    def import_draft(self, model: dict[str, Any]) -> dict[str, Any]:
        checked_model(model)
        if model["status"] != "draft" or model["revision"] != 1 or model["source"]["kind"] != "bitmap":
            raise InvalidModel("ingest must create an initial bitmap draft")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM revisions WHERE model_id = ? AND revision = 1", (model["model_id"],)).fetchone()
                if row is not None:
                    if self._envelope(row)["hash"] != canonical_hash(model):
                        raise StorageIntegrityError("Ingest identity already has a different initial model")
                    result = self._latest(db, model["model_id"])
                else:
                    result = self._insert(db, model, "Bitmap recognition; awaiting human review")
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    def confirm_ingest(self, model_id: str, ingest_id: str, *, expected_revision: int,
                       expected_hash: str, reviewed_object_ids: Any, checks: Any,
                       reviewer: Any, topology_reference: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.get(model_id)
        model = current["model"]
        if current["hash"] != expected_hash or model["revision"] != expected_revision:
            raise RevisionConflict(current)
        ingest = model.get("ingest", {})
        if model["source"]["kind"] != "bitmap" or ingest.get("ingest_id") != ingest_id:
            raise InvalidModel("model is not associated with this ingest")
        if model["status"] != "draft":
            raise InvalidModel("only a draft can be reviewed")
        scale = ingest.get("mm_per_pixel")
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
            raise InvalidModel("a verified user scale is required")
        topology_evidence = None
        blockers = ingest.get("hard_blockers", [])
        if blockers or ingest.get("blockers"):
            if (ingest.get("blockers") or not isinstance(blockers, list) or len(blockers) != 1
                    or not isinstance(blockers[0], dict)
                    or blockers[0].get("code") != "manual_trace_requires_topology_review"
                    or topology_reference is None):
                raise InvalidModel("unresolved recognition blockers require corrected input")
            from .topology_confirmation import topology_confirmation_evidence

            topology_evidence = topology_confirmation_evidence(model, topology_reference)
        required_checks = {"scale", "geometry", "openings", "heights"}
        if topology_evidence is not None:
            required_checks.update({"topology", "coverage"})
        if not isinstance(checks, dict) or set(checks) != required_checks or any(value is not True for value in checks.values()):
            raise InvalidModel(f"all review checks must be acknowledged: {', '.join(sorted(required_checks))}")
        ids = {item["id"] for key in ("rooms", "walls", "openings") for item in model[key]}
        if topology_evidence is not None:
            ids.update(room["merge_group_id"] for room in model["rooms"] if room.get("merge_group_id"))
        if (not isinstance(reviewed_object_ids, list)
                or any(not isinstance(value, str) for value in reviewed_object_ids)
                or len(reviewed_object_ids) != len(ids) or set(reviewed_object_ids) != ids):
            raise InvalidModel("every current room, wall and opening must be reviewed exactly once")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120:
            raise InvalidModel("reviewer must be a non-empty local display name of at most 120 characters")
        review = {
            "ingest_id": ingest_id, "source_sha256": model["source"]["sha256"],
            "draft_revision": model["revision"], "draft_hash": current["hash"],
            "reviewed_object_ids": sorted(ids), "checks": checks,
            "reviewer": reviewer.strip(), "identity_kind": "self_reported_local",
            "reviewed_at": datetime.now(UTC).isoformat(timespec="microseconds"),
        }
        if topology_evidence is not None:
            review["topology_confirmation"] = topology_evidence
        return self.append(model_id, model, expected_revision, expected_hash,
                           "Human reviewed bitmap geometry and scale", "confirm", review=review)

    def append(self, model_id: str, model: Any, expected_revision: int, expected_hash: str, note: str, action: str, *, review: dict[str, Any] | None = None) -> dict[str, Any]:
        checked_model(model, model_id)
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise InvalidModel("expected_revision must be a positive integer")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
            raise InvalidModel("expected_hash must be a lowercase SHA-256 hash")
        if not isinstance(note, str) or len(note) > 2000:
            raise InvalidModel("note must be a string of at most 2000 characters")
        if not isinstance(action, str) or action not in {"save", "confirm"}:
            raise InvalidModel("action must be 'save' or 'confirm'")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = self._latest(db, model_id)
                if expected_revision != current["model"]["revision"] or expected_hash != current["hash"]:
                    raise RevisionConflict(current)
                if current["model"]["source"]["kind"] == "bitmap":
                    if model["source"] != current["model"]["source"] or model.get("ingest") != current["model"].get("ingest"):
                        raise InvalidModel("bitmap source and calibration evidence are immutable; reimport to recalibrate")
                    if action == "confirm" and review is None:
                        raise InvalidModel("bitmap confirmation requires the ingest review endpoint")
                if model["revision"] > expected_revision:
                    raise InvalidModel("model.revision cannot refer to a future revision")
                source = db.execute("SELECT * FROM revisions WHERE model_id = ? AND revision = ?", (model_id, model["revision"])).fetchone()
                if source is None:
                    raise InvalidModel("model.revision must identify an existing source revision; the server assigns the new revision")
                self._envelope(source)
                # Historical restore uses old content with current CAS, never rewinds history.
                candidate = {**model, "revision": expected_revision + 1, "status": "confirmed" if action == "confirm" else "draft"}
                candidate.pop("review", None)
                if review is not None:
                    candidate["review"] = review
                if current["model"]["source"]["kind"] == "bitmap":
                    # Recognition confidence stays historical evidence; the
                    # human review state belongs to this specific revision.
                    for collection in ("rooms", "walls", "openings"):
                        candidate[collection] = []
                        for item in model[collection]:
                            reviewed_item = {**item, "needs_review": review is None}
                            for evidence in ("dimension_provenance", "height_provenance"):
                                if isinstance(item.get(evidence), dict):
                                    reviewed_item[evidence] = {**item[evidence], "needs_review": review is None}
                            candidate[collection].append(reviewed_item)
                checked_model(candidate, model_id)
                result = self._insert(db, candidate, note)
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise
