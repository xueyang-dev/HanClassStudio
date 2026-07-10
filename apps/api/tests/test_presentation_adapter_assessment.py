"""Focused capability assessment tests for the v2 compatibility adapter."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import hcs_api.storage as storage
from hcs_api.blueprint_compatibility import adapt_canonical_presentation_blueprint
from hcs_api.models import (
    ActivityPlan,
    ContentBlock,
    EvidenceAlignmentReport,
    EvidencePlan,
    EvidenceSpec,
    LearningActivity,
    LearningGoal,
    LearningStatePlan,
    LessonSlide,
    SlideComponent,
)
from hcs_api.presentation_adapter_assessment import (
    ABSTRACT_BINDING_PATH,
    ASSESSMENT_REPORT_PATH,
    CANONICAL_BLUEPRINT_PATH,
    MAPPING_PLAN_PATH,
    SHADOW_REPORT_PATH,
    run_presentation_adapter_assessment,
)
from hcs_api.presentation_blueprint import compile_shadow_presentation


def _write_inputs(tmp_path: Path, monkeypatch, *, evidence_type: str = "deterministic_choice", teacher_only: bool = False):
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "adapter_assessment"
    root = storage.ensure_project(project_id)
    goal = LearningGoal(id="goal_1", description="Recognize 你好", skill_focus="recognition", target_language=["你好"])
    state = LearningStatePlan(lesson_title="你好", learning_goals=[goal])
    evidence = EvidenceSpec(
        id="ev_1",
        goal_id="goal_1",
        evidence_type="teacher_observation" if teacher_only else evidence_type,
        collection_method="teacher_observation" if teacher_only else "learner_response",
        target_items=["你好", "您好"],
    )
    activity = LearningActivity(
        id="act_1",
        evidence_ids=["ev_1"],
        activity_type="teacher_observation" if teacher_only else "scene_choice",
        output_type="teacher_notes" if teacher_only else "selection",
        learner_facing=not teacher_only,
    )
    bindings, canonical, shadow = compile_shadow_presentation(
        state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), EvidenceAlignmentReport(),
    )
    assert canonical is not None
    storage.write_json(project_id, ABSTRACT_BINDING_PATH, bindings.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, CANONICAL_BLUEPRINT_PATH, canonical.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, SHADOW_REPORT_PATH, shadow.model_dump(mode="json", by_alias=True))
    return project_id, root, canonical


def test_adapter_assessment_report_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_inputs(tmp_path, monkeypatch)

    run_presentation_adapter_assessment(project_id)

    payload = json.loads((root / ASSESSMENT_REPORT_PATH).read_text(encoding="utf-8"))
    assert payload["schema"] == "hanclassstudio.presentation_adapter_assessment.v1"


def test_adapter_assessment_maps_known_presentation_modes(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_inputs(tmp_path, monkeypatch)

    report = run_presentation_adapter_assessment(project_id)

    mapping = json.loads((root / MAPPING_PLAN_PATH).read_text(encoding="utf-8"))["capabilities"]
    assert report.fallback_mappings_count == 1
    assert mapping[0]["presentation_mode"] == "choice_response"
    assert mapping[0]["recommended_legacy_component_type"] == "VocabularyFlipCard"


def test_adapter_assessment_flags_unsupported_learner_mode(tmp_path: Path, monkeypatch) -> None:
    project_id, _, _ = _write_inputs(tmp_path, monkeypatch, evidence_type="listen_choose")

    report = run_presentation_adapter_assessment(project_id)

    assert report.state == "blocked"
    assert report.unsupported_modes == ["listening_choice"]


def test_adapter_assessment_preserves_trace_metadata(tmp_path: Path, monkeypatch) -> None:
    project_id, _, _ = _write_inputs(tmp_path, monkeypatch)

    report = run_presentation_adapter_assessment(project_id)

    assert report.trace_coverage == 1.0


def test_adapter_assessment_blocks_teacher_leakage(tmp_path: Path, monkeypatch) -> None:
    project_id, _, canonical = _write_inputs(tmp_path, monkeypatch, teacher_only=True)

    def leaking_adapter(blueprint):
        legacy = adapt_canonical_presentation_blueprint(blueprint)
        unit = canonical.presentation_units[0]
        legacy.slides.append(LessonSlide(
            id=99,
            slide_type="PracticeSlide",
            layout_variant="basic",
            title="Teacher-only",
            content_blocks=[ContentBlock(id="private", text="Teacher-only private rubric")],
            components=[SlideComponent(
                id="teacher_trace",
                component_type="VocabularyFlipCard",
                data={"items": [{"word": "你好"}], "_shadow_trace": unit.trace.model_dump(mode="json")},
            )],
        ))
        return legacy

    report = run_presentation_adapter_assessment(project_id, adapter=leaking_adapter)

    assert report.state == "blocked"
    assert report.teacher_channel_findings


def test_adapter_assessment_warns_on_fallback_mapping(tmp_path: Path, monkeypatch) -> None:
    project_id, _, _ = _write_inputs(tmp_path, monkeypatch)

    report = run_presentation_adapter_assessment(project_id)

    assert report.state == "warning"
    assert report.fallback_modes == ["choice_response"]


def test_adapter_assessment_does_not_require_renderer_changes() -> None:
    import hcs_api.presentation_adapter_assessment as assessment

    source = inspect.getsource(assessment)
    assert "render_lesson" not in source
    assert "export_editable_pptx" not in source


def test_adapter_assessment_does_not_read_production_blueprint_as_authority() -> None:
    import hcs_api.presentation_adapter_assessment as assessment

    assert "blueprints/lesson_blueprint.json" not in inspect.getsource(assessment)


def test_adapter_payload_requirements_are_validated(tmp_path: Path, monkeypatch) -> None:
    project_id, _, _ = _write_inputs(tmp_path, monkeypatch, evidence_type="listen_choose")

    report = run_presentation_adapter_assessment(project_id)

    assert any("choices, answer, audio_key" in finding for finding in report.component_payload_findings)


def test_teacher_only_units_are_not_mapped_to_learner_components(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_inputs(tmp_path, monkeypatch, teacher_only=True)

    report = run_presentation_adapter_assessment(project_id)

    mapping = json.loads((root / MAPPING_PLAN_PATH).read_text(encoding="utf-8"))["capabilities"]
    assert report.teacher_only_units_count == 1
    assert mapping[0]["mapping_quality"] == "teacher_only"
    assert mapping[0]["recommended_legacy_component_type"] is None


def test_registered_component_mapping_preferred_over_generic_fallback_when_available(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_inputs(tmp_path, monkeypatch)

    run_presentation_adapter_assessment(project_id)

    capability = json.loads((root / MAPPING_PLAN_PATH).read_text(encoding="utf-8"))["capabilities"][0]
    assert capability["recommended_legacy_component_type"] == "VocabularyFlipCard"
    assert capability["renderer_supported"] is True


def test_visual_parity_marked_unchecked(tmp_path: Path, monkeypatch) -> None:
    project_id, _, _ = _write_inputs(tmp_path, monkeypatch)

    report = run_presentation_adapter_assessment(project_id)

    assert report.visual_parity_checked is False
