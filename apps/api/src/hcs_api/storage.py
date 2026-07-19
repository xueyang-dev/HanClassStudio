from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .models import (
    AssetManifest,
    ArtifactEntry,
    ArtifactGroup,
    ArtifactTree,
    GateStatus,
    GateSummary,
    LessonBlueprint,
    LessonProfile,
    ProjectState,
    ProjectSummary,
    StageStatus,
    ProviderSettings,
    QualityReport,
    SourceMaterial,
    StaleState,
)


ROOT_DIR = Path(__file__).resolve().parents[4]
RUNTIME_DIR = Path(os.environ.get("HCS_RUNTIME_DIR", ROOT_DIR / "runtime"))
PROJECTS_DIR = RUNTIME_DIR / "projects"
CONFIG_DIR = RUNTIME_DIR / "config"
PROVIDER_SETTINGS_PATH = CONFIG_DIR / "provider_settings.json"

T = TypeVar("T", bound=BaseModel)

PROJECT_GROUPS = [
    "uploads",
    "sources",
    "analysis",
    "learning",
    "presentation",
    "specs",
    "blueprints",
    "assets",
    "courseware",
    "quality",
    "exports",
    "agent",
]

PROJECT_SUBDIRS = [
    "uploads",
    "sources",
    "analysis",
    "learning",
    "presentation",
    "specs",
    "blueprints",
    "assets/images",
    "assets/audio",
    "assets/video",
    "assets/fonts",
    "assets/data",
    "courseware",
    "quality",
    "exports",
    "agent",
    "backup",
]

EXPECTED_ARTIFACTS = {
    "sources": ["sources/source_material.json"],
    "learning": [
        "learning/learning_state_plan.json",
        "learning/evidence_plan.json",
        "learning/activity_plan.json",
    ],
    "presentation": [
        "presentation/activity_bindings.json",
        "presentation/binding_quality_report.json",
        "presentation/abstract_activity_bindings.json",
        "presentation/presentation_blueprint.json",
        "presentation/legacy_blueprint_from_v2.shadow.json",
        "presentation/legacy_component_mapping.shadow.json",
        "presentation/presentation_content_plan.json",
        "presentation/presentation_content_plan.reconciled.json",
        "presentation/presentation_media_request_plan.json",
        "presentation/presentation_media_asset_links.shadow.json",
        "presentation/presentation_media_projection_links.shadow.json",
    ],
    "specs": ["specs/lesson_spec.md", "specs/spec_lock.json"],
    "blueprints": [
        "blueprints/lesson_blueprint.json",
        "blueprints/interaction_plan.json",
        "blueprints/media_plan.json",
    ],
    "assets": [
        "assets/data/lesson_profile.json",
        "assets/data/asset_manifest.json",
        "assets/data/attribution.json",
    ],
    "courseware": ["courseware/lesson.html", "courseware/render_manifest.json"],
    "quality": [
        "quality/evidence_alignment_report.json",
        "quality/presentation_readiness_report.json",
        "quality/presentation_shadow_report.json",
        "quality/presentation_parity_report.json",
        "quality/presentation_adapter_assessment_report.json",
        "quality/presentation_content_report.json",
        "quality/presentation_asset_reconciliation_report.json",
        "quality/presentation_media_request_report.json",
        "quality/presentation_media_projection_report.json",
        "quality/quality_report.json",
        "quality/quality_summary.md",
        "quality/pptx_quality_report.json",
    ],
    "exports": ["exports/export_manifest.json", "exports/pptx_export_manifest.json"],
    "agent": ["agent/AGENT_TASK.md", "agent/AGENT_RULES.md"],
}


def ensure_runtime() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def create_project_id() -> str:
    ensure_runtime()
    return uuid.uuid4().hex[:12]


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def ensure_project(project_id: str) -> Path:
    root = project_dir(project_id)
    for subdir in PROJECT_SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)
    return root


MODEL_PATHS = {
    "source_material.json": Path("sources/source_material.json"),
    "lesson_profile.json": Path("assets/data/lesson_profile.json"),
    "lesson_blueprint.json": Path("blueprints/lesson_blueprint.json"),
    "asset_manifest.json": Path("assets/data/asset_manifest.json"),
    "quality_report.json": Path("quality/quality_report.json"),
    "classroom_quality_report.json": Path("quality/classroom_quality_report.json"),
}


