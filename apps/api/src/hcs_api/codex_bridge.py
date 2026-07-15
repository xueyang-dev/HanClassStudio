"""Audited asynchronous bridge for a live Codex agent session.

The web process cannot call the model embedded in the Codex desktop session.
Instead it writes project-scoped, schema-bound jobs.  A live agent proves
presence with a short heartbeat, completes those jobs, and the normal pipeline
consumes the validated result on its next run.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import storage
from .models import LessonBlueprint, ProviderSettings
from .raster_provider import image_dimensions


BridgeCapability = Literal["llm", "image"]
BridgeJobState = Literal["pending", "completed"]
HEARTBEAT_TTL_SECONDS = 120
MAX_IMAGE_BYTES = 25 * 1024 * 1024
_SESSION_LOCK = threading.Lock()


class CodexBridgeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CodexBridgeActionRequired(RuntimeError):
    def __init__(self, job_ids: list[str]) -> None:
        self.job_ids = job_ids
        super().__init__(f"Codex agent action is required for jobs: {', '.join(job_ids)}")


class CodexBridgeHeartbeat(BaseModel):
    capabilities: list[BridgeCapability]


class CodexBridgeJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.codex_bridge_job.v1", alias="schema")
    job_id: str
    project_id: str
    capability: BridgeCapability
    operation: Literal["blueprint", "image"]
    state: BridgeJobState = "pending"
    fingerprint: str
    request: dict[str, Any]
    result_path: str | None = None
    result_mime_type: str | None = None
    created_at: str
    completed_at: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _sessions_path() -> Path:
    return storage.CONFIG_DIR / "codex_bridge_sessions.json"


def _read_sessions() -> dict[str, dict[str, Any]]:
    path = _sessions_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _configured_token(settings: ProviderSettings, capability: BridgeCapability) -> str:
    section = settings.llm if capability == "llm" else settings.image
    expected_provider = "codex_chatgpt" if capability == "llm" else "codex_image"
    return section.api_key.strip() if section.provider == expected_provider else ""


def authorize_token(settings: ProviderSettings, token: str) -> list[BridgeCapability]:
    if not token:
        raise CodexBridgeError("codex_bridge_unauthorized", "Missing Codex bridge token")
    authorized = [
        capability for capability in ("llm", "image")
        if (configured := _configured_token(settings, capability))
        and secrets.compare_digest(configured, token)
    ]
    if not authorized:
        raise CodexBridgeError("codex_bridge_unauthorized", "Invalid Codex bridge token")
    return authorized


def heartbeat(settings: ProviderSettings, token: str, capabilities: list[BridgeCapability]) -> dict[str, Any]:
    authorized = authorize_token(settings, token)
    requested = sorted(set(capabilities))
    if not requested or any(item not in authorized for item in requested):
        raise CodexBridgeError("codex_bridge_capability_denied", "Token is not configured for every requested capability")
    now = utc_now()
    expires_at = now + timedelta(seconds=HEARTBEAT_TTL_SECONDS)
    with _SESSION_LOCK:
        sessions = _read_sessions()
        sessions[_token_hash(token)] = {
            "capabilities": requested,
            "last_seen_at": _iso(now),
            "expires_at": _iso(expires_at),
        }
        _atomic_json(_sessions_path(), sessions)
    return {"capabilities": requested, "expires_at": _iso(expires_at)}


def is_active(capability: BridgeCapability, token: str) -> bool:
    if not token:
        return False
    session = _read_sessions().get(_token_hash(token))
    if not isinstance(session, dict) or capability not in session.get("capabilities", []):
        return False
    try:
        return datetime.fromisoformat(str(session["expires_at"])) > utc_now()
    except (KeyError, TypeError, ValueError):
        return False


def _job_dir(project_id: str) -> Path:
    return storage.ensure_project(project_id) / "agent" / "codex_bridge" / "jobs"


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _job_path(project_id: str, job_id: str) -> Path:
    return _job_dir(project_id) / f"{job_id}.json"


def _read_job(path: Path) -> CodexBridgeJob | None:
    try:
        return CodexBridgeJob.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def request_job(
    project_id: str,
    capability: BridgeCapability,
    operation: Literal["blueprint", "image"],
    request: dict[str, Any],
) -> CodexBridgeJob:
    payload = {"project_id": project_id, "capability": capability, "operation": operation, "request": request}
    fingerprint = _fingerprint(payload)
    job_id = f"{operation}-{fingerprint[:20]}"
    path = _job_path(project_id, job_id)
    existing = _read_job(path) if path.is_file() else None
    if existing and existing.fingerprint == fingerprint:
        return existing
    job = CodexBridgeJob(
        job_id=job_id,
        project_id=project_id,
        capability=capability,
        operation=operation,
        fingerprint=fingerprint,
        request=request,
        created_at=_iso(utc_now()),
    )
    _atomic_json(path, job.model_dump(mode="json", by_alias=True))
    return job


def pending_or_completed_jobs(state: BridgeJobState | None = None) -> list[CodexBridgeJob]:
    jobs: list[CodexBridgeJob] = []
    if not storage.PROJECTS_DIR.is_dir():
        return jobs
    for path in storage.PROJECTS_DIR.glob("*/agent/codex_bridge/jobs/*.json"):
        job = _read_job(path)
        if job and (state is None or job.state == state):
            jobs.append(job)
    return sorted(jobs, key=lambda item: item.created_at)


def get_job(job_id: str) -> CodexBridgeJob:
    matches = [job for job in pending_or_completed_jobs() if job.job_id == job_id]
    if len(matches) != 1:
        raise CodexBridgeError("codex_bridge_job_not_found", "Codex bridge job was not found")
    return matches[0]


def completed_json(job: CodexBridgeJob) -> dict[str, Any] | None:
    if job.state != "completed" or not job.result_path:
        return None
    path = storage.ensure_project(job.project_id) / job.result_path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def complete_blueprint(job: CodexBridgeJob, payload: dict[str, Any]) -> CodexBridgeJob:
    if job.capability != "llm" or job.operation != "blueprint":
        raise CodexBridgeError("codex_bridge_job_mismatch", "Job does not accept a Blueprint result")
    if job.state != "pending":
        raise CodexBridgeError("codex_bridge_job_completed", "Codex bridge job is already completed")
    blueprint = LessonBlueprint.model_validate(payload)
    relative = f"agent/codex_bridge/results/{job.job_id}.json"
    _atomic_json(storage.ensure_project(job.project_id) / relative, blueprint.model_dump(mode="json"))
    return _complete(job, relative, "application/json")


def complete_image(job: CodexBridgeJob, content: bytes, mime_type: str) -> CodexBridgeJob:
    if job.capability != "image" or job.operation != "image":
        raise CodexBridgeError("codex_bridge_job_mismatch", "Job does not accept an image result")
    if job.state != "pending":
        raise CodexBridgeError("codex_bridge_job_completed", "Codex bridge job is already completed")
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime_type)
    if not extension:
        raise CodexBridgeError("codex_bridge_image_invalid", "Codex bridge images must be PNG, JPEG, or WebP")
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise CodexBridgeError("codex_bridge_image_invalid", "Codex bridge images must be non-empty and no larger than 25 MB")
    try:
        image_dimensions(content, mime_type)
    except Exception as exc:
        raise CodexBridgeError("codex_bridge_image_invalid", str(exc)) from exc
    relative = f"agent/codex_bridge/results/{job.job_id}{extension}"
    path = storage.ensure_project(job.project_id) / relative
    _atomic_bytes(path, content)
    return _complete(job, relative, mime_type)


def _complete(job: CodexBridgeJob, result_path: str, mime_type: str) -> CodexBridgeJob:
    completed = job.model_copy(update={
        "state": "completed",
        "result_path": result_path,
        "result_mime_type": mime_type,
        "completed_at": _iso(utc_now()),
    })
    _atomic_json(_job_path(job.project_id, job.job_id), completed.model_dump(mode="json", by_alias=True))
    return completed


def completed_image(job: CodexBridgeJob) -> tuple[bytes, str] | None:
    if job.state != "completed" or not job.result_path or not job.result_mime_type:
        return None
    path = storage.ensure_project(job.project_id) / job.result_path
    if not path.is_file():
        return None
    content = path.read_bytes()
    try:
        image_dimensions(content, job.result_mime_type)
    except Exception:
        return None
    return content, job.result_mime_type
