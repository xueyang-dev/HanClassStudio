from __future__ import annotations

from pathlib import Path

from .agents import build_blueprint
from .analysis import extract_candidates
from .learner_comprehension import (
    build_language_items,
    build_learner_model,
    check_comprehensibility,
    plan_comprehensible_input,
)
from .media import generate_configured_media
from .models import (
    AssetManifest, ClassroomQualityReport, LessonBlueprint, LessonProfile,
    ProjectState, ProviderSettings, QualityReport, SourceMaterial, TeachingCandidates,
)
from .providers import ProviderError, generate_blueprint_with_llm
from .quality import check_classroom_quality, check_quality
from .renderer import render_lesson
from .storage import get_project_state, read_model, read_provider_settings, write_json, write_model, write_text, zip_output
from .strategist import build_interaction_plan, build_lesson_spec, build_media_plan, build_spec_lock
from .syllabus_engine import (
    build_allowed_text_plan,
    build_difficulty_profile,
    build_language_inventory,
    build_source_lesson_profile,
    check_off_level,
)


def generate_lesson_blueprint(
    source: SourceMaterial,
    profile: LessonProfile,
    settings: ProviderSettings,
) -> tuple[LessonBlueprint, TeachingCandidates]:
    # Always extract teaching candidates from source
    candidates = extract_candidates(source)
    from .learner_comprehension import build_language_items, build_learner_model
    learner_model = build_learner_model(profile)
    language_items = build_language_items(candidates, learner_model)
    try:
        blueprint = generate_blueprint_with_llm(source, profile, settings.llm)
    except ProviderError:
        blueprint = None
    if blueprint is None:
        blueprint = build_blueprint(source, profile, candidates, language_items)
    return blueprint, candidates


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
    candidates: TeachingCandidates | None = None,
    language_items: list | None = None,
    learner_model=None,
    render_mode: str = "debug",
) -> QualityReport:
    preliminary = QualityReport(suggestions=["Rendering in progress; final quality gate runs after HTML output."])
    render_lesson(project_root, profile, blueprint, manifest, preliminary, render_mode=render_mode)
    report = check_quality(project_root, blueprint, manifest)
    render_lesson(project_root, profile, blueprint, manifest, report, render_mode=render_mode)
    write_model(project_id, "quality_report.json", report)
    write_text(project_id, "quality/quality_summary.md", "\n".join(["# Quality Summary", "", f"State: {report.state}", *report.blocking, *report.warnings, *report.passed]))

    # Generate classroom HTML separately
    render_lesson(project_root, profile, blueprint, manifest, report, render_mode="classroom")

    # Learner comprehension artifacts
    if learner_model is not None and language_items is not None:
        seq_plan = plan_comprehensible_input(language_items, learner_model)
        write_json(project_id, "analysis/input_sequence_plan.json", seq_plan.model_dump(mode="json"))
        comp_report = check_comprehensibility(blueprint, language_items, learner_model)
        write_json(project_id, "quality/comprehensibility_report.json", comp_report.model_dump(mode="json"))

    # Classroom quality gate
    classroom_report = check_classroom_quality(blueprint, candidates)
    write_json(project_id, "quality/classroom_quality_report.json", classroom_report.model_dump(mode="json"))

    # Syllabus-aware allowed text plan and off-level check
    if blueprint and profile:
        from .models import DifficultyProfile as _DP, LanguageInventory as _LI, LearnerModel as _LM
        from .realization_engine import build_presentation_plan, check_realization as _check_real
        diff = read_model(project_id, "analysis/difficulty_profile.json", _DP) or _DP()
        inv = read_model(project_id, "analysis/language_inventory.json", _LI) or _LI()
        atp = build_allowed_text_plan(blueprint, inv, diff)
        write_json(project_id, "analysis/allowed_text_plan.json", atp.model_dump(mode="json"))
        off_report = check_off_level(blueprint, atp, inv, diff)
        write_json(project_id, "quality/off_level_report.json", off_report.model_dump(mode="json"))
        # Pedagogical realization check
        zblevel = "zero_beginner" if getattr(diff, "estimated_level", "zero_beginner") in ("zero_beginner", "beginner") else "beginner"
        pp = build_presentation_plan(blueprint, zblevel)
        write_json(project_id, "analysis/presentation_plan.json", pp.model_dump(mode="json"))
        real_report = _check_real(blueprint, zblevel)
        write_json(project_id, "quality/realization_report.json", real_report.model_dump(mode="json"))

        # Courseware Review Agent
        from .review_agent import review_blueprint, build_revision_plan
        from .storage import read_json as _rj
        language_items = _rj(project_id, "analysis/language_items.json") or []
        alignment_data = _rj(project_id, "quality/evidence_alignment_report.json") if _rj(project_id, "quality/evidence_alignment_report.json") else None
        review_report = review_blueprint(blueprint, zblevel, profile.scaffolding_language if profile else "English", language_items, alignment_data)
        write_json(project_id, "quality/courseware_review_report.json", review_report.model_dump(mode="json"))
        if review_report.state == "blocked":
            rev_plan = build_revision_plan(review_report, blueprint)
            write_json(project_id, "blueprints/revision_plan.json", rev_plan.model_dump(mode="json"))

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
    blueprint, candidates = generate_lesson_blueprint(source, profile, settings)
    write_blueprint_artifacts(project_id, blueprint)
    write_json(project_id, "analysis/teaching_candidates.json", candidates.model_dump(mode="json"))

    # Learner model
    learner_model = build_learner_model(profile)
    write_json(project_id, "analysis/learner_model.json", learner_model.model_dump(mode="json"))

    # Language items
    language_items = build_language_items(candidates, learner_model)
    write_json(project_id, "analysis/language_items.json", [li.model_dump(mode="json") for li in language_items])

    # Syllabus-aware artifacts
    source_lesson = build_source_lesson_profile(source)
    write_json(project_id, "analysis/source_lesson_profile.json", source_lesson.model_dump(mode="json"))
    difficulty = build_difficulty_profile(source, profile, source_lesson)
    write_json(project_id, "analysis/difficulty_profile.json", difficulty.model_dump(mode="json"))
    inventory = build_language_inventory(source_lesson, difficulty, learner_model)
    write_json(project_id, "analysis/language_inventory.json", inventory.model_dump(mode="json"))

    # State-Evidence Kernel
    from .state_evidence_kernel import build_full_kernel as _build_kernel
    state_plan, evidence_plan, activity_plan, alignment = _build_kernel(
        profile, candidates, language_items,
        str(difficulty.estimated_level) if hasattr(difficulty, "estimated_level") else "zero_beginner",
        profile.scaffolding_language or "English",
    )
    write_json(project_id, "learning/learning_state_plan.json", state_plan.model_dump(mode="json"))
    write_json(project_id, "learning/evidence_plan.json", evidence_plan.model_dump(mode="json"))
    write_json(project_id, "learning/activity_plan.json", activity_plan.model_dump(mode="json"))
    write_json(project_id, "quality/evidence_alignment_report.json", alignment.model_dump(mode="json"))

    # Pipeline gate: blocked alignment stops classroom render/export, writes diagnostic artifact
    if alignment.state == "blocked":
        from .storage import write_json as _wj, ensure_project as _ep
        _wj(project_id, "quality/kernel_revision_plan.json", {
            "schema": "hanclassstudio.kernel_revision_plan.v1",
            "state": "blocked",
            "blocking_issues": alignment.blocking[:10],
            "message": "Evidence alignment blocked. Classroom render/export stopped. Diagnostic artifact generated.",
        })
        # Generate diagnostic ZIP with kernel artifacts only
        import zipfile, datetime
        diag_root = _ep(project_id)
        diag_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        diag_path = diag_root / "exports" / f"HanClassStudio_Kernel_Diagnostic_{diag_ts}.zip"
        diag_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(diag_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for src_name, arc_name in [
                ("learning/learning_state_plan.json", "learning/learning_state_plan.json"),
                ("learning/evidence_plan.json", "learning/evidence_plan.json"),
                ("learning/activity_plan.json", "learning/activity_plan.json"),
                ("quality/evidence_alignment_report.json", "quality/evidence_alignment_report.json"),
                ("quality/kernel_revision_plan.json", "kernel_revision_plan.json"),
                ("sources/source_material.json", "source_material.json"),
            ]:
                fp = diag_root / src_name
                if fp.exists():
                    zf.write(fp, arc_name)
        _wj(project_id, "exports/export_manifest.json", {
            "project_id": project_id,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "export_type": "kernel_diagnostic",
            "diagnostic": True,
            "kernel_alignment_state": "blocked",
        })
        # Return project state without classroom render
        manifest = generate_project_media(project_root, blueprint, settings)
        write_model(project_id, "asset_manifest.json", manifest)
        return get_project_state(project_id)

    manifest = generate_project_media(project_root, blueprint, settings)
    write_model(project_id, "asset_manifest.json", manifest)
    write_json(project_id, "assets/data/attribution.json", {"schema": "hanclassstudio.attribution.v1", "items": []})
    report = render_and_check(project_id, project_root, profile, blueprint, manifest, candidates, language_items, learner_model)
    # Revision application: if review was blocked, try auto-fix
    rev_path = project_root / "blueprints" / "revision_plan.json"
    if rev_path.exists() and report.state == "blocked":
        from .review_agent import apply_revision_plan, review_blueprint as _review_again
        from .models import RevisionPlan as _RP
        from .storage import read_json as _rj
        rev_data = _rj(project_id, "blueprints/revision_plan.json")
        rev_plan = _RP(**rev_data) if rev_data else None
        zb = "zero_beginner" if profile.learner_level and "zero" in profile.learner_level.lower() else "beginner"
        revised_bp, rev_apply_report = apply_revision_plan(blueprint, rev_plan, learner_model, None, language_items)
        write_json(project_id, "blueprints/revised_blueprint.json", revised_bp.model_dump(mode="json"))
        write_json(project_id, "quality/revision_application_report.json", rev_apply_report)
        revised_review = _review_again(revised_bp, zb, profile.scaffolding_language or "English", language_items)
        write_json(project_id, "quality/revised_review_report.json", revised_review.model_dump(mode="json"))
        if revised_review.state != "blocked":
            blueprint = revised_bp
            write_model(project_id, "lesson_blueprint.json", revised_bp)
            manifest = generate_project_media(project_root, blueprint, settings)
            write_model(project_id, "asset_manifest.json", manifest)
            report = render_and_check(project_id, project_root, profile, blueprint, manifest, candidates, language_items, learner_model)
    # End revision application

    if report.state != "blocked" or force_export:
        zip_output(project_id, force=force_export)
    return get_project_state(project_id)