def artifact_path(project_id: str, filename: str) -> Path:
    root = ensure_project(project_id)
    return root / MODEL_PATHS.get(filename, Path("assets/data") / filename)


def data_path(project_id: str, filename: str) -> Path:
    return artifact_path(project_id, filename)


def write_text(project_id: str, relative_path: str | Path, content: str) -> Path:
    path = ensure_project(project_id) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_json(project_id: str, relative_path: str | Path, payload: Any) -> Path:
    path = ensure_project(project_id) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(project_id: str, relative_path: str | Path) -> Any | None:
    path = ensure_project(project_id) / relative_path
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # A malformed historical artifact is unavailable evidence, not a
        # reason for project-state reads or export checks to return 500.
        return None


def write_model(project_id: str, filename: str, model: BaseModel) -> None:
    path = artifact_path(project_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_model(project_id: str, filename: str, model_type: type[T]) -> T | None:
    path = artifact_path(project_id, filename)
    legacy_path = ensure_project(project_id) / "assets" / "data" / filename
    if not path.exists() and legacy_path.exists():
        path = legacy_path
    if not path.exists():
        return None
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        # Treat malformed/legacy artifacts as missing so the authoritative
        # state can expose a structured blocker and require regeneration.
        return None


def project_revision(project_id: str) -> int:
    metadata = read_json(project_id, "assets/data/project_meta.json")
    if not isinstance(metadata, dict):
        return 0
    try:
        return max(0, int(metadata.get("project_revision", 0)))
    except (TypeError, ValueError):
        return 0


def bump_project_revision(project_id: str) -> int:
    revision = project_revision(project_id) + 1
    write_json(
        project_id,
        "assets/data/project_meta.json",
        {"project_revision": revision, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    return revision


def set_profile_state(project_id: str, state: str) -> None:
    if state not in {"inferred", "confirmed", "stale"}:
        raise ValueError(f"Unsupported profile state: {state}")
    write_json(
        project_id,
        "assets/data/profile_state.json",
        {"state": state, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


def read_profile_state(project_id: str, profile: LessonProfile | None) -> str:
    metadata = read_json(project_id, "assets/data/profile_state.json")
    state = metadata.get("state") if isinstance(metadata, dict) else None
    if state in {"inferred", "confirmed", "stale"}:
        return state
    return "inferred" if profile else "inferred"


def _stale_metadata(project_id: str) -> dict[str, Any]:
    payload = read_json(project_id, "assets/data/stale_state.json")
    return payload if isinstance(payload, dict) else {}


def update_stale_state(project_id: str, *, stale_stages: set[str], reason: str) -> None:
    current = _stale_metadata(project_id)
    stages = {str(item) for item in current.get("stale_stages", []) if item}
    stages.update(stale_stages)
    reasons = [str(item) for item in current.get("reasons", []) if item]
    if reason not in reasons:
        reasons.append(reason)
    write_json(
        project_id,
        "assets/data/stale_state.json",
        {
            "stale": bool(stages),
            "stale_stages": sorted(stages),
            "reasons": reasons[-20:],
            "changed_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def clear_stale_state(project_id: str, *, stages: set[str]) -> None:
    current = _stale_metadata(project_id)
    remaining = {str(item) for item in current.get("stale_stages", []) if item} - stages
    # A stale profile is a persisted business fact, not a transient UI label.
    # Downstream routes may clear their own completed work, but they cannot
    # clear the profile's stale marker before the teacher confirms it again.
    profile_meta = read_json(project_id, "assets/data/profile_state.json")
    if isinstance(profile_meta, dict) and profile_meta.get("state") == "stale":
        remaining.add("profile")
    reasons = [str(item) for item in current.get("reasons", []) if item]
    if "profile" in remaining and "Profile confirmation is stale; downstream artifacts require regeneration." not in reasons:
        reasons.append("Profile confirmation is stale; downstream artifacts require regeneration.")
    write_json(
        project_id,
        "assets/data/stale_state.json",
        {
            "stale": bool(remaining),
            "stale_stages": sorted(remaining),
            "reasons": reasons if remaining else [],
            "changed_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def invalidate_downstream(project_id: str, dependency: str, reason: str) -> None:
    """Mark current downstream artifacts stale without deleting historical evidence."""
    downstream = {
        "source": {"profile", "design", "presentation", "media", "render", "quality", "delivery"},
        "ocr": {"profile", "design", "presentation", "media", "render", "quality", "delivery"},
        "profile": {"design", "presentation", "media", "render", "quality", "delivery"},
        "design": {"presentation", "media", "render", "quality", "delivery"},
        "blueprint": {"media", "render", "quality", "delivery"},
        "media": {"render", "quality", "delivery"},
        "render": {"quality", "delivery"},
    }
    affected = downstream.get(dependency, set())
    if "profile" in affected and read_json(project_id, "assets/data/lesson_profile.json") is not None:
        set_profile_state(project_id, "stale")
    update_stale_state(project_id, stale_stages=affected, reason=reason)


def _effective_stale_state(
    project_id: str,
    *,
    source: SourceMaterial | None,
    profile: LessonProfile | None,
    blueprint: LessonBlueprint | None,
    lesson_exists: bool,
    export_exists: bool,
    stored: StaleState,
) -> StaleState:
    """Resolve persisted stale facts without rewriting legacy project files."""
    stages = set(stored.stale_stages)
    reasons = list(stored.reasons)
    profile_state = read_profile_state(project_id, profile)
    all_downstream = {"profile", "design", "presentation", "media", "render", "quality", "delivery"}
    if profile_state == "stale":
        stages.update(all_downstream)
        if "Profile confirmation is stale; downstream artifacts require regeneration." not in reasons:
            reasons.append("Profile confirmation is stale; downstream artifacts require regeneration.")

    # Projects created before project_meta.json existed have no trustworthy
    # dependency lineage.  Preserve their files for historical evidence, but
    # never present their generated outputs as current.
    has_revision_metadata = isinstance(read_json(project_id, "assets/data/project_meta.json"), dict)
    if source and not has_revision_metadata and (blueprint or lesson_exists or export_exists):
        stages.update(all_downstream)
        legacy_reason = "Legacy project artifact lineage is unknown; rerun required before preview or export."
        if legacy_reason not in reasons:
            reasons.append(legacy_reason)

    return stored.model_copy(update={
        "stale": bool(stored.stale or stages),
        "stale_stages": sorted(stages),
        "reasons": reasons[-20:],
    })


def remove_project(project_id: str) -> None:
    root = project_dir(project_id)
    if root.exists():
        shutil.rmtree(root)


def read_provider_settings() -> ProviderSettings:
    ensure_runtime()
    if not PROVIDER_SETTINGS_PATH.exists():
        settings = ProviderSettings()
        write_provider_settings(settings)
        return settings
    return ProviderSettings.model_validate_json(PROVIDER_SETTINGS_PATH.read_text(encoding="utf-8"))


def write_provider_settings(settings: ProviderSettings) -> None:
    ensure_runtime()
    payload = json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2)
    # Browser startup requests read this file concurrently (settings, catalog,
    # OCR status). Replace it atomically so a reader never observes a partial
    # JSON document while another request is saving settings.
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{PROVIDER_SETTINGS_PATH.name}.",
        dir=str(PROVIDER_SETTINGS_PATH.parent),
    )
    try:
        # Provider settings can contain API credentials. mkstemp already uses
        # owner-only permissions on POSIX, but make that contract explicit so
        # future refactors cannot silently widen access before the atomic move.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, PROVIDER_SETTINGS_PATH)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def get_project_state(project_id: str) -> ProjectState:
    root = project_dir(project_id)
    source = read_model(project_id, "source_material.json", SourceMaterial)
    profile = read_model(project_id, "lesson_profile.json", LessonProfile)
    blueprint = read_model(project_id, "lesson_blueprint.json", LessonBlueprint)
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest)
    report = read_model(project_id, "quality_report.json", QualityReport)
    spec_lock = read_json(project_id, "specs/spec_lock.json") or {}
    lesson_exists = (root / "courseware" / "lesson.html").exists()
    export_exists = latest_export_path(project_id) is not None
    status = "empty"
    if source:
        status = "parsed"
    if blueprint:
        status = "blueprint_ready"
    if manifest:
        status = "media_ready"
    if lesson_exists:
        status = "rendered"

    stale_payload = read_json(project_id, "assets/data/stale_state.json")
    stored_stale_state = StaleState.model_validate(stale_payload) if isinstance(stale_payload, dict) else StaleState()
    stale_state = _effective_stale_state(
        project_id,
        source=source,
        profile=profile,
        blueprint=blueprint,
        lesson_exists=lesson_exists,
        export_exists=export_exists,
        stored=stored_stale_state,
    )
    stale_stages = set(stale_state.stale_stages)
    gate_summary = _gate_summary(
        project_id,
        blueprint=blueprint,
        lesson_exists=lesson_exists,
        stale=stale_state.stale,
        stale_stages=stale_stages,
    )
    profile_state = "stale" if "profile" in stale_stages else read_profile_state(project_id, profile)
    stages = _project_stages(
        project_id,
        source=source,
        profile=profile,
        profile_state=profile_state,
        blueprint=blueprint,
        manifest=manifest,
        lesson_exists=lesson_exists,
        export_exists=export_exists,
        gate_summary=gate_summary,
        stale_stages=stale_stages,
    )
    current_stage = next(
        (stage.stage_id for stage in stages if stage.state not in {"completed", "warning"}),
        "delivery",
    )
    artifacts = {
        "source_material": source is not None,
        "lesson_profile": profile is not None,
        "lesson_blueprint": blueprint is not None,
        "asset_manifest": manifest is not None,
        "render": lesson_exists,
        "quality_report": report is not None,
        "export": export_exists,
    }
    provider_readiness = _provider_readiness()
    file_times = [path.stat().st_mtime for path in root.rglob("*") if path.is_file()]
    last_updated_at = (
        datetime.fromtimestamp(max(file_times), tz=timezone.utc).isoformat()
        if file_times
        else None
    )
    return ProjectState(
        project_id=project_id,
        status=status,
        route=spec_lock.get("route") if isinstance(spec_lock, dict) else None,
        project_revision=project_revision(project_id),
        current_stage=current_stage,
        stages=stages,
        profile_state=profile_state,
        gate_summary=gate_summary,
        artifacts=artifacts,
        stale_state=stale_state,
        provider_readiness=provider_readiness,
        last_updated_at=last_updated_at,
        quality_state=report.state if report else None,
        source_material=source,
        lesson_profile=profile,
        lesson_blueprint=blueprint,
        asset_manifest=manifest,
        quality_report=report,
        preview_url=(
            f"/runtime/projects/{project_id}/courseware/lesson.html"
            if lesson_exists and not gate_summary.stale and not stale_state.stale and "render" not in stale_stages and "quality" not in stale_stages
            else None
        ),
        export_url=(
            f"/api/projects/{project_id}/export"
            if export_exists and gate_summary.export_allowed and not stale_state.stale and "delivery" not in stale_stages
            else None
        ),
    )


def list_project_summaries(limit: int = 20) -> list[ProjectSummary]:
    ensure_runtime()
    summaries: list[ProjectSummary] = []
    for root in PROJECTS_DIR.iterdir():
        if not root.is_dir():
            continue
        try:
            state = get_project_state(root.name)
        except Exception:
            continue
        summaries.append(
            ProjectSummary(
                project_id=state.project_id,
                status=state.status,
                current_stage=state.current_stage,
                profile_state=state.profile_state,
                project_revision=state.project_revision,
                source_filename=state.source_material.original_filename if state.source_material else None,
                last_updated_at=state.last_updated_at,
            )
        )
    summaries.sort(key=lambda item: item.last_updated_at or "", reverse=True)
    return summaries[: max(0, limit)]


def _gate_status(project_id: str, relative_path: str) -> GateStatus:
    payload = read_json(project_id, relative_path)
    if not isinstance(payload, dict) or not payload.get("state"):
        return GateStatus()
    raw_state = str(payload.get("state", "")).lower()
    state_map = {
        "pass": "passed",
        "passed": "passed",
        "warning": "warning",
        "blocked": "blocked",
        "failed": "failed",
        "running": "running",
        "stale": "stale",
        "not_run": "not_run",
    }
    state = state_map.get(raw_state, "failed")
    blocking = payload.get("blocking_reasons", payload.get("blocking", []))
    warnings = payload.get("warnings", [])
    return GateStatus(
        state=state,
        blocking_reasons=[str(item) for item in blocking] if isinstance(blocking, list) else [],
        warnings=[str(item) for item in warnings] if isinstance(warnings, list) else [],
        stale=bool(payload.get("stale", False)) or state == "stale",
    )


def _gate_summary(
    project_id: str,
    *,
    blueprint: LessonBlueprint | None,
    lesson_exists: bool,
    stale: bool,
    stale_stages: set[str] | None = None,
) -> GateSummary:
    stale_stages = stale_stages or set()
    evidence = _gate_status(project_id, "quality/evidence_alignment_report.json")
    readiness = _gate_status(project_id, "quality/presentation_readiness_report.json")
    binding = _gate_status(project_id, "presentation/binding_quality_report.json")
    quality = _gate_status(project_id, "quality/quality_report.json")
    if stale_stages.intersection({"source", "ocr", "profile", "design"}):
        evidence = _mark_gate_stale(evidence)
    if stale_stages.intersection({"presentation", "media"}):
        readiness = _mark_gate_stale(readiness)
        binding = _mark_gate_stale(binding)
    if stale_stages.intersection({"render", "quality"}):
        quality = _mark_gate_stale(quality)
    gates = [evidence, readiness, binding, quality]
    states = [gate.state for gate in gates]
    technical_blockers: list[str] = []
    root = project_dir(project_id)
    lesson_path = root / "courseware" / "lesson.html"
    if blueprint is None:
        technical_blockers.append("Blueprint artifact is missing")
    if (render_reason := _render_artifact_reason(lesson_path)) is not None:
        technical_blockers.append(render_reason)

    if stale or any(gate.stale for gate in gates):
        overall_state = "stale"
    elif any(state == "failed" for state in states):
        overall_state = "failed"
    elif any(state == "blocked" for state in states):
        overall_state = "blocked"
    elif any(state == "running" for state in states):
        overall_state = "running"
    elif any(state == "warning" for state in states):
        overall_state = "warning"
    elif all(state == "not_run" for state in states):
        overall_state = "not_run"
    elif any(state == "not_run" for state in states):
        overall_state = "not_run"
    elif technical_blockers:
        overall_state = "blocked"
    elif all(state in {"passed", "warning"} for state in states):
        overall_state = "passed"
    else:
        overall_state = "warning"
    blocking_reasons = [reason for gate in gates for reason in gate.blocking_reasons]
    blocking_reasons.extend(technical_blockers)
    warnings = [warning for gate in gates for warning in gate.warnings]
    blocked_or_stale = any(gate.state in {"blocked", "failed", "stale", "not_run", "running"} or gate.stale for gate in gates)
    all_gates_run = all(gate.state in {"passed", "warning", "blocked"} for gate in gates)
    gates_passed = all(gate.state in {"passed", "warning"} for gate in gates)
    technical_ready = not technical_blockers
    export_allowed = bool(technical_ready and gates_passed and not stale and not blocked_or_stale)
    force_export_allowed = bool(
        technical_ready
        and all_gates_run
        and not stale
        and not any(gate.state in {"failed", "stale", "running"} or gate.stale for gate in gates)
        and any(gate.state in {"blocked", "warning"} for gate in gates)
    )
    return GateSummary(
        evidence_alignment=evidence,
        presentation_readiness=readiness,
        presentation_binding=binding,
        quality_report=quality,
        overall_state=overall_state,
        export_allowed=export_allowed,
        force_export_allowed=force_export_allowed,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
        stale=stale or any(gate.stale for gate in gates),
    )


def _mark_gate_stale(gate: GateStatus) -> GateStatus:
    return gate.model_copy(update={"state": "stale", "stale": True})


def _project_stages(
    project_id: str,
    *,
    source: SourceMaterial | None,
    profile: LessonProfile | None,
    profile_state: str,
    blueprint: LessonBlueprint | None,
    manifest: AssetManifest | None,
    lesson_exists: bool,
    export_exists: bool,
    gate_summary: GateSummary,
    stale_stages: set[str] | None = None,
) -> list[StageStatus]:
    stale_stages = stale_stages or set()
    learning_artifacts = [
        "learning/learning_state_plan.json",
        "learning/evidence_plan.json",
        "learning/activity_plan.json",
    ]
    has_learning = all((project_dir(project_id) / path).exists() for path in learning_artifacts)
    quality_state = gate_summary.quality_report.state
    quality_stage_state = {
        "not_run": "not_started",
        "running": "running",
        "passed": "completed",
        "warning": "warning",
        "blocked": "blocked",
        "failed": "failed",
        "stale": "stale",
    }[quality_state]
    delivery_state: StageState
    if gate_summary.stale:
        delivery_state = "stale"
    elif gate_summary.overall_state in {"blocked", "failed"}:
        delivery_state = "blocked"
    elif export_exists and gate_summary.export_allowed:
        delivery_state = "completed"
    elif gate_summary.export_allowed:
        delivery_state = "ready"
    elif gate_summary.overall_state in {"blocked", "failed"} or any("artifact is missing" in reason.lower() for reason in gate_summary.blocking_reasons):
        delivery_state = "blocked"
    else:
        delivery_state = "not_started" if not lesson_exists else "ready"
    presentation_gates = (
        gate_summary.evidence_alignment,
        gate_summary.presentation_readiness,
        gate_summary.presentation_binding,
    )
    if not blueprint:
        presentation_state: StageState = "not_started"
    elif any(gate.state == "stale" or gate.stale for gate in presentation_gates):
        presentation_state = "stale"
    elif any(gate.state in {"blocked", "failed"} for gate in presentation_gates):
        presentation_state = "blocked"
    elif any(gate.state == "running" for gate in presentation_gates):
        presentation_state = "running"
    elif any(gate.state == "not_run" for gate in presentation_gates):
        presentation_state = "ready"
    else:
        presentation_state = "completed"
    presentation_blockers = [
        reason
        for gate in presentation_gates
        for reason in gate.blocking_reasons
    ]
    stages = [
        StageStatus(
            stage_id="material",
            state="completed" if source else "ready",
            required_artifacts=["sources/source_material.json"],
            available_actions=["upload", "rerun_ocr"] if source else ["upload"],
        ),
        StageStatus(
            stage_id="profile",
            state="stale" if profile and profile_state == "stale" else ("completed" if profile and profile_state == "confirmed" else ("ready" if profile else "not_started")),
            required_artifacts=["assets/data/lesson_profile.json", "assets/data/profile_state.json"],
            available_actions=["confirm_profile"] if profile else ["infer_profile"],
        ),
        StageStatus(
            stage_id="design",
            state="completed" if has_learning else ("ready" if profile else "not_started"),
            required_artifacts=learning_artifacts,
            available_actions=(
                ["generate_blueprint", "run_pipeline"]
                if profile and profile_state == "confirmed"
                else (["generate_blueprint"] if profile else [])
            ),
        ),
        StageStatus(
            stage_id="presentation",
            state=presentation_state,
            required_artifacts=["blueprints/lesson_blueprint.json", "presentation/activity_bindings.json"],
            blockers=presentation_blockers,
            available_actions=["edit_blueprint", "generate_media"] if blueprint else ["generate_blueprint"],
        ),
        StageStatus(
            stage_id="quality",
            state=quality_stage_state,
            required_artifacts=["quality/quality_report.json"],
            blockers=gate_summary.blocking_reasons,
            warnings=gate_summary.warnings,
            available_actions=(
                (["run_quality", "render"] if lesson_exists else [])
                + (["review_media", "replace_media"] if manifest and not stale_stages.intersection({"profile", "design", "presentation"}) else [])
            ),
        ),
        StageStatus(
            stage_id="delivery",
            state=delivery_state,
            required_artifacts=["courseware/lesson.html", "exports/"],
            blockers=gate_summary.blocking_reasons,
            warnings=gate_summary.warnings,
            available_actions=(
                ["agent_package", "agent_validate"]
                + (["export", "force_export"] if gate_summary.force_export_allowed else [])
            ),
        ),
    ]
    stale_aliases = {
        "profile": {"profile"},
        "design": {"design"},
        "presentation": {"presentation", "media"},
        "quality": {"render", "quality"},
        "delivery": {"delivery"},
    }
    for stage in stages:
        if stale_stages.intersection(stale_aliases.get(stage.stage_id, set())):
            stage.state = "stale"
            stage.stale = True
    return stages


def _provider_readiness() -> list[Any]:
    try:
        from .providers import provider_capability_catalog

        return provider_capability_catalog(read_provider_settings())
    except Exception:
        # Project reads must remain available when an optional runtime probe is
        # unavailable; the provider endpoint still exposes the detailed error.
        return []


def latest_export_path(project_id: str) -> Path | None:
    exports = ensure_project(project_id) / "exports"
    candidates = sorted(exports.glob("HanClassStudio_Output_*.zip"))
    return candidates[-1] if candidates else None


def get_artifact_tree(project_id: str) -> ArtifactTree:
    root = ensure_project(project_id)
    groups: list[ArtifactGroup] = []
    for group_name in PROJECT_GROUPS:
        seen: set[str] = set()
        items = [_artifact_entry(root, Path(group_name))]
        seen.add(group_name)
        for expected in EXPECTED_ARTIFACTS.get(group_name, []):
            relative = Path(expected)
            items.append(_artifact_entry(root, relative))
            seen.add(relative.as_posix())
        group_root = root / group_name
        if group_root.exists():
            for file_path in sorted(path for path in group_root.rglob("*") if path.is_file()):
                relative = file_path.relative_to(root)
                if relative.as_posix() not in seen:
                    items.append(_artifact_entry(root, relative))
        groups.append(ArtifactGroup(name=group_name, items=items))
    spec_lock = read_json(project_id, "specs/spec_lock.json")
    return ArtifactTree(project_id=project_id, groups=groups, spec_lock=spec_lock if isinstance(spec_lock, dict) else None)


def _artifact_entry(root: Path, relative: Path) -> ArtifactEntry:
    path = root / relative
    exists = path.exists()
    stat = path.stat() if exists else None
    return ArtifactEntry(
        path=relative.as_posix(),
        exists=exists,
        size=stat.st_size if stat and path.is_file() else None,
        updated_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else None,
        artifact_type=_artifact_type(relative, path),
    )


def _artifact_type(relative: Path, path: Path) -> str:
    if path.exists() and path.is_dir():
        return "directory"
    parts = relative.parts
    if len(parts) >= 3 and parts[0] == "assets":
        return f"asset:{parts[1]}"
    return parts[0] if parts else "unknown"


def zip_output(project_id: str, force: bool = False, classroom: bool = False) -> Path:
    root = ensure_project(project_id)
    if force:
        _assert_export_technical_artifacts(project_id, root)
        _assert_export_gate_inputs(project_id, force=True)
    alignment_report = read_json(project_id, "quality/evidence_alignment_report.json") or {}
    if isinstance(alignment_report, dict) and alignment_report.get("state") == "blocked" and not force:
        raise PermissionError("Evidence alignment gate is blocked; pass force=true to export anyway")
    readiness_report = read_json(project_id, "quality/presentation_readiness_report.json") or {}
    if isinstance(readiness_report, dict) and readiness_report.get("state") == "blocked" and not force:
        raise PermissionError("Presentation readiness gate is blocked; pass force=true to export anyway")
    if not force:
        _assert_export_gate_inputs(project_id, force=False)
        _assert_export_technical_artifacts(project_id, root)
    blueprint = read_model(project_id, "lesson_blueprint.json", LessonBlueprint)
    lesson_path = root / "courseware" / "lesson.html"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    prefix = "HanClassStudio_Classroom" if classroom else "HanClassStudio_Output"
    export_path = root / "exports" / f"{prefix}_{timestamp}.zip"
    gate_blockers: list[str] = []
    for relative_path in (
        "quality/evidence_alignment_report.json",
        "quality/presentation_readiness_report.json",
        "presentation/binding_quality_report.json",
        "quality/quality_report.json",
    ):
        payload = read_json(project_id, relative_path)
        if not isinstance(payload, dict):
            continue
        values = payload.get("blocking_reasons", payload.get("blocking", []))
        if isinstance(values, list):
            gate_blockers.extend(str(item) for item in values)
        if force and not values and str(payload.get("state", "")).lower() in {"blocked", "warning"}:
            gate_blockers.append(f"{relative_path} state: {payload.get('state')}")
    manifest = {
        "schema": "hanclassstudio.export_manifest.v1",
        "project_id": project_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "forced": force,
        "classroom": classroom,
        "evidence_alignment_state": alignment_report.get("state") if isinstance(alignment_report, dict) else None,
        "presentation_readiness_state": readiness_report.get("state") if isinstance(readiness_report, dict) else None,
        "forced_blockers": gate_blockers if force else [],
        "force_confirmation": "explicit force=true request" if force else None,
    }
    write_json(project_id, "exports/export_manifest.json", manifest)

    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        html = lesson_path.read_text(encoding="utf-8").replace("../assets/", "assets/")
        zf.writestr("lesson.html", html)

        # Add classroom HTML if available
        classroom_path = root / "courseware" / "lesson_classroom.html"
        if classroom_path.exists():
            html = classroom_path.read_text(encoding="utf-8").replace("../assets/", "assets/")
            zf.writestr("lesson_classroom.html", html)

        assets_root = root / "assets"
        for file_path in assets_root.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(root).as_posix())

        extra_data = {
            "sources/source_material.json": "assets/data/source_material.json",
            "blueprints/lesson_blueprint.json": "assets/data/lesson_blueprint.json",
            "blueprints/interaction_plan.json": "assets/data/interaction_plan.json",
            "blueprints/media_plan.json": "assets/data/media_plan.json",
            "presentation/activity_bindings.json": "assets/data/activity_bindings.json",
            "presentation/binding_quality_report.json": "assets/data/binding_quality_report.json",
            "quality/presentation_readiness_report.json": "assets/data/presentation_readiness_report.json",
            "quality/quality_report.json": "assets/data/quality_report.json",
            "quality/quality_summary.md": "quality_summary.md",
            "exports/export_manifest.json": "export_manifest.json",
        }
        for source_name, archive_name in extra_data.items():
            file_path = root / source_name
            if file_path.exists():
                zf.write(file_path, archive_name)
    return export_path


def _assert_export_technical_artifacts(project_id: str, root: Path) -> None:
    if read_model(project_id, "lesson_blueprint.json", LessonBlueprint) is None:
        raise PermissionError("Blueprint artifact is missing; export cannot proceed")
    lesson_path = root / "courseware" / "lesson.html"
    if (reason := _render_artifact_reason(lesson_path)) is not None:
        raise PermissionError(f"{reason}; export cannot proceed")


def _render_artifact_reason(path: Path) -> str | None:
    """Validate the current HTML entry point before exposing/exporting it."""
    if not path.is_file():
        return "Render artifact is missing"
    try:
        html = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "Render artifact is unreadable or corrupt"
    if not html.strip():
        return "Render artifact is empty"
    normalized = html.lstrip().lower()
    if "<html" not in normalized and not normalized.startswith("<!doctype html"):
        return "Render artifact is malformed"
    return None


def _assert_export_gate_inputs(project_id: str, *, force: bool) -> None:
    gates = (
        ("Evidence alignment", "quality/evidence_alignment_report.json"),
        ("Presentation readiness", "quality/presentation_readiness_report.json"),
        ("Presentation binding", "presentation/binding_quality_report.json"),
        ("Quality", "quality/quality_report.json"),
    )
    allowed = {"pass", "passed", "warning", "blocked"}
    for label, relative_path in gates:
        payload = read_json(project_id, relative_path)
        state = str(payload.get("state", "not_run")).lower() if isinstance(payload, dict) else "not_run"
        if state not in allowed or (state == "blocked" and not force):
            if state == "blocked" and not force:
                raise PermissionError(f"{label} gate is blocked; pass force=true to export anyway")
            if force:
                raise PermissionError(f"{label} gate is {state}; force export is unavailable")
            raise PermissionError(f"{label} gate is {state}; run the gate before export")
