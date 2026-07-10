"""Architecture regression tests for the Phase 2B presentation readiness seam."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import hcs_api.storage as storage
from hcs_api.models import (
    ActivityPlan,
    EvidenceAlignmentReport,
    EvidencePlan,
    EvidenceSpec,
    LearningActivity,
    LessonBlueprint,
    LessonSlide,
    PresentationBinding,
    PresentationBindingPlan,
    SlideComponent,
)
from hcs_api.pipeline import write_presentation_readiness
from hcs_api.presentation_readiness import check_presentation_readiness


def _contracts(*, teacher_only: bool = False):
    blueprint = LessonBlueprint(
        lesson_title="测试课",
        slides=[
            LessonSlide(
                id=1,
                slide_type="PracticeSlide",
                layout_variant="basic",
                title="练习",
                components=[SlideComponent(id="choice_1", component_type="ListenAndChoose")],
            )
        ],
    )
    evidence = EvidenceSpec(
        id="ev_1",
        goal_id="goal_1",
        evidence_type="teacher_observation" if teacher_only else "deterministic_choice",
        collection_method="teacher_observation" if teacher_only else "learner_response",
    )
    activity = LearningActivity(
        id="act_1",
        evidence_ids=["ev_1"],
        activity_type="teacher_observation" if teacher_only else "scene_choice",
        learner_facing=not teacher_only,
    )
    binding = PresentationBinding(
        binding_id="bind_1",
        activity_id="act_1",
        evidence_id="ev_1",
        slide_id=1,
        component_id="choice_1",
        presentation_modes=["teacher_observation"] if teacher_only else ["html_interactive"],
        binding_confidence=1.0,
    )
    return (
        blueprint,
        EvidencePlan(evidence_specs=[evidence]),
        ActivityPlan(activities=[activity]),
        PresentationBindingPlan(bindings=[binding]),
        EvidenceAlignmentReport(),
    )


def test_deprecated_blueprint_fields_emit_warning() -> None:
    blueprint, evidence, activities, bindings, alignment = _contracts()
    blueprint.route_hint = "greeting_lesson"
    blueprint.objectives = ["Recognize 你好"]
    blueprint.key_vocabulary = [{"word": "你好"}]
    blueprint.grammar_points = ["你 vs 您"]

    report = check_presentation_readiness(blueprint, evidence, activities, bindings, alignment)

    assert report.state == "warning"
    assert report.deprecated_blueprint_fields == ["route_hint", "objectives", "key_vocabulary", "grammar_points"]


def test_invalid_binding_blocks_presentation_readiness() -> None:
    blueprint, evidence, activities, bindings, alignment = _contracts()
    bindings.bindings[0].activity_id = "act_missing"

    report = check_presentation_readiness(
        blueprint, evidence, activities, bindings, alignment, binding_strategy="abstract",
    )

    assert report.state == "blocked"
    assert any("unknown activity" in issue for issue in report.invalid_bindings)


def test_missing_activity_binding_blocks_presentation_readiness() -> None:
    blueprint, evidence, activities, _bindings, alignment = _contracts()

    report = check_presentation_readiness(
        blueprint,
        evidence,
        activities,
        PresentationBindingPlan(),
        alignment,
        binding_strategy="abstract",
    )

    assert report.state == "blocked"
    assert report.missing_activity_bindings


def test_teacher_only_evidence_not_allowed_in_learner_binding() -> None:
    blueprint, evidence, activities, bindings, alignment = _contracts(teacher_only=True)
    bindings.bindings[0].presentation_modes = ["html_interactive"]

    report = check_presentation_readiness(
        blueprint, evidence, activities, bindings, alignment, binding_strategy="abstract",
    )

    assert report.state == "blocked"
    assert report.teacher_channel_leaks


def test_v1_blueprint_still_deserializes() -> None:
    blueprint = LessonBlueprint.model_validate(
        {
            "route_hint": "mixed_lesson",
            "lesson_title": "旧课件",
            "objectives": ["旧目标"],
            "key_vocabulary": [{"word": "你好"}],
            "grammar_points": [],
            "slides": [],
        }
    )

    assert blueprint.lesson_title == "旧课件"
    assert blueprint.objectives == ["旧目标"]


def test_blueprint_kernel_owned_fields_block_readiness() -> None:
    blueprint, evidence, activities, bindings, alignment = _contracts()
    blueprint.slides[0].components[0].data = {"learning_goals": []}

    report = check_presentation_readiness(
        blueprint, evidence, activities, bindings, alignment, binding_strategy="abstract",
    )

    assert report.state == "blocked"
    assert any("learning_goals" in issue for issue in report.authority_violations)


def test_readiness_report_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    blueprint, evidence, activities, bindings, alignment = _contracts()

    report = write_presentation_readiness("readiness", blueprint, evidence, activities, bindings, alignment)
    path = tmp_path / "runtime" / "projects" / "readiness" / "quality" / "presentation_readiness_report.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert report.state == "warning"
    assert payload["schema"] == "hanclassstudio.presentation_readiness.v1"
    assert payload["state"] == "warning"


def test_presentation_readiness_blocks_zip_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    storage.ensure_project("blocked_readiness")
    storage.write_json("blocked_readiness", "quality/presentation_readiness_report.json", {"state": "blocked"})

    with pytest.raises(PermissionError, match="Presentation readiness gate"):
        storage.zip_output("blocked_readiness")

    assert storage.zip_output("blocked_readiness", force=True).exists()


def test_renderer_does_not_import_learning_kernel() -> None:
    source_root = Path(__file__).parents[1] / "src" / "hcs_api"
    denied = {"learning_kernel", "evidence", "activity_planner", "evidence_alignment"}

    for filename in ("renderer.py", "pptx_exporter.py"):
        tree = ast.parse((source_root / filename).read_text(encoding="utf-8"))
        imported = {
            node.module.split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not imported & denied, f"{filename} imports kernel modules: {sorted(imported & denied)}"
