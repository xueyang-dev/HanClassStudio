from __future__ import annotations

from pathlib import Path

from .agents import build_blueprint
from .media import generate_configured_media
from .models import AssetManifest, LessonBlueprint, LessonProfile, ProjectState, ProviderSettings, QualityReport, SourceMaterial
from .providers import ProviderError, generate_blueprint_with_llm
from .quality import check_quality
from .renderer import render_lesson
from .storage import get_project_state, read_model, write_json, write_model, write_text, zip_output
from .strategist import build_interaction_plan, build_lesson_spec, build_media_plan, build_spec_lock


def generate_lesson_blueprint(
    source: SourceMaterial,
    profile: LessonProfile,
    settings: ProviderSettings,
) -> LessonBlueprint:
    try:
        blueprint = generate_blueprint_with_llm(source, profile, settings.llm)
    except ProviderError:
        blueprint = None
    return blueprint or build_blueprint(source, profile)


def generate_project_media(
    project_root: Path,
    blueprint: LessonBlueprint,
    settings: ProviderSettings,
) -> AssetManifest:
    return generate_configured_media(project_root, blueprint, settings)


def write_spec_artifacts(
    project_id: str,
    source: SourceMaterial,
    profile: LessonProfile,
) -> dict:
    spec_lock = build_spec_lock(project_id, source, profile)
    lesson_spec = build_lesson_spec(source, profile, spec_lock)
    write_text(project_id, "specs/lesson_spec.md", lesson_spec)
    write_json(project_id, "specs/spec_lock.json", spec_lock)
    return spec_lock


def write_blueprint_artifacts(project_id: str, blueprint: LessonBlueprint) -> None:
    write_model(project_id, "lesson_blueprint.json", blueprint)
    write_json(project_id, "blueprints/interaction_plan.json", build_interaction_plan(blueprint))
    write_json(project_id, "blueprints/media_plan.json", build_media_plan(blueprint))


def render_and_check(
    project_id: str,
    project_root: Path,
    profile: LessonProfile,
    blueprint: LessonBlueprint,
    manifest: AssetManifest,
) -> QualityReport:
    preliminary = QualityReport(suggestions=["Rendering in progress; final quality gate runs after HTML output."])
    render_lesson(project_root, profile, blueprint, manifest, preliminary)
    report = check_quality(project_root, blueprint, manifest)
    render_lesson(project_root, profile, blueprint, manifest, report)
    write_model(project_id, "quality_report.json", report)
    write_text(project_id, "quality/quality_summary.md", "\n".join(["# Quality Summary", "", f"State: {report.state}", *report.blocking, *report.warnings, *report.passed]))
    return report


def run_full_pipeline(
    project_id: str,
    project_root: Path,
    settings: ProviderSettings,
    force_export: bool = False,
) -> ProjectState:
    source = read_model(project_id, "source_material.json", SourceMaterial)
    profile = read_model(project_id, "lesson_profile.json", LessonProfile)
    if not source or not profile:
        raise ValueError("Project needs source material and lesson profile")

    write_spec_artifacts(project_id, source, profile)
    blueprint = generate_lesson_blueprint(source, profile, settings)
    write_blueprint_artifacts(project_id, blueprint)
    manifest = generate_project_media(project_root, blueprint, settings)
    write_model(project_id, "asset_manifest.json", manifest)
    write_json(project_id, "assets/data/attribution.json", {"schema": "hanclassstudio.attribution.v1", "items": []})
    report = render_and_check(project_id, project_root, profile, blueprint, manifest)
    if report.state != "blocked" or force_export:
        zip_output(project_id, force=force_export)
    return get_project_state(project_id)
