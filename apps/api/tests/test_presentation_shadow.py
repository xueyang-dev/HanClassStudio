"""Focused regression tests for the v2 binding-first shadow presentation path."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import hcs_api.storage as storage
from hcs_api.blueprint_compatibility import adapt_canonical_presentation_blueprint
from hcs_api.models import (
    AbstractPresentationBinding,
    ActivityPlan,
    CanonicalPresentationBlueprint,
    EvidenceAlignmentReport,
    EvidencePlan,
    EvidenceSpec,
    LearningActivity,
    LearningGoal,
    LearningStatePlan,
)
from hcs_api.pipeline import write_presentation_shadow_artifacts
from hcs_api.presentation_blueprint import (
    ABSTRACT_BINDING_PATH,
    CANONICAL_BLUEPRINT_PATH,
    SHADOW_REPORT_PATH,
    compile_shadow_presentation,
)


def _contracts(*, teacher_only: bool = False, alignment: EvidenceAlignmentReport | None = None):
    goal = LearningGoal(
        id="goal_1",
        description="Recognize 你好",
        skill_focus="recognition",
        target_language=["你好"],
    )
    state = LearningStatePlan(lesson_title="你好", learning_goals=[goal])
    evidence = EvidenceSpec(
        id="ev_1",
        goal_id=goal.id,
        evidence_type="teacher_observation" if teacher_only else "deterministic_choice",
        collection_method="teacher_observation" if teacher_only else "learner_response",
        target_items=["你好"],
        teacher_observation_notes="Private rubric: re-model before recording." if teacher_only else "",
    )
    activity = LearningActivity(
        id="act_1",
        evidence_ids=[evidence.id],
        activity_type="teacher_observation" if teacher_only else "scene_choice",
        input_type="teacher_prompt" if teacher_only else "prompt",
        output_type="teacher_notes" if teacher_only else "selection",
        learner_facing=not teacher_only,
        fallback_activity="Re-model and retry.",
    )
    return state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), alignment or EvidenceAlignmentReport()


def test_shadow_compiler_does_not_read_lesson_blueprint() -> None:
    import hcs_api.presentation_blueprint as compiler

    source = inspect.getsource(compiler)
    assert "LessonBlueprint" not in source
    assert "lesson_blueprint" not in source


def test_deterministic_presentation_unit_ids() -> None:
    state, evidence, activities, alignment = _contracts()
    first, first_blueprint, _ = compile_shadow_presentation(state, evidence, activities, alignment)
    second, second_blueprint, _ = compile_shadow_presentation(state, evidence, activities, alignment)

    assert [binding.presentation_unit_id for binding in first.bindings] == ["unit_act_1"]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first_blueprint and second_blueprint
    assert first_blueprint.model_dump(mode="json") == second_blueprint.model_dump(mode="json")


def test_abstract_bindings_do_not_require_slide_or_component_ids() -> None:
    state, evidence, activities, alignment = _contracts()
    bindings, _, _ = compile_shadow_presentation(state, evidence, activities, alignment)

    payload = bindings.bindings[0].model_dump(mode="json", by_alias=True)
    assert "slide_id" not in payload
    assert "component_id" not in payload
    assert "layout_variant" not in payload
    with pytest.raises(ValidationError):
        AbstractPresentationBinding.model_validate({**payload, "slide_id": 1})


def test_canonical_presentation_blueprint_contains_no_low_level_layout() -> None:
    state, evidence, activities, alignment = _contracts()
    _, blueprint, _ = compile_shadow_presentation(state, evidence, activities, alignment)
    assert blueprint is not None
    payload = blueprint.model_dump(mode="json", by_alias=True)
    serialized = json.dumps(payload)
    assert all(term not in serialized for term in ("slide_id", "component_id", "layout_variant", "font", "color"))
    payload["presentation_units"][0]["layout_variant"] = "two_column"

    with pytest.raises(ValidationError):
        CanonicalPresentationBlueprint.model_validate(payload)


def test_canonical_presentation_models_reject_goal_objects() -> None:
    payload = {"lesson_title": "测试", "presentation_units": [], "warnings": [], "source_artifacts": [], "compatibility_notes": [], "learning_goals": []}

    with pytest.raises(ValidationError):
        CanonicalPresentationBlueprint.model_validate(payload)


def test_canonical_presentation_models_reject_evidence_spec_objects() -> None:
    payload = {"lesson_title": "测试", "presentation_units": [], "warnings": [], "source_artifacts": [], "compatibility_notes": [], "evidence_specs": []}

    with pytest.raises(ValidationError):
        CanonicalPresentationBlueprint.model_validate(payload)


def test_teacher_only_binding_has_no_learner_mode() -> None:
    state, evidence, activities, alignment = _contracts(teacher_only=True)
    bindings, _, _ = compile_shadow_presentation(state, evidence, activities, alignment)

    binding = bindings.bindings[0]
    assert binding.teacher_only is True
    assert binding.learner_channel == []
    assert set(binding.teacher_channel) <= {"speaker_notes", "teacher_observation", "teacher_html", "diagnostic_export"}


def test_teacher_only_notes_not_in_learner_facing_content() -> None:
    state, evidence, activities, alignment = _contracts(teacher_only=True)
    _, blueprint, _ = compile_shadow_presentation(state, evidence, activities, alignment)
    assert blueprint is not None

    unit = blueprint.presentation_units[0]
    assert unit.learner_facing_content == []
    assert "Private rubric" not in json.dumps(unit.model_dump(mode="json"), ensure_ascii=False)


def test_warning_alignment_allows_shadow_blueprint_with_warning() -> None:
    warning = EvidenceAlignmentReport(state="warning", warnings=["Production evidence is preparatory only."])
    state, evidence, activities, alignment = _contracts(alignment=warning)
    bindings, blueprint, report = compile_shadow_presentation(state, evidence, activities, alignment)

    assert bindings.state == "warning"
    assert blueprint is not None
    assert report.state == "warning"
    assert report.warnings == warning.warnings


def test_blocked_alignment_blocks_shadow_blueprint_pass_state() -> None:
    blocked = EvidenceAlignmentReport(state="blocked", blocking=["Evidence is missing."])
    state, evidence, activities, alignment = _contracts(alignment=blocked)
    bindings, blueprint, report = compile_shadow_presentation(state, evidence, activities, alignment)

    assert bindings.state == "blocked"
    assert blueprint is None
    assert report.state == "blocked"
    assert CANONICAL_BLUEPRINT_PATH not in report.generated_artifacts


def test_compatibility_adapter_preserves_existing_lesson_blueprint_contract() -> None:
    state, evidence, activities, alignment = _contracts()
    _, blueprint, _ = compile_shadow_presentation(state, evidence, activities, alignment)
    assert blueprint is not None

    legacy = adapt_canonical_presentation_blueprint(blueprint)
    assert legacy.lesson_title == "你好"
    assert legacy.slides[0].id == 1
    assert legacy.model_dump(mode="json")["slides"][0]["layout_variant"] == "canonical_shadow"


def test_shadow_legacy_adapter_does_not_select_activities() -> None:
    import hcs_api.blueprint_compatibility as adapter

    source = inspect.getsource(adapter)
    assert "LearningActivity" not in source
    assert "ActivityPlan" not in source
    assert "activity_plan" not in source


def test_shadow_artifacts_written_without_changing_production_blueprint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "shadow_artifacts"
    root = storage.ensure_project(project_id)
    legacy_path = root / "blueprints" / "lesson_blueprint.json"
    legacy_path.write_text('{"lesson_title":"Production blueprint","slides":[]}', encoding="utf-8")
    before = legacy_path.read_text(encoding="utf-8")
    state, evidence, activities, alignment = _contracts()

    _, canonical, report = write_presentation_shadow_artifacts(project_id, state, evidence, activities, alignment)

    assert canonical is not None
    assert report.compatibility_contract_valid is True
    assert legacy_path.read_text(encoding="utf-8") == before
    assert (root / ABSTRACT_BINDING_PATH).exists()
    assert (root / CANONICAL_BLUEPRINT_PATH).exists()
    assert (root / SHADOW_REPORT_PATH).exists()


def test_blocked_shadow_run_removes_stale_canonical_blueprint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "shadow_blocked_rerun"
    root = storage.ensure_project(project_id)
    (root / CANONICAL_BLUEPRINT_PATH).write_text('{"stale":true}', encoding="utf-8")
    state, evidence, activities, _ = _contracts()
    blocked = EvidenceAlignmentReport(state="blocked", blocking=["Evidence is missing."])

    _, canonical, report = write_presentation_shadow_artifacts(project_id, state, evidence, activities, blocked)

    assert canonical is None
    assert report.state == "blocked"
    assert not (root / CANONICAL_BLUEPRINT_PATH).exists()
