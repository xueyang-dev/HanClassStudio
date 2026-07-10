"""Boundary tests for the shadow-only Presentation Content Contract."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import hcs_api.storage as storage
from hcs_api.blueprint_compatibility import adapt_canonical_presentation_blueprint
from hcs_api.models import (
    ActivityPlan,
    AssetFile,
    AssetManifest,
    EvidenceAlignmentReport,
    EvidencePlan,
    EvidenceSpec,
    LanguageItem,
    LearningActivity,
    LearningGoal,
    LearningStatePlan,
    PresentationContentItem,
)
from hcs_api.pipeline import write_presentation_content_shadow_artifacts
from hcs_api.presentation_adapter_assessment import run_presentation_adapter_assessment
from hcs_api.presentation_blueprint import compile_shadow_presentation
from hcs_api.presentation_content import (
    CONTENT_PLAN_PATH,
    CONTENT_REPORT_PATH,
    attach_content_references,
    build_presentation_content_plan,
)


def _contracts(
    evidence_type: str = "deterministic_choice",
    *,
    target_items: list[str] | None = None,
    accepted_values: list[str] | None = None,
    teacher_only: bool = False,
):
    target_items = target_items if target_items is not None else ["你好"]
    goal = LearningGoal(id="goal_1", description="Use the approved greeting.", skill_focus="recognition", target_language=target_items)
    state = LearningStatePlan(lesson_title="你好", learning_goals=[goal])
    evidence = EvidenceSpec(
        id="ev_1",
        goal_id="goal_1",
        evidence_type="teacher_observation" if teacher_only else evidence_type,
        collection_method="teacher_observation" if teacher_only else "learner_response",
        target_items=target_items,
        acceptable_response={"accepted_values": accepted_values} if accepted_values is not None else {},
        observable_behavior="Choose or use the approved greeting.",
    )
    activity = LearningActivity(
        id="act_1",
        evidence_ids=["ev_1"],
        activity_type="teacher_observation" if teacher_only else "scene_choice",
        learner_action="Choose the approved response." if not teacher_only else "",
        teacher_action="Private teacher observation notes.",
        interaction_mode="pair" if evidence_type == "role_play" else "individual",
        output_type="teacher_notes" if teacher_only else "response" if evidence_type in {"constrained_production", "role_play"} else "selection",
        learner_facing=not teacher_only,
        fallback_activity="Teacher-only fallback instruction.",
    )
    bindings, canonical, shadow = compile_shadow_presentation(
        state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), EvidenceAlignmentReport(),
    )
    assert canonical is not None
    return state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), bindings, canonical, shadow


def _language_items() -> list[LanguageItem]:
    return [
        LanguageItem(id="lang_nihao", target_form="你好", scaffold_meaning="hello", source_evidence="source"),
        LanguageItem(id="lang_ninhao", target_form="您好", scaffold_meaning="hello (polite)", source_evidence="source"),
    ]


def _build(*args, language_items=None, assets=None, **kwargs):
    state, evidence, activity, bindings, canonical, shadow = _contracts(*args, **kwargs)
    plan, report = build_presentation_content_plan(
        state, evidence, activity, bindings, canonical, language_items if language_items is not None else _language_items(), assets,
    )
    return state, evidence, activity, bindings, attach_content_references(canonical, plan), shadow, plan, report


def test_presentation_content_plan_serializes_to_presentation_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    state, evidence, activity, bindings, canonical, _, _, _ = _build()

    write_presentation_content_shadow_artifacts("content", state, evidence, activity, bindings, canonical, _language_items())

    assert (tmp_path / "runtime" / "projects" / "content" / CONTENT_PLAN_PATH).exists()


def test_presentation_content_report_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    state, evidence, activity, bindings, canonical, _, _, _ = _build()

    write_presentation_content_shadow_artifacts("content_report", state, evidence, activity, bindings, canonical, _language_items())

    payload = json.loads((tmp_path / "runtime" / "projects" / "content_report" / CONTENT_REPORT_PATH).read_text(encoding="utf-8"))
    assert payload["schema"] == "hanclassstudio.presentation_content_report.v1"


def test_content_planner_does_not_read_lesson_blueprint() -> None:
    import hcs_api.presentation_content as content

    assert "lesson_blueprint" not in inspect.getsource(content)


def test_content_planner_does_not_change_presentation_mode() -> None:
    _, _, _, _, canonical, _, plan, _ = _build("listen_choose")

    assert plan.content_items[0].presentation_mode == canonical.presentation_units[0].presentation_mode


def test_content_models_reject_slide_component_and_layout_fields() -> None:
    _, _, _, _, _, _, plan, _ = _build()
    for forbidden in ("slide_id", "component_id", "layout_variant", "font", "color"):
        payload = plan.content_items[0].model_dump(mode="json")
        payload[forbidden] = "forbidden"
        with pytest.raises(ValidationError):
            PresentationContentItem.model_validate(payload)


def test_choice_response_requires_options_and_accepted_response() -> None:
    _, _, _, _, _, _, _, report = _build("deterministic_choice", target_items=[], language_items=[])

    assert report.state == "blocked"
    assert report.missing_options
    assert report.missing_accepted_responses


def test_listening_choice_requires_available_audio_reference() -> None:
    _, _, _, _, _, _, plan, report = _build("listen_choose")

    assert report.state == "blocked"
    assert report.missing_audio_assets
    assert plan.content_items[0].audio_asset_refs[0].availability == "missing"


def test_listening_choice_uses_existing_audio_reference_without_generating_audio() -> None:
    assets = AssetManifest(audio=[AssetFile(id="audio_nihao", kind="audio", path="assets/audio/nihao.wav", text="你好")])
    _, _, _, _, canonical, _, plan, report = _build("listen_choose", assets=assets)

    adapted = adapt_canonical_presentation_blueprint(canonical, plan)

    assert report.state == "pass"
    assert adapted.slides[0].components[0].component_type == "ListenAndChoose"
    assert adapted.slides[0].components[0].data["audio_key"] == "audio_nihao"


def test_matching_response_requires_valid_pairs() -> None:
    _, _, _, _, _, _, _, report = _build("matching", language_items=[_language_items()[0]])

    assert report.state == "blocked"
    assert report.missing_matching_pairs


def test_guided_response_has_prompt_and_response_guidance() -> None:
    _, _, _, _, _, _, plan, report = _build("constrained_production")
    item = plan.content_items[0]

    assert item.prompt
    assert item.learner_instructions
    assert item.complete is True
    assert report.state in {"pass", "warning"}


def test_role_play_content_contains_only_learner_safe_roles() -> None:
    _, _, _, _, _, _, plan, _ = _build("role_play")
    item = plan.content_items[0]

    assert item.complete is True
    assert "teacher-only" not in json.dumps(item.model_dump(mode="json")).lower()
    assert item.learner_instructions


def test_teacher_observation_produces_no_learner_content() -> None:
    _, _, _, _, _, _, plan, report = _build(teacher_only=True)
    item = plan.content_items[0]

    assert item.prompt == ""
    assert item.display_items == []
    assert item.options == []
    assert item.teacher_channel_reference
    assert report.teacher_only_items


def test_accepted_responses_derive_from_evidence_contract() -> None:
    _, _, _, _, _, _, plan, _ = _build("deterministic_choice", accepted_values=["您好"])

    accepted = plan.content_items[0].accepted_responses[0]
    assert accepted.value == "您好"
    assert accepted.provenance == ["evidence.acceptable_response"]


def test_content_items_preserve_activity_evidence_unit_trace() -> None:
    _, evidence, activity, _, canonical, _, plan, _ = _build()
    item = plan.content_items[0]

    assert item.activity_id == activity.activities[0].activity_id
    assert item.evidence_ids == [evidence.evidence_specs[0].evidence_id]
    assert item.presentation_unit_id == canonical.presentation_units[0].presentation_unit_id
    assert item.trace.activity_id == item.activity_id


def test_content_generation_is_deterministic() -> None:
    *_, first, first_report = _build()
    *_, second, second_report = _build()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first_report.model_dump(mode="json") == second_report.model_dump(mode="json")


def test_missing_required_content_blocks_content_report() -> None:
    _, _, _, _, _, _, _, report = _build("listen_choose")

    assert report.state == "blocked"


def test_adapter_uses_content_contract_for_choice_payload() -> None:
    _, _, _, _, canonical, _, plan, _ = _build("deterministic_choice", accepted_values=["你好"])

    adapted = adapt_canonical_presentation_blueprint(canonical, plan)

    assert adapted.slides[0].components[0].component_type == "VocabularyFlipCard"
    assert [item["word"] for item in adapted.slides[0].components[0].data["items"]] == [option.text for option in plan.content_items[0].options]


def test_adapter_uses_content_contract_for_matching_payload() -> None:
    _, _, _, _, canonical, _, plan, report = _build("matching")
    assert report.state == "pass"

    adapted = adapt_canonical_presentation_blueprint(canonical, plan)

    assert adapted.slides[0].components[0].component_type == "MatchGame"
    assert len(adapted.slides[0].components[0].data["pairs"]) == 2


def test_adapter_does_not_fabricate_missing_payload() -> None:
    _, _, _, _, canonical, _, plan, report = _build("listen_choose")
    assert report.state == "blocked"

    adapted = adapt_canonical_presentation_blueprint(canonical, plan)

    assert adapted.slides[0].components == []


def test_adapter_assessment_recomputed_after_content_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    state, evidence, activity, bindings, canonical, shadow, plan, _ = _build("matching")
    root = storage.ensure_project("assessment_content")
    storage.write_json("assessment_content", "presentation/abstract_activity_bindings.json", bindings.model_dump(mode="json", by_alias=True))
    storage.write_json("assessment_content", "presentation/presentation_blueprint.json", canonical.model_dump(mode="json", by_alias=True))
    storage.write_json("assessment_content", "quality/presentation_shadow_report.json", shadow.model_dump(mode="json", by_alias=True))
    storage.write_json("assessment_content", CONTENT_PLAN_PATH, plan.model_dump(mode="json", by_alias=True))

    report = run_presentation_adapter_assessment("assessment_content")

    assert report.state == "warning"
    assert report.exact_mappings_count == 1
    assert report.unsupported_mappings_count == 0


def test_production_blueprint_and_renderers_remain_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    root = storage.ensure_project("production_unchanged")
    production = root / "blueprints" / "lesson_blueprint.json"
    production.write_text('{"lesson_title":"Production","slides":[]}', encoding="utf-8")
    before = production.read_text(encoding="utf-8")
    state, evidence, activity, bindings, canonical, _, _, _ = _build()

    write_presentation_content_shadow_artifacts("production_unchanged", state, evidence, activity, bindings, canonical, _language_items())

    assert production.read_text(encoding="utf-8") == before
