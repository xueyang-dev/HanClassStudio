from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .models import (
    AssetManifest,
    ArtifactEntry,
    ArtifactGroup,
    ArtifactTree,
    LessonBlueprint,
    LessonProfile,
    ProjectState,
    ProviderSettings,
    QualityReport,
    SourceMaterial,
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
    "quality": ["quality/quality_report.json", "quality/quality_summary.md", "quality/pptx_quality_report.json"],
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
    return json.loads(path.read_text(encoding="utf-8"))


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
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


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
    PROVIDER_SETTINGS_PATH.write_text(
        json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
    return ProjectState(
        project_id=project_id,
        status=status,
        route=spec_lock.get("route") if isinstance(spec_lock, dict) else None,
        quality_state=report.state if report else None,
        source_material=source,
        lesson_profile=profile,
        lesson_blueprint=blueprint,
        asset_manifest=manifest,
        quality_report=report,
        preview_url=f"/runtime/projects/{project_id}/courseware/lesson.html" if lesson_exists else None,
        export_url=f"/api/projects/{project_id}/export" if export_exists else None,
    )


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    prefix = "HanClassStudio_Classroom" if classroom else "HanClassStudio_Output"
    export_path = root / "exports" / f"{prefix}_{timestamp}.zip"
    manifest = {
        "schema": "hanclassstudio.export_manifest.v1",
        "project_id": project_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "forced": force,
        "classroom": classroom,
    }
    write_json(project_id, "exports/export_manifest.json", manifest)

    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        lesson_path = root / "courseware" / "lesson.html"
        if lesson_path.exists():
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
            "quality/quality_report.json": "assets/data/quality_report.json",
            "quality/quality_summary.md": "quality_summary.md",
            "exports/export_manifest.json": "export_manifest.json",
        }
        for source_name, archive_name in extra_data.items():
            file_path = root / source_name
            if file_path.exists():
                zf.write(file_path, archive_name)
    return export_path
