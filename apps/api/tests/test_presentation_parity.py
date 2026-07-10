"""Diagnostic-only parity coverage for the v2 presentation compiler."""

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
    LessonBlueprint,
    LessonSlide,
    SlideComponent,
)
from hcs_api.presentation_blueprint import compile_shadow_presentation
from hcs_api.presentation_parity import (
    ABSTRACT_BINDING_PATH,
    CANONICAL_BLUEPRINT_PATH,
    PARITY_REPORT_PATH,
    PRODUCTION_BLUEPRINT_PATH,
    SHADOW_LEGACY_BLUEPRINT_PATH,
    SHADOW_REPORT_PATH,
    run_presentation_parity_harness,
)


def _write_inputs(tmp_path: Path, monkeypatch, *, teacher_only: bool = False, production_slides: int = 1):
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "presentation_parity"
    root = storage.ensure_project(project_id)
    goal = LearningGoal(id="goal_1", description="Recognize 你好", skill_focus="recognition", target_language=["你好"])
    state = LearningStatePlan(lesson_title="你好", learning_goals=[goal])
    evidence = EvidenceSpec(
        id="ev_1",
        goal_id="goal_1",
        evidence_type="teacher_observation" if teacher_only else "deterministic_choice",
        collection_method="teacher_observation" if teacher_only else "learner_response",
        target_items=["你好"],
    )
    activity = LearningActivity(
        id="act_1",
        evidence_ids=["ev_1"],
        activity_type="teacher_observation" if teacher_only else "scene_choice",
        learner_facing=not teacher_only,
        output_type="teacher_notes" if teacher_only else "selection",
    )
    bindings, canonical, shadow = compile_shadow_presentation(
        state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), EvidenceAlignmentReport(),
    )
    assert canonical is not None
    storage.write_json(project_id, ABSTRACT_BINDING_PATH, bindings.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, CANONICAL_BLUEPRINT_PATH, canonical.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, SHADOW_REPORT_PATH, shadow.model_dump(mode="json", by_alias=True))
    production = LessonBlueprint(
        lesson_title="你好",
        slides=[
            LessonSlide(
                id=index,
                slide_type="PracticeSlide",
                layout_variant="basic",
                title="你好",
                content_blocks=[ContentBlock(id=f"text_{index}", text="你好")],
                components=[SlideComponent(id=f"component_{index}", component_type="VocabularyFlipCard", data={"items": [{"word": "你好"}]})],
            )
            for index in range(1, production_slides + 1)
        ],
    )
    storage.write_json(project_id, PRODUCTION_BLUEPRINT_PATH, production.model_dump(mode="json"))
    return project_id, root


def test_parity_harness_writes_shadow_legacy_blueprint(tmp_path: Path, monkeypatch) -> None:
    project_id, root = _write_inputs(tmp_path, monkeypatch)

    report = run_presentation_parity_harness(project_id)

    assert report.state == "warning"
    assert (root / SHADOW_LEGACY_BLUEPRINT_PATH).exists()


def test_parity_report_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    project_id, root = _write_inputs(tmp_path, monkeypatch)

    run_presentation_parity_harness(project_id)

    payload = json.loads((root / PARITY_REPORT_PATH).read_text(encoding="utf-8"))
    assert payload["schema"] == "hanclassstudio.presentation_parity.v1"
    assert payload["visual_parity_checked"] is False


def test_shadow_legacy_blueprint_validates_as_lesson_blueprint(tmp_path: Path, monkeypatch) -> None:
    project_id, root = _write_inputs(tmp_path, monkeypatch)

    run_presentation_parity_harness(project_id)

    LessonBlueprint.model_validate_json((root / SHADOW_LEGACY_BLUEPRINT_PATH).read_text(encoding="utf-8"))


def test_parity_harness_does_not_overwrite_production_blueprint(tmp_path: Path, monkeypatch) -> None:
    project_id, root = _write_inputs(tmp_path, monkeypatch)
    production_path = root / PRODUCTION_BLUEPRINT_PATH
    before = production_path.read_text(encoding="utf-8")

    run_presentation_parity_harness(project_id)

    assert production_path.read_text(encoding="utf-8") == before


def test_parity_harness_detects_teacher_only_leakage(tmp_path: Path, monkeypatch) -> None:
    project_id, _ = _write_inputs(tmp_path, monkeypatch, teacher_only=True)

    def leaking_adapter(canonical):
        legacy = adapt_canonical_presentation_blueprint(canonical)
        legacy.slides.append(LessonSlide(
            id=99,
            slide_type="PracticeSlide",
            layout_variant="basic",
            title="Private",
            content_blocks=[ContentBlock(id="private", text="Teacher-only private rubric")],
        ))
        return legacy

    report = run_presentation_parity_harness(project_id, adapter=leaking_adapter)

    assert report.state == "blocked"
    assert report.teacher_leakage_findings


def test_parity_harness_blocks_invalid_adapter_output(tmp_path: Path, monkeypatch) -> None:
    project_id, _ = _write_inputs(tmp_path, monkeypatch)

    report = run_presentation_parity_harness(project_id, adapter=lambda _canonical: {"slides": "invalid"})

    assert report.state == "blocked"
    assert any("LessonBlueprint-compatible" in issue for issue in report.blocking)


def test_parity_harness_reports_trace_coverage(tmp_path: Path, monkeypatch) -> None:
    project_id, _ = _write_inputs(tmp_path, monkeypatch)

    report = run_presentation_parity_harness(project_id)

    assert report.trace_coverage == 1.0
    assert report.missing_units == []


def test_parity_harness_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    project_id, root = _write_inputs(tmp_path, monkeypatch)

    first = run_presentation_parity_harness(project_id)
    first_payload = (root / SHADOW_LEGACY_BLUEPRINT_PATH).read_text(encoding="utf-8")
    second = run_presentation_parity_harness(project_id)

    assert first.deterministic_output is True
    assert second.deterministic_output is True
    assert (root / SHADOW_LEGACY_BLUEPRINT_PATH).read_text(encoding="utf-8") == first_payload


def test_parity_harness_does_not_require_renderer_cutover() -> None:
    import hcs_api.presentation_parity as parity

    source = inspect.getsource(parity)
    assert "render_lesson" not in source
    assert "export_editable_pptx" not in source


def test_parity_report_warns_when_counts_differ_but_schema_valid(tmp_path: Path, monkeypatch) -> None:
    project_id, _ = _write_inputs(tmp_path, monkeypatch, production_slides=2)

    report = run_presentation_parity_harness(project_id)

    assert report.state == "warning"
    assert not report.blocking
    assert any("Slide count differs" in warning for warning in report.warnings)
