from __future__ import annotations

from pathlib import Path

from .agents import build_blueprint
from .analysis import extract_candidates
from .blueprint_utils import normalize_component_ids
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
from .storage import get_project_state, read_json, read_model, read_provider_settings, write_json, write_model, write_text, zip_output
from .strategist import build_interaction_plan, build_lesson_spec, build_media_plan, build_spec_lock
from .syllabus_engine import (
    build_allowed_text_plan,
    build_difficulty_profile,
    build_language_inventory,
    build_source_lesson_profile,
    check_off_level,
)


SHADOW_PRESENTATION_ARTIFACTS = (
    "presentation/presentation_blueprint.json",
    "presentation/presentation_content_plan.json",
    "presentation/presentation_content_plan.reconciled.json",
    "presentation/presentation_media_request_plan.json",
    "presentation/presentation_media_asset_links.shadow.json",
    "presentation/presentation_media_projection_links.shadow.json",
    "presentation/legacy_blueprint_from_v2.shadow.json",
    "presentation/legacy_component_mapping.shadow.json",
    "quality/presentation_content_report.json",
    "quality/presentation_media_request_report.json",
    "quality/presentation_media_projection_report.json",
    "quality/presentation_asset_reconciliation_report.json",
    "quality/presentation_parity_report.json",
    "quality/presentation_adapter_assessment_report.json",
)

CONTENT_DOWNSTREAM_ARTIFACTS = SHADOW_PRESENTATION_ARTIFACTS[2:]
V2_INTERNAL_CUTOVER_ARTIFACTS = (
    "quality/v2_cutover_readiness_report.json",
    "quality/v2_rendered_output_review.json",
    "courseware/lesson_v2_internal.html",
    "courseware/render_manifest_v2_internal.json",
    "diagnostics/v2_rendered_output",
)


def _remove_project_artifacts(project_id: str, relative_paths: tuple[str, ...]) -> None:
    import shutil

    from .storage import project_dir

    root = project_dir(project_id)
    for relative_path in relative_paths:
        path = root / relative_path
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def generate_lesson_blueprint(
    source: SourceMaterial,
    profile: LessonProfile,
    settings: ProviderSettings,
    candidates: TeachingCandidates | None = None,
    language_items: list | None = None,
) -> tuple[LessonBlueprint, TeachingCandidates]:
    # Always extract teaching candidates from source
    candidates = candidates or extract_candidates(source)
    from .learner_comprehension import build_language_items, build_learner_model
    if language_items is None:
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
    preserve_media_origin_trace: bool = False,
    force_regenerate: bool = False,
) -> AssetManifest:
    return generate_configured_media(
        project_root, blueprint, settings, preserve_media_origin_trace, force_regenerate,
    )


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
    # Manual legacy edits must never retain a prior v2 route decision or output.
    _remove_project_artifacts(project_id, V2_INTERNAL_CUTOVER_ARTIFACTS)
    normalize_component_ids(blueprint)
    write_model(project_id, "lesson_blueprint.json", blueprint)
    write_json(project_id, "blueprints/interaction_plan.json", build_interaction_plan(blueprint))
    write_json(project_id, "blueprints/media_plan.json", build_media_plan(blueprint))


def write_presentation_bindings(
    project_id: str,
    blueprint: LessonBlueprint,
    evidence_plan,
    activity_plan,
    state_plan,
    learner_level: str,
):
    from .presentation_bindings import build_activity_bindings
    binding_plan = build_activity_bindings(blueprint, evidence_plan, activity_plan, state_plan, learner_level)
    payload = binding_plan.model_dump(mode="json", by_alias=True)
    write_json(project_id, "presentation/activity_bindings.json", payload)
    write_json(project_id, "presentation/binding_quality_report.json", payload)
    if binding_plan.state == "blocked":
        write_json(project_id, "presentation/binding_revision_recommendation.json", {
            "schema": "hanclassstudio.binding_revision_recommendation.v1",
            "state": "blocked",
            "blocking_issues": binding_plan.blocking[:10],
            "message": "Presentation binding blocked. Classroom-ready render/export stopped.",
        })
    return binding_plan


