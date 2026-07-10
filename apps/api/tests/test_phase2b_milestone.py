"""Phase 2B end-to-end shadow milestone fixtures and release-gate invariants."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hcs_api.storage as storage
from hcs_api.blueprint_compatibility import adapt_canonical_presentation_blueprint
from hcs_api.evidence_alignment import check_evidence_alignment
from hcs_api.media import generate_placeholder_media
from hcs_api.models import (
    ActivityPlan,
    AssetManifest,
    EvidenceAlignmentReport,
    EvidencePlan,
    EvidenceSpec,
    LanguageItem,
    LearningActivity,
    LearningGoal,
    LearningStatePlan,
    LessonBlueprint,
    LessonProfile,
    LessonSlide,
    MediaRequirements,
    PresentationContentPlan,
    QualityReport,
    SlideComponent,
)
from hcs_api.pipeline import SHADOW_PRESENTATION_ARTIFACTS, write_presentation_shadow_artifacts
from hcs_api.presentation_adapter_assessment import run_presentation_adapter_assessment
from hcs_api.presentation_asset_reconciliation import reconcile_presentation_content_assets
from hcs_api.presentation_bindings import build_activity_bindings
from hcs_api.presentation_blueprint import compile_shadow_presentation
from hcs_api.presentation_content import attach_content_references, build_presentation_content_plan, evaluate_presentation_content_plan
from hcs_api.presentation_media_projection import audit_presentation_media_projection
from hcs_api.presentation_media_requests import build_presentation_media_request_plan
from hcs_api.presentation_parity import run_presentation_parity_harness
from hcs_api.presentation_readiness import check_presentation_readiness
from hcs_api.pptx_deck import build_pptx_deck_plan
from hcs_api.renderer import render_lesson
from hcs_api.strategist import build_media_plan


@dataclass
class _FixtureRun:
    mode: str
    state_plan: LearningStatePlan
    evidence_plan: EvidencePlan
    activity_plan: ActivityPlan
    alignment: Any
    bindings: Any
    canonical: Any
    shadow: Any
    initial_content: PresentationContentPlan
    content: PresentationContentPlan
    content_report: Any
    request_plan: Any
    request_report: Any
    projection_links: Any
    projection_report: Any
    reconciliation_report: Any
    adapted: LessonBlueprint
    adapter_report: Any
    parity_report: Any
    readiness_report: Any
    manifest: AssetManifest
    project_id: str
    root: Path


def _language_items() -> list[LanguageItem]:
    return [
        LanguageItem(id="lang_nihao", target_form="你好", scaffold_meaning="hello", source_evidence="approved fixture source"),
        LanguageItem(id="lang_zaijian", target_form="再见", scaffold_meaning="goodbye", source_evidence="approved fixture source"),
    ]


def _contracts(mode: str):
    evidence_type = {
        "guided_response": "constrained_production",
        "listening_choice": "listen_choose",
        "matching_response": "matching",
    }[mode]
    activity_type = {
        "guided_response": "guided_response",
        "listening_choice": "listen_choose",
        "matching_response": "match_pairs",
    }[mode]
    output_type = "response" if mode == "guided_response" else "selection"
    targets = ["你好", "再见"] if mode == "matching_response" else ["你好"]
    goal = LearningGoal(
        id=f"goal_{mode}", description=f"Complete the approved {mode} activity.",
        skill_focus="production" if mode == "guided_response" else "recognition",
        target_language=targets, expected_behavior="Use only approved target-language content.",
        justification="Controlled Phase 2B milestone fixture.",
    )
    evidence = EvidenceSpec(
        id=f"evidence_{mode}", goal_id=goal.id, evidence_type=evidence_type,
        observable_behavior=f"Complete the approved {mode} response.", collection_method="learner_response",
        acceptable_response={"accepted_values": ["你好"]}, target_items=targets,
    )
    activity = LearningActivity(
        id=f"activity_{mode}", evidence_ids=[evidence.id], activity_type=activity_type,
        learner_action={
            "guided_response": "Say the approved greeting.",
            "listening_choice": "Listen and choose the greeting you hear.",
            "matching_response": "Match each approved word with its meaning.",
        }[mode],
        teacher_action="Private teacher facilitation note that must remain hidden.",
        interaction_mode="individual", input_type="audio" if mode == "listening_choice" else "prompt",
        output_type=output_type, fallback_activity="Use the displayed approved items and retry.",
        allowed_presentation_modes=["html_interactive", "pptx_classroom"],
    )
    state = LearningStatePlan(lesson_title=f"Fixture {mode}", learner_level="beginner", learning_goals=[goal])
    evidence_plan = EvidencePlan(evidence_specs=[evidence])
    activity_plan = ActivityPlan(activities=[activity])
    return state, evidence_plan, activity_plan


def _legacy_listening_blueprint() -> LessonBlueprint:
    return LessonBlueprint(lesson_title="Fixture listening_choice", slides=[LessonSlide(
        id=1, slide_type="PracticeSlide", layout_variant="listen_choose", title="听一听",
        components=[SlideComponent(
            id="legacy_listen", component_type="ListenAndChoose",
            data={"audio_key": "lang_nihao", "audio_text": "你好", "choices": ["你好", "再见"], "answer": "你好"},
        )],
        media_requirements=MediaRequirements(),
    )])


def _write_fixture_artifacts(run: _FixtureRun, legacy_media_plan: dict) -> None:
    payloads = {
        "learning/learning_state_plan.json": run.state_plan,
        "learning/evidence_plan.json": run.evidence_plan,
        "learning/activity_plan.json": run.activity_plan,
        "quality/evidence_alignment_report.json": run.alignment,
        "presentation/abstract_activity_bindings.json": run.bindings,
        "presentation/presentation_blueprint.json": run.canonical,
        "quality/presentation_shadow_report.json": run.shadow,
        "presentation/presentation_content_plan.json": run.initial_content,
        "presentation/presentation_content_plan.reconciled.json": run.content,
        "quality/presentation_content_report.json": run.content_report,
        "presentation/presentation_media_request_plan.json": run.request_plan,
        "quality/presentation_media_request_report.json": run.request_report,
        "presentation/presentation_media_projection_links.shadow.json": run.projection_links,
        "quality/presentation_media_projection_report.json": run.projection_report,
        "quality/presentation_asset_reconciliation_report.json": run.reconciliation_report,
    }
    for path, model in payloads.items():
        storage.write_json(run.project_id, path, model.model_dump(mode="json", by_alias=True))
    storage.write_json(run.project_id, "blueprints/media_plan.json", legacy_media_plan)
    storage.write_model(run.project_id, "asset_manifest.json", run.manifest)
    storage.write_model(run.project_id, "lesson_blueprint.json", run.adapted)


def _run_fixture(tmp_path: Path, monkeypatch, mode: str, suffix: str = "") -> _FixtureRun:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = f"phase2b_{mode}{suffix}"
    root = storage.ensure_project(project_id)
    state, evidence_plan, activity_plan = _contracts(mode)
    alignment = check_evidence_alignment(state, evidence_plan, activity_plan, "beginner")
    bindings, canonical, shadow = compile_shadow_presentation(state, evidence_plan, activity_plan, alignment)
    assert canonical is not None
    initial_content, _initial_report = build_presentation_content_plan(
        state, evidence_plan, activity_plan, bindings, canonical, _language_items(),
    )
    request_plan, request_report = build_presentation_media_request_plan(initial_content)

    if mode == "listening_choice":
        production_media_blueprint = _legacy_listening_blueprint()
        legacy_media_plan = build_media_plan(production_media_blueprint)
        manifest = generate_placeholder_media(root, production_media_blueprint, preserve_media_origin_trace=True)
    else:
        legacy_media_plan = {"schema": "hanclassstudio.media_plan.v1", "images": [], "audio": [], "video": []}
        manifest = AssetManifest()
    projection_report, projection_links = audit_presentation_media_projection(request_plan, legacy_media_plan, manifest)
    content, reconciliation_report = reconcile_presentation_content_assets(
        initial_content, manifest, request_plan, None, projection_links,
    )
    content_report = evaluate_presentation_content_plan(content)
    canonical = attach_content_references(canonical, content)
    adapted = adapt_canonical_presentation_blueprint(canonical, content)
    shadow = shadow.model_copy(update={"compatibility_contract_valid": True})

    placeholder = _FixtureRun(
        mode, state, evidence_plan, activity_plan, alignment, bindings, canonical, shadow,
        initial_content, content, content_report, request_plan, request_report, projection_links,
        projection_report, reconciliation_report, adapted, None, None, None, manifest, project_id, root,
    )
    _write_fixture_artifacts(placeholder, legacy_media_plan)
    production_before = (root / "blueprints/lesson_blueprint.json").read_bytes()
    adapter_report = run_presentation_adapter_assessment(project_id)
    parity_report = run_presentation_parity_harness(project_id)
    assert (root / "blueprints/lesson_blueprint.json").read_bytes() == production_before

    v1_bindings = build_activity_bindings(adapted, evidence_plan, activity_plan, state, "beginner")
    readiness = check_presentation_readiness(adapted, evidence_plan, activity_plan, v1_bindings, alignment)
    storage.write_json(project_id, "presentation/activity_bindings.json", v1_bindings.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, "quality/presentation_readiness_report.json", readiness.model_dump(mode="json", by_alias=True))
    placeholder.adapter_report = adapter_report
    placeholder.parity_report = parity_report
    placeholder.readiness_report = readiness
    return placeholder


def _trace_tuple(run: _FixtureRun) -> tuple[str, str, str, tuple[str, ...]]:
    binding = run.bindings.bindings[0]
    item = run.content.content_items[0]
    unit = run.canonical.presentation_units[0]
    return unit.presentation_unit_id, item.activity_id, binding.activity_id, tuple(item.evidence_ids)


def test_phase2b_fixture_a_no_media_end_to_end(tmp_path: Path, monkeypatch) -> None:
    run = _run_fixture(tmp_path, monkeypatch, "guided_response")
    component = run.adapted.slides[0].components[0]

    assert run.alignment.state == "pass"
    assert run.content_report.state == "pass"
    assert run.request_plan.requests == []
    assert component.component_type == "VocabularyFlipCard"
    assert component.data["items"]
    assert run.adapted.slides[0].content_blocks
    assert run.adapter_report.state == "warning"
    assert run.adapter_report.approximate_mappings_count == 1


def test_phase2b_fixture_b_listening_with_exact_audio_trace(tmp_path: Path, monkeypatch) -> None:
    run = _run_fixture(tmp_path, monkeypatch, "listening_choice")
    request = run.request_plan.requests[0]
    asset = run.manifest.audio[0]
    component = run.adapted.slides[0].components[0]

    assert request.id.startswith("pmr_")
    assert asset.origin_media_requirement_ids == ["lang_nihao"]
    assert run.projection_report.approximate_matches_count == 0
    assert run.projection_report.linkable_matches_count == 1
    assert run.projection_report.projection_chain_complete is True
    assert run.reconciliation_report.state == "pass"
    assert component.component_type == "ListenAndChoose"
    assert component.data["choices"] == ["你好", "再见"]
    assert component.data["answer"] == "你好"
    assert component.data["audio_key"] == asset.id
    assert run.adapter_report.exact_mappings_count == 1


def test_phase2b_fixture_c_matching_with_approved_pairs(tmp_path: Path, monkeypatch) -> None:
    run = _run_fixture(tmp_path, monkeypatch, "matching_response")
    item = run.content.content_items[0]
    component = run.adapted.slides[0].components[0]

    assert run.content_report.state == "pass"
    assert [pair.id for pair in item.matching_pairs] == [
        "pair_unit_activity_matching_response_1", "pair_unit_activity_matching_response_2",
    ]
    assert len({pair.left for pair in item.matching_pairs}) == 2
    assert len({pair.right for pair in item.matching_pairs}) == 2
    assert all(pair.provenance[0] == "analysis/language_items.json" for pair in item.matching_pairs)
    assert component.component_type == "MatchGame"
    assert component.data["pairs"] == [{"left": "你好", "right": "hello"}, {"left": "再见", "right": "goodbye"}]
    assert run.adapter_report.exact_mappings_count == 1


def test_phase2b_all_trace_ids_are_continuous(tmp_path: Path, monkeypatch) -> None:
    for mode in ("guided_response", "listening_choice", "matching_response"):
        run = _run_fixture(tmp_path, monkeypatch, mode, "_trace")
        unit_id, item_activity, binding_activity, evidence_ids = _trace_tuple(run)
        trace = run.adapted.slides[0].components[0].data["_shadow_trace"]
        assert unit_id == trace["presentation_unit_id"]
        assert item_activity == binding_activity == trace["activity_id"]
        assert evidence_ids == tuple(trace["evidence_ids"])
        assert run.adapter_report.trace_coverage == 1.0
        learner_payload = json.dumps(run.adapted.model_dump(mode="json")).lower()
        assert "private teacher" not in learner_payload


def test_phase2b_teacher_content_never_enters_learner_payload() -> None:
    goal = LearningGoal(id="goal_teacher", description="Teacher observation", skill_focus="recognition", target_language=["你好"])
    evidence = EvidenceSpec(
        id="evidence_teacher", goal_id=goal.id, evidence_type="teacher_observation",
        collection_method="teacher_observation", teacher_observation_notes="Private rubric: do not show.", target_items=["你好"],
    )
    activity = LearningActivity(
        id="activity_teacher", evidence_ids=[evidence.id], activity_type="teacher_observation",
        teacher_action="Private teacher observation notes.", learner_facing=False, output_type="teacher_notes",
    )
    state = LearningStatePlan(lesson_title="Teacher safety", learning_goals=[goal])
    evidence_plan = EvidencePlan(evidence_specs=[evidence])
    activity_plan = ActivityPlan(activities=[activity])
    alignment = check_evidence_alignment(state, evidence_plan, activity_plan)
    bindings, canonical, _ = compile_shadow_presentation(state, evidence_plan, activity_plan, alignment)
    assert canonical is not None
    content, report = build_presentation_content_plan(state, evidence_plan, activity_plan, bindings, canonical, _language_items())
    adapted = adapt_canonical_presentation_blueprint(attach_content_references(canonical, content), content)

    assert report.state in {"pass", "warning"}
    assert content.content_items[0].prompt == ""
    assert content.content_items[0].display_items == []
    assert adapted.slides == []
    assert "private rubric" not in json.dumps(adapted.model_dump(mode="json")).lower()


def test_phase2b_outputs_are_deterministic(tmp_path: Path, monkeypatch) -> None:
    for mode in ("guided_response", "listening_choice", "matching_response"):
        first = _run_fixture(tmp_path, monkeypatch, mode, "_det_a")
        second = _run_fixture(tmp_path, monkeypatch, mode, "_det_b")
        assert first.bindings.model_dump(mode="json") == second.bindings.model_dump(mode="json")
        assert first.content.model_dump(mode="json") == second.content.model_dump(mode="json")
        assert first.canonical.model_dump(mode="json") == second.canonical.model_dump(mode="json")
        assert first.adapted.model_dump(mode="json") == second.adapted.model_dump(mode="json")


def test_phase2b_blocked_upstream_invalidates_downstream_shadow_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "phase2b_stale"
    root = storage.ensure_project(project_id)
    for path in SHADOW_PRESENTATION_ARTIFACTS:
        storage.write_json(project_id, path, {"state": "pass", "stale": True})
    state, evidence_plan, activity_plan = _contracts("guided_response")
    blocked = EvidenceAlignmentReport(state="blocked", blocking=["fixture block"])

    _bindings, canonical, report = write_presentation_shadow_artifacts(project_id, state, evidence_plan, activity_plan, blocked)

    assert canonical is None
    assert report.state == "blocked"
    assert all(not (root / path).exists() for path in SHADOW_PRESENTATION_ARTIFACTS)
    assert (root / "presentation/abstract_activity_bindings.json").exists()
    assert json.loads((root / "quality/presentation_shadow_report.json").read_text(encoding="utf-8"))["state"] == "blocked"


def test_phase2b_report_states_are_consistent(tmp_path: Path, monkeypatch) -> None:
    expected = {
        "guided_response": ("pass", "pass", "pass", "pass", "pass", "pass", "warning", "warning", "warning"),
        "listening_choice": ("pass", "pass", "warning", "pass", "pass", "pass", "warning", "warning", "warning"),
        "matching_response": ("pass", "pass", "pass", "pass", "pass", "pass", "warning", "warning", "warning"),
    }
    for mode, states in expected.items():
        run = _run_fixture(tmp_path, monkeypatch, mode, "_reports")
        actual = (
            run.alignment.state, run.content_report.state, run.request_report.state,
            run.projection_report.state, run.reconciliation_report.state, run.shadow.state,
            run.adapter_report.state, run.parity_report.state, run.readiness_report.state,
        )
        assert actual == states


def test_phase2b_required_artifacts_are_emitted_by_fixture(tmp_path: Path, monkeypatch) -> None:
    run = _run_fixture(tmp_path, monkeypatch, "listening_choice", "_artifacts")
    expected = {
        "learning/learning_state_plan.json",
        "learning/evidence_plan.json",
        "learning/activity_plan.json",
        "quality/evidence_alignment_report.json",
        "presentation/presentation_content_plan.json",
        "presentation/presentation_content_plan.reconciled.json",
        "quality/presentation_content_report.json",
        "presentation/presentation_media_request_plan.json",
        "quality/presentation_media_request_report.json",
        "presentation/presentation_media_projection_links.shadow.json",
        "quality/presentation_media_projection_report.json",
        "presentation/abstract_activity_bindings.json",
        "presentation/presentation_blueprint.json",
        "presentation/legacy_blueprint_from_v2.shadow.json",
        "quality/presentation_shadow_report.json",
        "quality/presentation_parity_report.json",
        "presentation/legacy_component_mapping.shadow.json",
        "quality/presentation_adapter_assessment_report.json",
        "quality/presentation_asset_reconciliation_report.json",
        "quality/presentation_readiness_report.json",
        "blueprints/lesson_blueprint.json",
    }

    assert all((run.root / path).exists() for path in expected)


def test_phase2b_production_blueprint_remains_unchanged(tmp_path: Path, monkeypatch) -> None:
    run = _run_fixture(tmp_path, monkeypatch, "listening_choice", "_production")
    before = (run.root / "blueprints/lesson_blueprint.json").read_bytes()
    rendered = run.root / "courseware/lesson.html"
    rendered.write_text("production sentinel", encoding="utf-8")

    run_presentation_adapter_assessment(run.project_id)
    run_presentation_parity_harness(run.project_id)

    assert (run.root / "blueprints/lesson_blueprint.json").read_bytes() == before
    assert rendered.read_text(encoding="utf-8") == "production sentinel"


def test_phase2b_existing_projects_remain_compatible(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "phase2b_legacy_only"
    storage.ensure_project(project_id)
    storage.write_model(project_id, "lesson_blueprint.json", LessonBlueprint(lesson_title="Legacy only", slides=[]))

    state = storage.get_project_state(project_id)

    assert state.lesson_blueprint is not None
    assert storage.read_json(project_id, "presentation/presentation_blueprint.json") is None


def test_phase2b_adapter_output_is_not_only_schema_valid(tmp_path: Path, monkeypatch) -> None:
    listening = _run_fixture(tmp_path, monkeypatch, "listening_choice", "_usable")
    matching = _run_fixture(tmp_path, monkeypatch, "matching_response", "_usable")

    listen_payload = listening.adapted.slides[0].components[0].data
    match_payload = matching.adapted.slides[0].components[0].data
    assert listen_payload["audio_key"] in {asset.id for asset in listening.manifest.audio}
    assert listen_payload["answer"] in listen_payload["choices"]
    assert len(match_payload["pairs"]) >= 2
    assert all(pair["left"] and pair["right"] for pair in match_payload["pairs"])


def test_phase2b_supported_adapter_inputs_compile_with_existing_renderers(tmp_path: Path, monkeypatch) -> None:
    for mode, marker in (("listening_choice", "listen-choose"), ("matching_response", "match-game")):
        run = _run_fixture(tmp_path, monkeypatch, mode, "_renderer")
        html_path = render_lesson(run.root, LessonProfile(), run.adapted, run.manifest, QualityReport())
        deck = build_pptx_deck_plan(run.adapted)

        assert marker in html_path.read_text(encoding="utf-8")
        assert len(deck.slides) == len(run.adapted.slides)


def test_phase2b_shadow_planning_never_calls_or_imports_renderers() -> None:
    modules = [
        "presentation_blueprint", "presentation_content", "presentation_media_requests",
        "presentation_media_projection", "presentation_asset_reconciliation", "blueprint_compatibility",
    ]
    for name in modules:
        module = __import__(f"hcs_api.{name}", fromlist=[name])
        source = inspect.getsource(module)
        assert "render_lesson" not in source
        assert "pptx_export" not in source
        assert "LearningGoal(" not in source
        assert "EvidenceSpec(" not in source
        assert "LearningActivity(" not in source


def test_phase2b_canonical_artifacts_have_no_low_level_layout(tmp_path: Path, monkeypatch) -> None:
    forbidden = ("slide_id", "component_id", "layout_variant", "coordinate", "font", "color")
    for mode in ("guided_response", "listening_choice", "matching_response"):
        run = _run_fixture(tmp_path, monkeypatch, mode, "_layout")
        serialized = json.dumps(run.canonical.model_dump(mode="json"))
        assert all(term not in serialized for term in forbidden)
