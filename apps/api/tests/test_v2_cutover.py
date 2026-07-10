"""Whole-lesson aggregate gate tests for the internal-only v2 HTML experiment."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

import hcs_api.storage as storage
from hcs_api.blueprint_compatibility import adapt_canonical_presentation_blueprint
from hcs_api.evidence_alignment import check_evidence_alignment
from hcs_api.media import generate_placeholder_media
from hcs_api.models import (
    ActivityPlan,
    CoursewareReviewReport,
    EvidencePlan,
    EvidenceSpec,
    LearningActivity,
    LearningGoal,
    LearningStatePlan,
    LessonBlueprint,
    LessonSlide,
    MediaRequirements,
    QualityReport,
    SlideComponent,
)
from hcs_api.pipeline import run_full_pipeline, write_blueprint_artifacts
from hcs_api.presentation_adapter_assessment import run_presentation_adapter_assessment
from hcs_api.presentation_asset_reconciliation import reconcile_presentation_content_assets
from hcs_api.presentation_bindings import build_activity_bindings
from hcs_api.presentation_blueprint import compile_shadow_presentation
from hcs_api.presentation_content import attach_content_references, build_presentation_content_plan, evaluate_presentation_content_plan
from hcs_api.presentation_media_projection import audit_presentation_media_projection
from hcs_api.presentation_media_requests import build_presentation_media_request_plan
from hcs_api.presentation_parity import run_presentation_parity_harness
from hcs_api.presentation_readiness import check_presentation_readiness
from hcs_api.strategist import build_media_plan
from hcs_api.v2_cutover_readiness import (
    INTERNAL_HTML_PATH,
    REPORT_PATH,
    evaluate_v2_cutover_readiness,
    run_v2_internal_html_cutover,
)
from test_phase2b_milestone import _FixtureRun, _language_items, _run_fixture, _write_fixture_artifacts


def _eligible_fixture(tmp_path: Path, monkeypatch, mode: str = "listening_choice"):
    run = _run_fixture(tmp_path, monkeypatch, mode, "_cutover")
    storage.write_json(run.project_id, "quality/courseware_review_report.json", CoursewareReviewReport().model_dump(mode="json", by_alias=True))
    return run


def _evaluate(run, *, enabled: bool = True):
    return evaluate_v2_cutover_readiness(run.project_id, enabled=enabled, require_courseware_review=True)


def _write_model(run, path: str, model) -> None:
    storage.write_json(run.project_id, path, model.model_dump(mode="json", by_alias=True))


def _multi_unit_fixture(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "phase2b_listening_matching_cutover"
    root = storage.ensure_project(project_id)
    listen_goal = LearningGoal(id="goal_listen", description="Recognize the greeting.", skill_focus="recognition", target_language=["你好"])
    match_goal = LearningGoal(id="goal_match", description="Match approved words.", skill_focus="recognition", target_language=["你好", "再见"])
    listen_evidence = EvidenceSpec(id="evidence_listen", goal_id=listen_goal.id, evidence_type="listen_choose", collection_method="learner_response", target_items=["你好"], acceptable_response={"accepted_values": ["你好"]})
    match_evidence = EvidenceSpec(id="evidence_match", goal_id=match_goal.id, evidence_type="matching", collection_method="learner_response", target_items=["你好", "再见"], acceptable_response={"accepted_values": ["你好"]})
    listen_activity = LearningActivity(id="activity_listen", evidence_ids=[listen_evidence.id], activity_type="listen_choose", learner_action="Listen and choose the greeting.", output_type="selection", allowed_presentation_modes=["html_interactive", "pptx_classroom"])
    match_activity = LearningActivity(id="activity_match", evidence_ids=[match_evidence.id], activity_type="match_pairs", learner_action="Match each approved word with its meaning.", output_type="selection", allowed_presentation_modes=["html_interactive", "pptx_classroom"])
    state = LearningStatePlan(lesson_title="Listening and matching", learner_level="beginner", learning_goals=[listen_goal, match_goal])
    evidence_plan = EvidencePlan(evidence_specs=[listen_evidence, match_evidence])
    activity_plan = ActivityPlan(activities=[listen_activity, match_activity])
    alignment = check_evidence_alignment(state, evidence_plan, activity_plan, "beginner")
    bindings, canonical, shadow = compile_shadow_presentation(state, evidence_plan, activity_plan, alignment)
    assert canonical is not None
    initial, _ = build_presentation_content_plan(state, evidence_plan, activity_plan, bindings, canonical, _language_items())
    request_plan, request_report = build_presentation_media_request_plan(initial)
    legacy = LessonBlueprint(lesson_title="Legacy comparison", slides=[LessonSlide(
        id=1, slide_type="PracticeSlide", layout_variant="mixed", title="Practice",
        components=[
            SlideComponent(id="legacy_listen", component_type="ListenAndChoose", data={"audio_key": "lang_nihao", "audio_text": "你好", "choices": ["你好", "再见"], "answer": "你好"}),
            SlideComponent(id="legacy_match", component_type="MatchGame", data={"pairs": [{"left": "你好", "right": "hello"}, {"left": "再见", "right": "goodbye"}]}),
        ], media_requirements=MediaRequirements(),
    )])
    manifest = generate_placeholder_media(root, legacy, preserve_media_origin_trace=True)
    projection_report, projection_links = audit_presentation_media_projection(request_plan, build_media_plan(legacy), manifest)
    content, reconciliation_report = reconcile_presentation_content_assets(initial, manifest, request_plan, None, projection_links)
    content_report = evaluate_presentation_content_plan(content)
    canonical = attach_content_references(canonical, content)
    adapted = adapt_canonical_presentation_blueprint(canonical, content)
    shadow = shadow.model_copy(update={"compatibility_contract_valid": True})
    run = _FixtureRun(
        "listening_matching", state, evidence_plan, activity_plan, alignment, bindings, canonical, shadow,
        initial, content, content_report, request_plan, request_report, projection_links, projection_report,
        reconciliation_report, adapted, None, None, None, manifest, project_id, root,
    )
    _write_fixture_artifacts(run, build_media_plan(legacy))
    run.adapter_report = run_presentation_adapter_assessment(project_id)
    run.parity_report = run_presentation_parity_harness(project_id)
    v1 = build_activity_bindings(adapted, evidence_plan, activity_plan, state, "beginner")
    run.readiness_report = check_presentation_readiness(adapted, evidence_plan, activity_plan, v1, alignment)
    _write_model(run, "presentation/activity_bindings.json", v1)
    _write_model(run, "quality/presentation_readiness_report.json", run.readiness_report)
    storage.write_json(project_id, "quality/courseware_review_report.json", CoursewareReviewReport().model_dump(mode="json", by_alias=True))
    return run


def test_v2_internal_cutover_disabled_by_default() -> None:
    assert inspect.signature(run_full_pipeline).parameters["enable_v2_internal_html_cutover"].default is False


def test_v2_cutover_gate_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)

    report = run_v2_internal_html_cutover(
        run.project_id, run.root, __import__("hcs_api.models", fromlist=["LessonProfile"]).LessonProfile(),
        run.manifest, QualityReport(), enabled=True,
    )

    assert (run.root / REPORT_PATH).exists()
    assert report.selected_route == "v2_internal_html"


def test_v2_cutover_accepts_listening_only_lesson(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch, "listening_choice")
    report, adapted = _evaluate(run)

    assert report.experiment_eligible is True
    assert report.learner_facing_modes == ["listening_choice"]
    assert adapted is not None


def test_v2_cutover_accepts_matching_only_lesson(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch, "matching_response")
    report, adapted = _evaluate(run)

    assert report.experiment_eligible is True
    assert report.learner_facing_modes == ["matching_response"]
    assert adapted is not None


def test_v2_cutover_accepts_listening_and_matching_lesson_deterministically(tmp_path: Path, monkeypatch) -> None:
    run = _multi_unit_fixture(tmp_path, monkeypatch)
    profile = __import__("hcs_api.models", fromlist=["LessonProfile"]).LessonProfile()

    first = run_v2_internal_html_cutover(run.project_id, run.root, profile, run.manifest, QualityReport(), enabled=True)
    first_html = (run.root / INTERNAL_HTML_PATH).read_bytes()
    second = run_v2_internal_html_cutover(run.project_id, run.root, profile, run.manifest, QualityReport(), enabled=True)

    assert first.experiment_eligible is True
    assert second.experiment_eligible is True
    assert first.learner_facing_modes == ["listening_choice", "matching_response"]
    assert first.whole_lesson_routing is True
    assert (run.root / INTERNAL_HTML_PATH).read_bytes() == first_html


@pytest.mark.parametrize("mode", ["choice_response", "guided_response", "role_play_response", "unknown_mode"])
def test_v2_cutover_requires_whole_lesson_allowlist(tmp_path: Path, monkeypatch, mode: str) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    canonical = run.canonical.model_copy(deep=True)
    content = run.content.model_copy(deep=True)
    canonical.presentation_units[0].presentation_mode = mode
    content.content_items[0].presentation_mode = mode
    _write_model(run, "presentation/presentation_blueprint.json", canonical)
    _write_model(run, "presentation/presentation_content_plan.reconciled.json", content)

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    if mode == "unknown_mode":
        assert report.blocking
    else:
        assert mode in report.unsupported_modes


def test_v2_cutover_does_not_mix_legacy_and_v2_units(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    canonical = run.canonical.model_copy(deep=True)
    duplicate = canonical.presentation_units[0].model_copy(update={
        "presentation_unit_id": "unit_unsupported", "binding_id": "abind_unsupported", "activity_id": "activity_unsupported",
        "presentation_mode": "choice_response", "content_item_id": "content_unsupported",
    })
    canonical.presentation_units.append(duplicate)
    _write_model(run, "presentation/presentation_blueprint.json", canonical)

    report, _ = _evaluate(run)

    assert report.whole_lesson_routing is False
    assert report.selected_route == "legacy"
    assert "choice_response" in report.unsupported_modes


def test_v2_cutover_requires_complete_listening_media_trace(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    content = run.content.model_copy(deep=True)
    content.content_items[0].audio_asset_refs = []
    _write_model(run, "presentation/presentation_content_plan.reconciled.json", content)

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    assert any("Listening unit" in issue for issue in report.blocking)


def test_approximate_media_projection_blocks_v2_cutover(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    links = run.projection_links.model_copy(update={"links": []})
    _write_model(run, "presentation/presentation_media_projection_links.shadow.json", links)

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    assert any("exact or linkable" in issue for issue in report.blocking)


def test_v2_cutover_requires_valid_matching_pairs(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch, "matching_response")
    content = run.content.model_copy(deep=True)
    content.content_items[0].matching_pairs = content.content_items[0].matching_pairs[:1]
    _write_model(run, "presentation/presentation_content_plan.reconciled.json", content)

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    assert any("Matching unit" in issue for issue in report.blocking)


def test_v2_cutover_blocks_teacher_leakage(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    content = run.content.model_copy(deep=True)
    content.content_items[0].teacher_channel_reference = "teacher:private"
    _write_model(run, "presentation/presentation_content_plan.reconciled.json", content)

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    assert report.teacher_leakage_findings


def test_v2_cutover_requires_trace_coverage_one(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    adapter = run.adapter_report.model_copy(update={"trace_coverage": 0.5})
    _write_model(run, "quality/presentation_adapter_assessment_report.json", adapter)

    report, _ = _evaluate(run)

    assert report.trace_coverage == 1.0
    assert any("trace coverage" in issue for issue in report.blocking)


def test_v2_cutover_blocks_missing_required_artifact(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    (run.root / "presentation/presentation_content_plan.reconciled.json").unlink()

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    assert "presentation/presentation_content_plan.reconciled.json" in report.missing_artifacts


def test_v2_cutover_blocks_stale_report(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    report_path = run.root / "quality/presentation_content_report.json"
    source_path = run.root / "presentation/presentation_content_plan.reconciled.json"
    os.utime(report_path, ns=(source_path.stat().st_atime_ns, source_path.stat().st_mtime_ns - 1))

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    assert report.stale_artifacts


def test_v2_cutover_blocks_blocked_courseware_review(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    review = CoursewareReviewReport(state="blocked", blocking=["fixture review block"])
    _write_model(run, "quality/courseware_review_report.json", review)

    report, _ = _evaluate(run)

    assert report.courseware_review_state == "blocked"
    assert report.selected_route == "legacy"


def test_v2_cutover_blocks_stale_courseware_review(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    review_path = run.root / "quality/courseware_review_report.json"
    canonical_path = run.root / "presentation/presentation_blueprint.json"
    os.utime(review_path, ns=(canonical_path.stat().st_atime_ns, canonical_path.stat().st_mtime_ns - 1))

    report, _ = _evaluate(run)

    assert report.selected_route == "legacy"
    assert any("courseware_review_report" in finding for finding in report.stale_artifacts)


def test_v2_cutover_warning_courseware_review_remains_visible(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    review = CoursewareReviewReport(state="warning", warnings=["fixture review warning"])
    _write_model(run, "quality/courseware_review_report.json", review)

    report, _ = _evaluate(run)

    assert report.experiment_eligible is True
    assert "Courseware review: fixture review warning" in report.warnings


def test_v2_internal_html_uses_in_memory_adapter_output_and_preserves_production(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    production = run.root / "blueprints/lesson_blueprint.json"
    before = production.read_bytes()
    legacy_html = run.root / "courseware/lesson.html"
    legacy_html.write_text("legacy sentinel", encoding="utf-8")
    profile = __import__("hcs_api.models", fromlist=["LessonProfile"]).LessonProfile()

    report = run_v2_internal_html_cutover(run.project_id, run.root, profile, run.manifest, QualityReport(), enabled=True)

    internal = run.root / INTERNAL_HTML_PATH
    assert report.selected_route == "v2_internal_html"
    assert "listen-choose" in internal.read_text(encoding="utf-8")
    assert production.read_bytes() == before
    assert legacy_html.read_text(encoding="utf-8") == "legacy sentinel"


def test_failed_v2_gate_removes_stale_internal_html_and_falls_back_to_legacy(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    internal = run.root / INTERNAL_HTML_PATH
    internal.parent.mkdir(parents=True, exist_ok=True)
    internal.write_text("stale", encoding="utf-8")
    (run.root / "presentation/presentation_content_plan.reconciled.json").unlink()
    profile = __import__("hcs_api.models", fromlist=["LessonProfile"]).LessonProfile()

    report = run_v2_internal_html_cutover(run.project_id, run.root, profile, run.manifest, QualityReport(), enabled=True)

    assert report.selected_route == "legacy"
    assert not internal.exists()


def test_manual_blueprint_edit_invalidates_v2_eligibility(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    profile = __import__("hcs_api.models", fromlist=["LessonProfile"]).LessonProfile()
    run_v2_internal_html_cutover(run.project_id, run.root, profile, run.manifest, QualityReport(), enabled=True)
    assert (run.root / INTERNAL_HTML_PATH).exists()

    write_blueprint_artifacts(run.project_id, run.adapted)

    assert not (run.root / INTERNAL_HTML_PATH).exists()
    assert not (run.root / REPORT_PATH).exists()


def test_existing_legacy_projects_remain_unchanged_and_rollback_is_one_flag_change(tmp_path: Path, monkeypatch) -> None:
    run = _eligible_fixture(tmp_path, monkeypatch)
    profile = __import__("hcs_api.models", fromlist=["LessonProfile"]).LessonProfile()

    report = run_v2_internal_html_cutover(run.project_id, run.root, profile, run.manifest, QualityReport(), enabled=False)

    assert report.selected_route == "legacy"
    assert report.experiment_eligible is False
    assert not (run.root / INTERNAL_HTML_PATH).exists()


def test_public_exports_and_editable_pptx_do_not_use_v2_experiment() -> None:
    import hcs_api.pptx_exporter as pptx_exporter
    import hcs_api.storage as storage_module

    assert "lesson_v2_internal" not in inspect.getsource(storage_module.zip_output)
    assert "v2_internal" not in inspect.getsource(pptx_exporter)
