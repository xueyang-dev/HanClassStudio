"""Teacher-approved teaching-video generation and Asset Manifest registration.

This is the project-facing workflow. The FFmpeg module remains a controlled
compiler/executor; callers must use this module to obtain a registered asset.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ffmpeg_video import (
    RECIPE_VERSION,
    FfmpegVideoError,
    SourceAssetProvenance,
    TeachingVideoPlan,
    compile_teaching_video_plan,
    execute_compiled_video_plan,
    probe_ffmpeg,
)
from .models import (
    AssetFile,
    AssetManifest,
    GeneratedVideoAssetRecord,
    TeacherMediaApproval,
    VideoGenerationFailureRecord,
    VideoInputAssetRecord,
    utc_now_iso,
)


class TeachingVideoProposal(BaseModel):
    """Reviewable proposal compiled from a teaching-video draft."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    plan: TeachingVideoPlan
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teaching_unit_id: str | None = None
    activity_id: str | None = None
    media_requirement_id: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def _has_teaching_context(self) -> "TeachingVideoProposal":
        if not any((self.teaching_unit_id, self.activity_id, self.media_requirement_id)):
            raise ValueError("a teaching unit, activity, or media requirement ID is required")
        return self


class VideoGenerationRequest(BaseModel):
    """Explicit request; construction does not imply approval or execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    proposal: TeachingVideoProposal
    approval: TeacherMediaApproval | None = None
    requested_at: str = Field(default_factory=utc_now_iso)


VideoGenerationResult = GeneratedVideoAssetRecord | VideoGenerationFailureRecord


def create_teaching_video_proposal(
    project_root: Path,
    plan: TeachingVideoPlan | dict,
    *,
    teaching_unit_id: str | None = None,
    activity_id: str | None = None,
    media_requirement_id: str | None = None,
) -> TeachingVideoProposal:
    compiled = compile_teaching_video_plan(project_root, plan)
    validated = plan if isinstance(plan, TeachingVideoPlan) else TeachingVideoPlan.model_validate(plan)
    return TeachingVideoProposal(
        proposal_id=f"video-proposal-{validated.video_id}-{compiled.plan_sha256[:16]}",
        plan=validated,
        plan_sha256=compiled.plan_sha256,
        source_plan_sha256=compiled.source_plan_sha256,
        teaching_unit_id=teaching_unit_id,
        activity_id=activity_id,
        media_requirement_id=media_requirement_id,
    )


def approve_teaching_video_proposal(
    proposal: TeachingVideoProposal,
    *,
    teacher_id: str,
    notes: str = "",
) -> TeacherMediaApproval:
    """Create the explicit teacher evidence; never called by plan generation."""

    return TeacherMediaApproval(
        approval_id=f"video-approval-{uuid.uuid4().hex}",
        proposal_id=proposal.proposal_id,
        approved_plan_sha256=proposal.plan_sha256,
        teacher_id=teacher_id,
        notes=notes,
    )


def create_video_generation_request(
    proposal: TeachingVideoProposal,
    approval: TeacherMediaApproval | None = None,
) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        request_id=f"video-request-{uuid.uuid4().hex}",
        proposal=proposal,
        approval=approval,
    )


def execute_video_generation_request(project_root: Path, request: VideoGenerationRequest) -> VideoGenerationResult:
    """Recompile, verify approval, deduplicate, execute, and register atomically."""

    root = Path(project_root).resolve()
    proposal = request.proposal
    approval = request.approval
    if approval is None:
        return _fail(root, request, "approval_required", "approval", "Teacher approval is required before execution")
    try:
        compiled = compile_teaching_video_plan(root, proposal.plan)
    except FfmpegVideoError as exc:
        stale = approval.model_copy(update={
            "approval_status": "stale",
            "stale_reason": f"plan_recompile_failed:{exc.code}",
        })
        return _fail(
            root,
            request,
            "approval_stale",
            "approval",
            "The approved plan can no longer be reproduced; teacher approval is stale",
            approval=stale,
        )

    stale_reason = _approval_stale_reason(request, compiled.plan_sha256)
    if stale_reason:
        stale = approval.model_copy(update={"approval_status": "stale", "stale_reason": stale_reason})
        return _fail(
            root,
            request,
            "approval_stale",
            "approval",
            "The current compiled plan does not match the teacher-approved plan hash",
            plan_sha256=compiled.plan_sha256,
            approval=stale,
        )

    try:
        manifest = _read_manifest(root)
    except (OSError, ValueError) as exc:
        return _fail(
            root, request, "registration_failed", "registration",
            f"Asset Manifest cannot be loaded: {type(exc).__name__}", plan_sha256=compiled.plan_sha256,
        )

    deduplication_key = _deduplication_key(compiled.plan_sha256, compiled.source_assets)
    for asset in manifest.video:
        record = asset.video_generation
        if record and record.deduplication_key == deduplication_key:
            if _registered_asset_is_valid(root, asset):
                return record.model_copy(update={
                    "generation_status": "reused",
                    "teacher_approval": approval,
                })
            return _fail(
                root, request, "regeneration_required", "preflight",
                "A matching registered artifact is missing or corrupt; explicit regeneration is required",
                plan_sha256=compiled.plan_sha256,
            )

    if any(asset.id == compiled.video_id for group in (manifest.images, manifest.audio, manifest.video, manifest.fonts) for asset in group):
        return _fail(
            root, request, "asset_id_conflict", "preflight",
            f"Asset ID {compiled.video_id} is already registered for a different artifact",
            plan_sha256=compiled.plan_sha256,
        )
    reserved_provenance = root / f"assets/data/video/{compiled.video_id}.provenance.json"
    if reserved_provenance.exists():
        return _fail(
            root, request, "asset_id_conflict", "preflight",
            f"Provenance for asset ID {compiled.video_id} already exists without a matching manifest record",
            plan_sha256=compiled.plan_sha256,
        )

    capability = probe_ffmpeg()
    if not capability.available:
        return _fail(
            root, request, "capability_unavailable", "preflight",
            "Controlled FFmpeg capability is unavailable: " + ", ".join(capability.blockers),
            plan_sha256=compiled.plan_sha256,
        )

    try:
        artifact = execute_compiled_video_plan(root, compiled)
    except FfmpegVideoError as exc:
        return _fail(
            root, request, "generation_failed", "generation",
            f"Controlled video generation failed: {exc.code}", plan_sha256=compiled.plan_sha256,
        )

    provenance_ref = f"assets/data/video/{artifact.artifact_id}.provenance.json"
    provenance_path = root / provenance_ref
    provenance_payload = {
        "schema_version": 1,
        "proposal_id": proposal.proposal_id,
        "teaching_context": {
            "teaching_unit_id": proposal.teaching_unit_id,
            "activity_id": proposal.activity_id,
            "media_requirement_id": proposal.media_requirement_id,
        },
        "teacher_approval": approval.model_dump(mode="json"),
        "artifact": artifact.model_dump(mode="json"),
    }
    provenance_bytes = _json_bytes(provenance_payload)
    record = GeneratedVideoAssetRecord(
        generation_status="generated",
        asset_id=artifact.artifact_id,
        video_path=artifact.video_path,
        subtitle_path=artifact.subtitle_path,
        plan_sha256=artifact.plan_sha256,
        artifact_sha256=artifact.video_sha256,
        subtitle_sha256=artifact.subtitle_sha256,
        input_assets=[_input_record(item) for item in artifact.source_assets],
        recipe_id=artifact.recipe_id,
        recipe_version=RECIPE_VERSION,
        duration_seconds=artifact.duration_seconds,
        width=artifact.width,
        height=artifact.height,
        video_codec=artifact.video_codec,
        audio_codec=artifact.audio_codec,
        subtitle_font_family=artifact.provenance.subtitle_font.family,
        subtitle_font_sha256=artifact.provenance.subtitle_font.sha256,
        provenance_ref=provenance_ref,
        provenance_sha256=hashlib.sha256(provenance_bytes).hexdigest(),
        teacher_approval=approval,
        deduplication_key=deduplication_key,
        teaching_unit_id=proposal.teaching_unit_id,
        activity_id=proposal.activity_id,
        media_requirement_id=proposal.media_requirement_id,
    )
    manifest.video.append(AssetFile(
        id=record.asset_id,
        kind="video",
        path=record.video_path,
        placeholder=False,
        media_request_id=proposal.media_requirement_id,
        origin_media_requirement_ids=[proposal.media_requirement_id] if proposal.media_requirement_id else [],
        mime_type="video/mp4",
        content_hash=record.artifact_sha256,
        video_generation=record,
    ))
    try:
        _atomic_write_bytes(provenance_path, provenance_bytes)
        _atomic_write_bytes(root / "assets/data/asset_manifest.json", _json_bytes(manifest.model_dump(mode="json")))
    except OSError as exc:
        (root / artifact.video_path).unlink(missing_ok=True)
        (root / artifact.subtitle_path).unlink(missing_ok=True)
        provenance_path.unlink(missing_ok=True)
        return _fail(
            root, request, "registration_failed", "registration",
            f"Generated files could not be registered: {type(exc).__name__}", plan_sha256=compiled.plan_sha256,
        )
    return record


def _approval_stale_reason(request: VideoGenerationRequest, current_plan_sha256: str) -> str | None:
    approval = request.approval
    if approval is None:
        return "approval_missing"
    if approval.approval_status != "approved":
        return f"approval_status:{approval.approval_status}"
    if approval.proposal_id != request.proposal.proposal_id:
        return "proposal_id_changed"
    if request.proposal.plan_sha256 != current_plan_sha256:
        return "proposal_plan_changed"
    if approval.approved_plan_sha256 != current_plan_sha256:
        return "approved_plan_changed"
    return None


def _deduplication_key(plan_sha256: str, inputs: list[SourceAssetProvenance]) -> str:
    payload = {
        "plan_sha256": plan_sha256,
        "recipe_id": "hcs_teaching_video_720p_v1",
        "recipe_version": RECIPE_VERSION,
        "input_assets": [
            {"asset_id": item.asset_id, "kind": item.kind, "sha256": item.sha256}
            for item in inputs
        ],
    }
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _input_record(item: SourceAssetProvenance) -> VideoInputAssetRecord:
    return VideoInputAssetRecord(
        segment_id=item.segment_id,
        asset_id=item.asset_id,
        kind=item.kind,
        path=item.path,
        sha256=item.sha256,
    )


def _read_manifest(root: Path) -> AssetManifest:
    path = root / "assets/data/asset_manifest.json"
    if not path.exists():
        return AssetManifest()
    return AssetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _registered_asset_is_valid(root: Path, asset: AssetFile) -> bool:
    record = asset.video_generation
    if record is None or asset.kind != "video" or asset.content_hash != record.artifact_sha256:
        return False
    checks = (
        (record.video_path, record.artifact_sha256, "assets/video"),
        (record.subtitle_path, record.subtitle_sha256, "assets/video"),
        (record.provenance_ref, record.provenance_sha256, "assets/data"),
    )
    for relative, expected_hash, allowed_prefix in checks:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.as_posix().startswith(allowed_prefix + "/"):
            return False
        target = root / path
        if not target.is_file() or _sha256(target) != expected_hash:
            return False
    return True


def _fail(
    root: Path,
    request: VideoGenerationRequest,
    code: Literal[
        "approval_required", "approval_stale", "invalid_plan", "capability_unavailable",
        "generation_failed", "registration_failed", "regeneration_required", "asset_id_conflict",
    ],
    stage: Literal["approval", "preflight", "generation", "registration"],
    message: str,
    *,
    plan_sha256: str | None = None,
    approval: TeacherMediaApproval | None = None,
) -> VideoGenerationFailureRecord:
    failure = VideoGenerationFailureRecord(
        request_id=request.request_id,
        proposal_id=request.proposal.proposal_id,
        plan_sha256=plan_sha256 or request.proposal.plan_sha256,
        code=code,
        stage=stage,
        message=message,
        teacher_approval=approval or request.approval,
    )
    _record_failure(root, failure)
    return failure


def _record_failure(root: Path, failure: VideoGenerationFailureRecord) -> None:
    path = root / "assets/data/video_generation_failures.json"
    try:
        failures = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(failures, list):
            failures = []
        failures.append(failure.model_dump(mode="json"))
        _atomic_write_bytes(path, _json_bytes(failures))
    except (OSError, ValueError):
        pass


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