def write_presentation_readiness(
    project_id: str,
    blueprint: LessonBlueprint,
    evidence_plan,
    activity_plan,
    binding_plan,
    alignment_report,
):
    from .presentation_readiness import check_presentation_readiness

    report = check_presentation_readiness(
        blueprint,
        evidence_plan,
        activity_plan,
        binding_plan,
        alignment_report,
    )
    write_json(project_id, "quality/presentation_readiness_report.json", report.model_dump(mode="json", by_alias=True))
    return report


def write_presentation_shadow_artifacts(
    project_id: str,
    state_plan,
    evidence_plan,
    activity_plan,
    alignment_report,
):
    """Dual-write v2 presentation artifacts without touching the production blueprint."""
    _remove_project_artifacts(project_id, SHADOW_PRESENTATION_ARTIFACTS)
    from .blueprint_compatibility import adapt_canonical_presentation_blueprint
    from .presentation_blueprint import (
        ABSTRACT_BINDING_PATH,
        CANONICAL_BLUEPRINT_PATH,
        SHADOW_REPORT_PATH,
        compile_shadow_presentation,
    )

    bindings, canonical, report = compile_shadow_presentation(
        state_plan, evidence_plan, activity_plan, alignment_report,
    )
    write_json(project_id, ABSTRACT_BINDING_PATH, bindings.model_dump(mode="json", by_alias=True))
    if canonical is not None:
        try:
            # Validate the adapter seam in memory only.  The production legacy
            # blueprint is neither read nor written by this shadow path.
            adapt_canonical_presentation_blueprint(canonical)
            report.compatibility_contract_valid = True
            write_json(project_id, CANONICAL_BLUEPRINT_PATH, canonical.model_dump(mode="json", by_alias=True))
        except Exception as exc:  # pragma: no cover - defensive shadow isolation
            report.state = "blocked"
            report.blocking.append(f"Legacy compatibility adapter rejected canonical shadow blueprint: {exc}")
            report.compatibility_contract_valid = False
    write_json(project_id, SHADOW_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    return bindings, canonical, report


def write_presentation_content_shadow_artifacts(
    project_id: str,
    state_plan,
    evidence_plan,
    activity_plan,
    binding_plan,
    canonical_blueprint,
    language_items,
    asset_manifest=None,
):
    """Write v2 content artifacts and update only the shadow canonical reference graph."""
    _remove_project_artifacts(project_id, CONTENT_DOWNSTREAM_ARTIFACTS)
    from .presentation_content import (
        CONTENT_PLAN_PATH,
        CONTENT_REPORT_PATH,
        attach_content_references,
        build_presentation_content_plan,
    )

    plan, report = build_presentation_content_plan(
        state_plan, evidence_plan, activity_plan, binding_plan, None, language_items, asset_manifest,
    )
    enriched = attach_content_references(canonical_blueprint, plan)
    write_json(project_id, CONTENT_PLAN_PATH, plan.model_dump(mode="json", by_alias=True))
    write_json(project_id, CONTENT_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    write_json(project_id, "presentation/presentation_blueprint.json", enriched.model_dump(mode="json", by_alias=True))
    return plan, report, enriched


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
    from .models import PresentationBindingPlan as _PBP
    binding_data = read_json(project_id, "presentation/activity_bindings.json")
    activity_bindings = _PBP(**binding_data) if binding_data else None
    render_lesson(project_root, profile, blueprint, manifest, preliminary, render_mode=render_mode, activity_bindings=activity_bindings)
    report = check_quality(project_root, blueprint, manifest)
    render_lesson(project_root, profile, blueprint, manifest, report, render_mode=render_mode, activity_bindings=activity_bindings)
    write_model(project_id, "quality_report.json", report)
    write_text(project_id, "quality/quality_summary.md", "\n".join(["# Quality Summary", "", f"State: {report.state}", *report.blocking, *report.warnings, *report.passed]))

    # Generate classroom HTML separately
    render_lesson(project_root, profile, blueprint, manifest, report, render_mode="classroom", activity_bindings=activity_bindings)

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
    enable_presentation_parity_shadow: bool = False,
    enable_presentation_adapter_assessment: bool = False,
    enable_presentation_content_shadow: bool = False,
    enable_presentation_asset_reconciliation_shadow: bool = False,
    enable_presentation_media_request_shadow: bool = False,
    enable_presentation_media_projection_shadow: bool = False,
    enable_v2_internal_html_cutover: bool = False,
) -> ProjectState:
    source = read_model(project_id, "source_material.json", SourceMaterial)
    profile = read_model(project_id, "lesson_profile.json", LessonProfile)
    if not source or not profile:
        raise ValueError("Project needs source material and lesson profile")

    shadow_content_enabled = enable_presentation_content_shadow or enable_v2_internal_html_cutover
    media_request_enabled = enable_presentation_media_request_shadow or enable_v2_internal_html_cutover
    media_projection_enabled = enable_presentation_media_projection_shadow or enable_v2_internal_html_cutover
    reconciliation_enabled = (
        enable_presentation_asset_reconciliation_shadow
        or media_request_enabled
        or media_projection_enabled
    )

    write_spec_artifacts(project_id, source, profile)
    candidates = extract_candidates(source)
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
    write_json(project_id, "learning/learning_state_plan.json", state_plan.model_dump(mode="json", by_alias=True))
    write_json(project_id, "learning/evidence_plan.json", evidence_plan.model_dump(mode="json", by_alias=True))
    write_json(project_id, "learning/activity_plan.json", activity_plan.model_dump(mode="json", by_alias=True))
    write_json(project_id, "quality/evidence_alignment_report.json", alignment.model_dump(mode="json", by_alias=True))
    shadow_bindings, canonical_shadow, _ = write_presentation_shadow_artifacts(
        project_id, state_plan, evidence_plan, activity_plan, alignment,
    )
    if shadow_content_enabled and canonical_shadow is not None:
        _, _, canonical_shadow = write_presentation_content_shadow_artifacts(
            project_id, state_plan, evidence_plan, activity_plan, shadow_bindings, canonical_shadow, language_items,
        )
    if media_request_enabled:
        from .presentation_media_requests import run_presentation_media_request_shadow

        run_presentation_media_request_shadow(project_id)

    # Pipeline gate: blocked alignment stops classroom render/export, writes diagnostic artifact
    if alignment.state == "blocked":
        if enable_presentation_parity_shadow:
            from .presentation_parity import run_presentation_parity_harness

            run_presentation_parity_harness(project_id)
        if enable_presentation_adapter_assessment:
            from .presentation_adapter_assessment import run_presentation_adapter_assessment

            run_presentation_adapter_assessment(project_id)
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
                ("presentation/abstract_activity_bindings.json", "presentation/abstract_activity_bindings.json"),
                ("quality/presentation_shadow_report.json", "quality/presentation_shadow_report.json"),
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
        if enable_v2_internal_html_cutover:
            from .v2_cutover_readiness import run_v2_internal_html_cutover

            run_v2_internal_html_cutover(
                project_id, project_root, profile, AssetManifest(), QualityReport(),
                enabled=True, require_courseware_review=False,
            )
        # Return project state without generating presentation or rendered artifacts.
        return get_project_state(project_id)

    # Presentation remains downstream from the State-Evidence alignment gate.
    blueprint, _ = generate_lesson_blueprint(source, profile, settings, candidates, language_items)
    write_blueprint_artifacts(project_id, blueprint)
    if enable_presentation_parity_shadow:
        from .presentation_parity import run_presentation_parity_harness

        run_presentation_parity_harness(project_id)
    if enable_presentation_adapter_assessment:
        from .presentation_adapter_assessment import run_presentation_adapter_assessment

        run_presentation_adapter_assessment(project_id)
    learner_level = str(difficulty.estimated_level) if hasattr(difficulty, "estimated_level") else "zero_beginner"
    binding_plan = write_presentation_bindings(project_id, blueprint, evidence_plan, activity_plan, state_plan, learner_level)
    readiness = write_presentation_readiness(
        project_id, blueprint, evidence_plan, activity_plan, binding_plan, alignment,
    )
    if binding_plan.state == "blocked" or readiness.state == "blocked":
        manifest = generate_project_media(project_root, blueprint, settings, media_projection_enabled)
        write_model(project_id, "asset_manifest.json", manifest)
        if media_projection_enabled:
            from .presentation_media_projection import run_presentation_media_projection_audit

            run_presentation_media_projection_audit(project_id, manifest)
        if media_request_enabled:
            from .presentation_media_requests import run_presentation_media_asset_linkage

            run_presentation_media_asset_linkage(project_id, manifest)
        if reconciliation_enabled:
            from .presentation_asset_reconciliation import run_post_media_presentation_reconciliation

            run_post_media_presentation_reconciliation(project_id, manifest)
        if enable_v2_internal_html_cutover:
            from .v2_cutover_readiness import run_v2_internal_html_cutover

            run_v2_internal_html_cutover(
                project_id, project_root, profile, manifest, QualityReport(),
                enabled=True, require_courseware_review=False,
            )
        return get_project_state(project_id)

    manifest = generate_project_media(project_root, blueprint, settings, media_projection_enabled)
    write_model(project_id, "asset_manifest.json", manifest)
    if media_projection_enabled:
        from .presentation_media_projection import run_presentation_media_projection_audit

        run_presentation_media_projection_audit(project_id, manifest)
    if media_request_enabled:
        from .presentation_media_requests import run_presentation_media_asset_linkage

        run_presentation_media_asset_linkage(project_id, manifest)
    if reconciliation_enabled:
        from .presentation_asset_reconciliation import run_post_media_presentation_reconciliation

        run_post_media_presentation_reconciliation(project_id, manifest)
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
        normalize_component_ids(revised_bp)
        write_json(project_id, "blueprints/revised_blueprint.json", revised_bp.model_dump(mode="json"))
        write_json(project_id, "quality/revision_application_report.json", rev_apply_report)
        revised_review = _review_again(revised_bp, zb, profile.scaffolding_language or "English", language_items)
        write_json(project_id, "quality/revised_review_report.json", revised_review.model_dump(mode="json"))
        if revised_review.state != "blocked":
            blueprint = revised_bp
            write_blueprint_artifacts(project_id, revised_bp)
            binding_plan = write_presentation_bindings(project_id, blueprint, evidence_plan, activity_plan, state_plan, learner_level)
            readiness = write_presentation_readiness(
                project_id, blueprint, evidence_plan, activity_plan, binding_plan, alignment,
            )
            if binding_plan.state == "blocked" or readiness.state == "blocked":
                return get_project_state(project_id)
            manifest = generate_project_media(project_root, blueprint, settings, media_projection_enabled)
            write_model(project_id, "asset_manifest.json", manifest)
            if media_projection_enabled:
                from .presentation_media_projection import run_presentation_media_projection_audit

                run_presentation_media_projection_audit(project_id, manifest)
            if media_request_enabled:
                from .presentation_media_requests import run_presentation_media_asset_linkage

                run_presentation_media_asset_linkage(project_id, manifest)
            if reconciliation_enabled:
                from .presentation_asset_reconciliation import run_post_media_presentation_reconciliation

                run_post_media_presentation_reconciliation(project_id, manifest)
            report = render_and_check(project_id, project_root, profile, blueprint, manifest, candidates, language_items, learner_model)
    # End revision application

    if enable_v2_internal_html_cutover:
        from .v2_cutover_readiness import run_v2_internal_html_cutover

        run_v2_internal_html_cutover(
            project_id, project_root, profile, manifest, report,
            enabled=True, require_courseware_review=True,
        )

    if report.state != "blocked" or force_export:
        zip_output(project_id, force=force_export)
    return get_project_state(project_id)
