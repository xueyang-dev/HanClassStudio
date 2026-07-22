"""Teacher-approved video generation, crash recovery, and asset registration."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .ffmpeg_video import (
    RECIPE_ID,
    RECIPE_VERSION,
    FfmpegCapability,
    FfmpegVideoError,
    SourceAssetProvenance,
    TeachingVideoPlan,
    VerifiedVideoArtifact,
    _verify_video,
    _verify_webvtt,
    compile_teaching_video_plan,
    execute_compiled_video_plan,
    probe_ffmpeg,
    rendering_environment_from_capability,
)
from .models import (
    AssetFile,
    AssetManifest,
    TeacherMediaApproval,
    VideoArtifactRecord,
    VideoAssetReference,
    VideoGenerationFailureRecord,
    VideoInputAssetRecord,
    VideoRenderingEnvironment,
    utc_now_iso,
)


PROVENANCE_SCHEMA_VERSION = 2
JOURNAL_SCHEMA_VERSION = 1
SUPPORTED_VIDEO_RECIPES = {(RECIPE_ID, RECIPE_VERSION)}
PublicationPhase = Literal[
    "prepared",
    "artifacts_published",
    "provenance_published",
    "manifest_committed",
    "completed",
]
RecoveryAction = Literal["none", "cleaned", "registered", "regeneration_required"]


class TeachingVideoProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    plan: TeachingVideoPlan
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendering_environment: VideoRenderingEnvironment
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
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    proposal: TeachingVideoProposal
    approval: TeacherMediaApproval | None = None
    requested_at: str = Field(default_factory=utc_now_iso)


class VideoPublicationTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = JOURNAL_SCHEMA_VERSION
    transaction_id: str
    asset_id: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase: PublicationPhase = "prepared"
    staging_paths: list[str]
    final_paths: list[str]
    expected_hashes: dict[str, str | None]
    artifact_record: VideoArtifactRecord | None = None
    reference: VideoAssetReference | None = None
    approval: TeacherMediaApproval | None = None
    recovery_action: RecoveryAction = "none"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


VideoGenerationResult = VideoArtifactRecord | VideoGenerationFailureRecord
_video_generation_lock = threading.RLock()


def create_teaching_video_proposal(
    project_root: Path,
    plan: TeachingVideoPlan | dict,
    *,
    teaching_unit_id: str | None = None,
    activity_id: str | None = None,
    media_requirement_id: str | None = None,
    capability: FfmpegCapability | None = None,
) -> TeachingVideoProposal:
    compiled = compile_teaching_video_plan(project_root, plan)
    validated = plan if isinstance(plan, TeachingVideoPlan) else TeachingVideoPlan.model_validate(plan)
    selected = capability or probe_ffmpeg()
    if not selected.available:
        raise FfmpegVideoError("ffmpeg_failed", ", ".join(selected.blockers) or "video capability is unavailable")
    environment = rendering_environment_from_capability(selected)
    return TeachingVideoProposal(
        proposal_id=f"video-proposal-{validated.video_id}-{compiled.plan_sha256[:16]}",
        plan=validated,
        plan_sha256=compiled.plan_sha256,
        source_plan_sha256=compiled.source_plan_sha256,
        rendering_environment=environment,
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
    return TeacherMediaApproval(
        approval_id=f"video-approval-{uuid.uuid4().hex}",
        proposal_id=proposal.proposal_id,
        approved_plan_sha256=proposal.plan_sha256,
        approved_rendering_environment_sha256=proposal.rendering_environment.fingerprint_sha256,
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
    with _video_generation_lock:
        return _execute_video_generation_request(Path(project_root).resolve(), request)


def _execute_video_generation_request(root: Path, request: VideoGenerationRequest) -> VideoGenerationResult:
    proposal = request.proposal
    approval = request.approval
    if approval is None:
        return _fail(root, request, "approval_required", "approval", "Teacher approval is required before execution")
    try:
        compiled = compile_teaching_video_plan(root, proposal.plan)
    except FfmpegVideoError as exc:
        return _stale(root, request, approval, f"plan_recompile_failed:{exc.code}")

    capability = probe_ffmpeg()
    if not capability.available:
        return _fail(
            root, request, "capability_unavailable", "preflight",
            "Controlled FFmpeg capability is unavailable: " + ", ".join(capability.blockers),
            plan_sha256=compiled.plan_sha256,
        )
    try:
        current_environment = rendering_environment_from_capability(capability)
    except FfmpegVideoError:
        return _fail(
            root, request, "capability_unavailable", "preflight",
            "Controlled rendering environment is incomplete", plan_sha256=compiled.plan_sha256,
        )
    stale_reason = _approval_stale_reason(request, compiled.plan_sha256, current_environment)
    if stale_reason:
        return _stale(root, request, approval, stale_reason, plan_sha256=compiled.plan_sha256)

    recover_video_publication_transactions(root, capability=capability)
    try:
        manifest = _read_manifest(root)
    except (OSError, ValueError) as exc:
        return _fail(
            root, request, "registration_failed", "registration",
            f"Asset Manifest cannot be loaded: {type(exc).__name__}", plan_sha256=compiled.plan_sha256,
        )

    deduplication_key = _deduplication_key(
        compiled.plan_sha256,
        compiled.source_assets,
        current_environment.fingerprint_sha256,
    )
    for asset in manifest.video:
        record = asset.video_artifact
        if record and record.deduplication_key == deduplication_key:
            if not _registered_artifact_is_valid(root, asset, record, capability):
                return _fail(
                    root, request, "regeneration_required", "preflight",
                    "A matching registered artifact failed semantic verification",
                    plan_sha256=compiled.plan_sha256,
                )
            try:
                _register_reference(manifest, asset, proposal, approval, record.artifact_id)
                _write_manifest(root, manifest)
            except (OSError, ValueError) as exc:
                return _fail(
                    root, request, "registration_failed", "registration",
                    f"A reused artifact could not be linked: {type(exc).__name__}",
                    plan_sha256=compiled.plan_sha256,
                )
            return record.model_copy(update={"generation_status": "reused"})
        legacy = asset.video_generation
        if legacy and legacy.deduplication_key == deduplication_key:
            return _fail(
                root, request, "regeneration_required", "preflight",
                "A legacy video record must be regenerated under the current verification contract",
                plan_sha256=compiled.plan_sha256,
            )

    if any(asset.id == compiled.video_id for group in (manifest.images, manifest.audio, manifest.video, manifest.fonts) for asset in group):
        return _fail(
            root, request, "asset_id_conflict", "preflight",
            f"Asset ID {compiled.video_id} is already registered for a different artifact",
            plan_sha256=compiled.plan_sha256,
        )
    provenance_ref = f"assets/data/video/{compiled.video_id}.provenance.json"
    final_paths = [compiled.video_path, compiled.subtitle_path, provenance_ref]
    if any((root / path).exists() for path in final_paths):
        return _fail(
            root, request, "orphan_detected", "preflight",
            f"Unregistered files already exist for asset ID {compiled.video_id}; recovery or cleanup is required",
            plan_sha256=compiled.plan_sha256,
        )

    try:
        transaction = _prepare_transaction(root, compiled.video_id, compiled.plan_sha256, final_paths)
    except Exception as exc:
        return _fail(
            root, request, "registration_failed", "registration",
            f"Publication journal could not be prepared: {type(exc).__name__}",
            plan_sha256=compiled.plan_sha256,
        )
    try:
        artifact = execute_compiled_video_plan(
            root,
            compiled,
            capability=capability,
            transaction_id=transaction.transaction_id,
        )
    except FfmpegVideoError as exc:
        if _cleanup_transaction_files(root, transaction):
            try:
                _advance_transaction(root, transaction, "completed", recovery_action="cleaned")
            except OSError:
                pass
        return _fail(
            root, request, "generation_failed", "generation",
            f"Controlled video generation failed: {exc.code}", plan_sha256=compiled.plan_sha256,
        )

    reference = _video_reference(proposal, approval, artifact.artifact_id)
    provenance_payload = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "proposal_id": proposal.proposal_id,
        "artifact": artifact.model_dump(mode="json"),
    }
    provenance_bytes = _json_bytes(provenance_payload)
    record = _artifact_record(artifact, compiled.subtitle_cues, provenance_ref, provenance_bytes, deduplication_key)
    try:
        transaction = _advance_transaction(
            root,
            transaction,
            "artifacts_published",
            artifact_record=record,
            reference=reference,
            approval=approval,
            expected_hashes={
                "video": record.artifact_sha256,
                "subtitle": record.subtitle_sha256,
                "provenance": record.provenance_sha256,
            },
        )
    except Exception as exc:
        _cleanup_transaction_files(root, transaction)
        return _fail(
            root, request, "registration_failed", "registration",
            f"Publication journal could not be updated: {type(exc).__name__}",
            plan_sha256=compiled.plan_sha256,
        )
    try:
        _atomic_write_bytes(root / provenance_ref, provenance_bytes)
        transaction = _advance_transaction(root, transaction, "provenance_published")
        asset = AssetFile(
            id=record.artifact_id,
            kind="video",
            path=record.video_path,
            placeholder=False,
            media_request_id=proposal.media_requirement_id,
            origin_media_requirement_ids=[proposal.media_requirement_id] if proposal.media_requirement_id else [],
            mime_type="video/mp4",
            content_hash=record.artifact_sha256,
            video_artifact=record,
        )
        manifest.video.append(asset)
        _register_reference(manifest, asset, proposal, approval, record.artifact_id)
        _write_manifest(root, manifest)
        transaction = _advance_transaction(root, transaction, "manifest_committed")
        _advance_transaction(root, transaction, "completed")
    except Exception as exc:
        recover_video_publication_transactions(root, capability=capability)
        return _fail(
            root, request, "registration_failed", "registration",
            f"Generated files could not be registered: {type(exc).__name__}", plan_sha256=compiled.plan_sha256,
        )
    return record


def recover_video_publication_transactions(
    project_root: Path,
    *,
    capability: FfmpegCapability | None = None,
) -> list[VideoPublicationTransaction]:
    root = Path(project_root).resolve()
    journal_dir = root / "assets/data/video_transactions"
    if not journal_dir.exists():
        return []
    try:
        manifest = _read_manifest(root)
    except (OSError, ValueError):
        return []
    recovered: list[VideoPublicationTransaction] = []
    for path in sorted(journal_dir.glob("*.json")):
        try:
            transaction = VideoPublicationTransaction.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if transaction.phase == "completed":
            continue
        asset = next((item for item in manifest.video if item.id == transaction.asset_id), None)
        if asset is not None:
            record = asset.video_artifact
            if capability is None or not capability.available:
                continue
            if (
                record
                and _transaction_matches_manifest(transaction, manifest, asset, record)
                and _registered_artifact_is_valid(
                    root, asset, record, capability, require_current_environment=False,
                )
            ):
                try:
                    transaction = _advance_transaction(
                        root, transaction, "completed", recovery_action="registered",
                    )
                except OSError:
                    continue
            else:
                try:
                    transaction = _advance_transaction(
                        root, transaction, "completed", recovery_action="regeneration_required",
                    )
                except OSError:
                    continue
        else:
            if not _cleanup_transaction_files(root, transaction):
                continue
            try:
                transaction = _advance_transaction(root, transaction, "completed", recovery_action="cleaned")
            except OSError:
                continue
        recovered.append(transaction)
    return recovered


def _transaction_matches_manifest(
    transaction: VideoPublicationTransaction,
    manifest: AssetManifest,
    asset: AssetFile,
    record: VideoArtifactRecord,
) -> bool:
    if (
        transaction.asset_id != record.artifact_id
        or transaction.plan_sha256 != record.plan_sha256
        or transaction.artifact_record != record
        or transaction.expected_hashes != {
            "video": record.artifact_sha256,
            "subtitle": record.subtitle_sha256,
            "provenance": record.provenance_sha256,
        }
        or set(transaction.final_paths) != {
            record.video_path,
            record.subtitle_path,
            record.provenance_ref,
        }
        or asset.video_artifact != record
        or transaction.reference is None
        or transaction.approval is None
    ):
        return False
    manifest_reference = next(
        (item for item in manifest.video_references if item.reference_id == transaction.reference.reference_id),
        None,
    )
    manifest_approval = next(
        (item for item in manifest.video_approvals if item.approval_id == transaction.approval.approval_id),
        None,
    )
    return bool(
        manifest_reference
        and manifest_reference.model_dump(exclude={"created_at"})
        == transaction.reference.model_dump(exclude={"created_at"})
        and manifest_approval == transaction.approval
    )


def _approval_stale_reason(
    request: VideoGenerationRequest,
    current_plan_sha256: str,
    current_environment: VideoRenderingEnvironment,
) -> str | None:
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
    expected_environment = request.proposal.rendering_environment.fingerprint_sha256
    if expected_environment != current_environment.fingerprint_sha256:
        return "rendering_environment_changed"
    if approval.approved_rendering_environment_sha256 != current_environment.fingerprint_sha256:
        return "approved_rendering_environment_changed"
    return None


def _stale(
    root: Path,
    request: VideoGenerationRequest,
    approval: TeacherMediaApproval,
    reason: str,
    *,
    plan_sha256: str | None = None,
) -> VideoGenerationFailureRecord:
    stale = approval.model_copy(update={"approval_status": "stale", "stale_reason": reason})
    return _fail(
        root,
        request,
        "approval_stale",
        "approval",
        "The current plan or rendering environment no longer matches teacher approval",
        plan_sha256=plan_sha256,
        approval=stale,
    )


def _deduplication_key(
    plan_sha256: str,
    inputs: list[SourceAssetProvenance],
    rendering_environment_sha256: str,
) -> str:
    payload = {
        "plan_sha256": plan_sha256,
        "recipe_id": RECIPE_ID,
        "recipe_version": RECIPE_VERSION,
        "rendering_environment_sha256": rendering_environment_sha256,
        "input_assets": [
            {"asset_id": item.asset_id, "kind": item.kind, "sha256": item.sha256}
            for item in inputs
        ],
    }
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _artifact_record(
    artifact: VerifiedVideoArtifact,
    cues: list,
    provenance_ref: str,
    provenance_bytes: bytes,
    deduplication_key: str,
) -> VideoArtifactRecord:
    return VideoArtifactRecord(
        generation_status="generated",
        artifact_id=artifact.artifact_id,
        video_path=artifact.video_path,
        subtitle_path=artifact.subtitle_path,
        plan_sha256=artifact.plan_sha256,
        artifact_sha256=artifact.video_sha256,
        subtitle_sha256=artifact.subtitle_sha256,
        subtitle_cue_count=len(cues),
        input_assets=[_input_record(item) for item in artifact.source_assets],
        recipe_id=artifact.recipe_id,
        recipe_version=RECIPE_VERSION,
        duration_seconds=artifact.duration_seconds,
        width=artifact.width,
        height=artifact.height,
        video_codec=artifact.video_codec,
        audio_codec=artifact.audio_codec,
        rendering_environment=artifact.rendering_environment,
        provenance_schema_version=PROVENANCE_SCHEMA_VERSION,
        provenance_ref=provenance_ref,
        provenance_sha256=hashlib.sha256(provenance_bytes).hexdigest(),
        deduplication_key=deduplication_key,
    )


def _input_record(item: SourceAssetProvenance) -> VideoInputAssetRecord:
    return VideoInputAssetRecord(
        segment_id=item.segment_id,
        asset_id=item.asset_id,
        kind=item.kind,
        path=item.path,
        sha256=item.sha256,
    )


def _video_reference(
    proposal: TeachingVideoProposal,
    approval: TeacherMediaApproval,
    artifact_id: str,
) -> VideoAssetReference:
    payload = {
        "artifact_id": artifact_id,
        "approval_id": approval.approval_id,
        "unit_id": proposal.teaching_unit_id,
        "activity_id": proposal.activity_id,
        "media_requirement_id": proposal.media_requirement_id,
    }
    return VideoAssetReference(
        reference_id="video-ref-" + hashlib.sha256(_json_bytes(payload)).hexdigest()[:24],
        **payload,
    )


def _register_reference(
    manifest: AssetManifest,
    asset: AssetFile,
    proposal: TeachingVideoProposal,
    approval: TeacherMediaApproval,
    artifact_id: str,
) -> VideoAssetReference:
    existing_approval = next(
        (item for item in manifest.video_approvals if item.approval_id == approval.approval_id),
        None,
    )
    if existing_approval is not None and existing_approval != approval:
        raise ValueError("approval ID collision")
    if existing_approval is None:
        manifest.video_approvals.append(approval)
    reference = _video_reference(proposal, approval, artifact_id)
    existing_reference = next(
        (item for item in manifest.video_references if item.reference_id == reference.reference_id),
        None,
    )
    if existing_reference is not None:
        if existing_reference.model_dump(exclude={"created_at"}) != reference.model_dump(exclude={"created_at"}):
            raise ValueError("video reference ID collision")
        reference = existing_reference
    else:
        manifest.video_references.append(reference)
    if proposal.media_requirement_id and proposal.media_requirement_id not in asset.origin_media_requirement_ids:
        asset.origin_media_requirement_ids.append(proposal.media_requirement_id)
    return reference


def _registered_artifact_is_valid(
    root: Path,
    asset: AssetFile,
    record: VideoArtifactRecord,
    capability: FfmpegCapability,
    *,
    require_current_environment: bool = True,
) -> bool:
    if (
        asset.kind != "video"
        or asset.path != record.video_path
        or asset.content_hash != record.artifact_sha256
        or (record.recipe_id, record.recipe_version) not in SUPPORTED_VIDEO_RECIPES
        or record.provenance_schema_version != PROVENANCE_SCHEMA_VERSION
        or not capability.probe_executable
    ):
        return False
    if require_current_environment:
        try:
            current = rendering_environment_from_capability(capability)
        except FfmpegVideoError:
            return False
        if current.fingerprint_sha256 != record.rendering_environment.fingerprint_sha256:
            return False
    checks = (
        (record.video_path, record.artifact_sha256, "assets/video"),
        (record.subtitle_path, record.subtitle_sha256, "assets/video"),
        (record.provenance_ref, record.provenance_sha256, "assets/data"),
    )
    resolved: list[Path] = []
    try:
        for relative, expected_hash, allowed_prefix in checks:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or not path.as_posix().startswith(allowed_prefix + "/"):
                return False
            target = root / path
            if not target.is_file() or _sha256(target) != expected_hash:
                return False
            resolved.append(target)
        payload = json.loads(resolved[2].read_text(encoding="utf-8"))
        if payload.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
            return False
        verified = VerifiedVideoArtifact.model_validate(payload.get("artifact"))
        if (
            verified.artifact_id != record.artifact_id
            or verified.video_path != record.video_path
            or verified.subtitle_path != record.subtitle_path
            or verified.video_sha256 != record.artifact_sha256
            or verified.subtitle_sha256 != record.subtitle_sha256
            or verified.plan_sha256 != record.plan_sha256
            or verified.recipe_id != record.recipe_id
            or verified.duration_seconds != record.duration_seconds
            or verified.width != record.width
            or verified.height != record.height
            or verified.video_codec != record.video_codec
            or verified.audio_codec != record.audio_codec
            or verified.rendering_environment != record.rendering_environment
            or [_input_record(item) for item in verified.source_assets] != record.input_assets
        ):
            return False
        _verify_webvtt(resolved[1], record.subtitle_cue_count)
        metadata = _verify_video(resolved[0], record.duration_seconds, capability.probe_executable)
        return (
            metadata["width"] == record.width
            and metadata["height"] == record.height
            and metadata["video_codec"] == record.video_codec
            and metadata["audio_codec"] == record.audio_codec
        )
    except (FfmpegVideoError, OSError, UnicodeError, ValueError, ValidationError, json.JSONDecodeError):
        return False


def _prepare_transaction(
    root: Path,
    asset_id: str,
    plan_sha256: str,
    final_paths: list[str],
) -> VideoPublicationTransaction:
    transaction_id = f"video-txn-{uuid.uuid4().hex}"
    transaction = VideoPublicationTransaction(
        transaction_id=transaction_id,
        asset_id=asset_id,
        plan_sha256=plan_sha256,
        staging_paths=[f"assets/video/.{asset_id}-{transaction_id}-*"],
        final_paths=final_paths,
        expected_hashes={"video": None, "subtitle": None, "provenance": None},
    )
    _write_transaction(root, transaction)
    return transaction


def _advance_transaction(
    root: Path,
    transaction: VideoPublicationTransaction,
    phase: PublicationPhase,
    **updates: object,
) -> VideoPublicationTransaction:
    advanced = transaction.model_copy(update={"phase": phase, "updated_at": utc_now_iso(), **updates})
    _write_transaction(root, advanced)
    return advanced


def _cleanup_transaction_files(root: Path, transaction: VideoPublicationTransaction) -> bool:
    cleaned = True
    for relative in transaction.final_paths:
        path = Path(relative)
        if not path.is_absolute() and ".." not in path.parts:
            try:
                (root / path).unlink(missing_ok=True)
            except OSError:
                cleaned = False
    for pattern in transaction.staging_paths:
        path = Path(pattern)
        if path.is_absolute() or ".." in path.parts:
            continue
        for candidate in root.glob(pattern):
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)
                if candidate.exists():
                    cleaned = False
    return cleaned


def _transaction_path(root: Path, transaction_id: str) -> Path:
    return root / f"assets/data/video_transactions/{transaction_id}.json"


def _write_transaction(root: Path, transaction: VideoPublicationTransaction) -> None:
    _atomic_write_bytes(
        _transaction_path(root, transaction.transaction_id),
        _json_bytes(transaction.model_dump(mode="json")),
    )


def _read_manifest(root: Path) -> AssetManifest:
    path = root / "assets/data/asset_manifest.json"
    if not path.exists():
        return AssetManifest()
    return AssetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _write_manifest(root: Path, manifest: AssetManifest) -> None:
    _atomic_write_bytes(
        root / "assets/data/asset_manifest.json",
        _json_bytes(manifest.model_dump(mode="json")),
    )


def _fail(
    root: Path,
    request: VideoGenerationRequest,
    code: Literal[
        "approval_required", "approval_stale", "invalid_plan", "capability_unavailable",
        "generation_failed", "registration_failed", "regeneration_required", "asset_id_conflict",
        "orphan_detected",
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
