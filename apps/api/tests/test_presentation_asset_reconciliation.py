"""Post-media reconciliation tests using the authoritative AssetManifest models."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import hcs_api.storage as storage
from hcs_api.models import (
    ActivityPlan,
    AssetFile,
    AssetManifest,
    AssetReference,
    EvidenceAlignmentReport,
    EvidencePlan,
    EvidenceSpec,
    LanguageItem,
    LearningActivity,
    LearningGoal,
    LearningStatePlan,
    LessonBlueprint,
)
from hcs_api.pipeline import run_full_pipeline
from hcs_api.presentation_asset_reconciliation import (
    RECONCILED_CONTENT_PLAN_PATH,
    RECONCILIATION_REPORT_PATH,
    reconcile_presentation_content_assets,
    run_post_media_presentation_reconciliation,
)
from hcs_api.presentation_blueprint import compile_shadow_presentation
from hcs_api.presentation_content import (
    CONTENT_PLAN_PATH,
    CONTENT_REPORT_PATH,
    attach_content_references,
    build_presentation_content_plan,
    content_item_is_complete,
)


def _language_items() -> list[LanguageItem]:
    return [
        LanguageItem(id="lang_nihao", target_form="你好", scaffold_meaning="hello", source_evidence="source"),
        LanguageItem(id="lang_ninhao", target_form="您好", scaffold_meaning="hello (polite)", source_evidence="source"),
    ]


def _content_plan(*, teacher_only: bool = False):
    goal = LearningGoal(id="goal_1", description="Choose 你好", skill_focus="recognition", target_language=["你好"])
    state = LearningStatePlan(lesson_title="你好", learning_goals=[goal])
    evidence = EvidenceSpec(
        id="ev_1",
        goal_id="goal_1",
        evidence_type="teacher_observation" if teacher_only else "listen_choose",
        collection_method="teacher_observation" if teacher_only else "learner_response",
        target_items=["你好"],
        acceptable_response={"accepted_values": ["你好"]},
    )
    activity = LearningActivity(
        id="act_1",
        evidence_ids=["ev_1"],
        activity_type="teacher_observation" if teacher_only else "listen_choose",
        learner_action="Choose the greeting." if not teacher_only else "",
        output_type="teacher_notes" if teacher_only else "selection",
        learner_facing=not teacher_only,
    )
    bindings, canonical, shadow = compile_shadow_presentation(
        state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), EvidenceAlignmentReport(),
    )
    assert canonical is not None
    plan, _ = build_presentation_content_plan(
        state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), bindings, canonical, _language_items(),
    )
    return state, bindings, attach_content_references(canonical, plan), shadow, plan


def _write_project(tmp_path: Path, monkeypatch, manifest: AssetManifest | None = None):
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "asset_reconciliation"
    root = storage.ensure_project(project_id)
    _state, bindings, canonical, shadow, plan = _content_plan()
    storage.write_json(project_id, "presentation/abstract_activity_bindings.json", bindings.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, "presentation/presentation_blueprint.json", canonical.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, "quality/presentation_shadow_report.json", shadow.model_dump(mode="json", by_alias=True))
    storage.write_json(project_id, CONTENT_PLAN_PATH, plan.model_dump(mode="json", by_alias=True))
    storage.write_model(project_id, "lesson_blueprint.json", LessonBlueprint(lesson_title="Production", slides=[]))
    if manifest is not None:
        storage.write_model(project_id, "asset_manifest.json", manifest)
    return project_id, root, plan


def _audio(asset_id: str = "audio_nihao", path: str = "assets/audio/nihao.wav", text: str = "你好") -> AssetFile:
    return AssetFile(id=asset_id, kind="audio", path=path, text=text)


def test_asset_reconciliation_report_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_project(tmp_path, monkeypatch, AssetManifest(audio=[_audio()]))

    run_post_media_presentation_reconciliation(project_id)

    payload = json.loads((root / RECONCILIATION_REPORT_PATH).read_text(encoding="utf-8"))
    assert payload["schema"] == "hanclassstudio.presentation_asset_reconciliation.v1"


def test_reconciled_content_plan_serializes_to_presentation_path(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_project(tmp_path, monkeypatch, AssetManifest(audio=[_audio()]))

    run_post_media_presentation_reconciliation(project_id)

    assert (root / RECONCILED_CONTENT_PLAN_PATH).exists()


def test_reconciler_runs_after_media_manifest_is_available(tmp_path: Path, monkeypatch) -> None:
    manifest = AssetManifest(audio=[_audio()])
    project_id, root, _ = _write_project(tmp_path, monkeypatch, manifest)

    report = run_post_media_presentation_reconciliation(project_id)

    assert (root / "assets/data/asset_manifest.json").exists()
    assert report.reconciled_audio_items == 1


def test_reconciler_does_not_read_lesson_blueprint() -> None:
    import hcs_api.presentation_asset_reconciliation as reconciliation

    assert "lesson_blueprint" not in inspect.getsource(reconciliation)


def test_reconciler_only_mutates_asset_reference_fields() -> None:
    *_, plan = _content_plan()
    before = plan.content_items[0].model_dump(mode="json")

    reconciled, report = reconcile_presentation_content_assets(plan, AssetManifest(audio=[_audio()]))

    after = reconciled.content_items[0].model_dump(mode="json")
    changed = {key for key in before if before[key] != after[key]}
    assert changed == {"audio_asset_refs"}
    assert report.mutated_non_asset_fields == []


def test_reconciler_does_not_change_presentation_mode() -> None:
    *_, plan = _content_plan()

    reconciled, _ = reconcile_presentation_content_assets(plan, AssetManifest(audio=[_audio()]))

    assert reconciled.content_items[0].presentation_mode == plan.content_items[0].presentation_mode


def test_reconciler_attaches_existing_traceable_audio() -> None:
    *_, plan = _content_plan()

    reconciled, report = reconcile_presentation_content_assets(plan, AssetManifest(audio=[_audio()]))

    assert report.state == "pass"
    assert reconciled.content_items[0].audio_asset_refs[0].asset_id == "audio_nihao"
    assert reconciled.content_items[0].audio_asset_refs[0].provenance[1] == "exact_approved_text"


def test_reconciler_rejects_missing_audio_asset() -> None:
    *_, plan = _content_plan()

    reconciled, report = reconcile_presentation_content_assets(plan, AssetManifest())

    assert report.state == "blocked"
    assert reconciled.content_items[0].audio_asset_refs == []


def test_reconciler_rejects_non_audio_asset() -> None:
    *_, plan = _content_plan()
    plan.content_items[0].audio_asset_refs = [AssetReference(asset_id="image_nihao", asset_type="audio", path_or_key="", availability="planned")]
    manifest = AssetManifest(images=[AssetFile(id="image_nihao", kind="image", path="assets/images/nihao.png", text="你好")])

    _, report = reconcile_presentation_content_assets(plan, manifest)

    assert report.state == "blocked"
    assert report.invalid_asset_findings


def test_reconciler_rejects_unready_asset() -> None:
    *_, plan = _content_plan()
    plan.content_items[0].audio_asset_refs = [AssetReference(asset_id="audio_nihao", asset_type="audio", path_or_key="", availability="planned")]

    _, report = reconcile_presentation_content_assets(plan, AssetManifest(audio=[_audio(path="")]))

    assert report.state == "blocked"
    assert report.invalid_asset_findings


def test_reconciler_reports_ambiguous_audio_candidates() -> None:
    *_, plan = _content_plan()

    _, report = reconcile_presentation_content_assets(plan, AssetManifest(audio=[_audio("audio_a"), _audio("audio_b")]))

    assert report.state == "blocked"
    assert report.ambiguous_audio_items


def test_reconciliation_is_deterministic() -> None:
    *_, plan = _content_plan()
    manifest = AssetManifest(audio=[_audio()])

    first, first_report = reconcile_presentation_content_assets(plan, manifest)
    second, second_report = reconcile_presentation_content_assets(plan, manifest)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first_report.model_dump(mode="json") == second_report.model_dump(mode="json")


def test_listening_choice_unblocks_when_valid_audio_exists() -> None:
    *_, plan = _content_plan()

    reconciled, _ = reconcile_presentation_content_assets(plan, AssetManifest(audio=[_audio()]))

    assert content_item_is_complete(reconciled.content_items[0]) is True


def test_listening_choice_remains_blocked_without_valid_audio() -> None:
    *_, plan = _content_plan()

    reconciled, _ = reconcile_presentation_content_assets(plan, AssetManifest())

    assert content_item_is_complete(reconciled.content_items[0]) is False


def test_teacher_only_asset_not_attached_to_learner_item() -> None:
    *_, plan = _content_plan(teacher_only=True)
    before = plan.model_dump(mode="json")

    reconciled, report = reconcile_presentation_content_assets(plan, AssetManifest(audio=[_audio()]))

    assert reconciled.model_dump(mode="json") == before
    assert report.assessed_audio_items == 0


def test_content_report_recomputed_after_reconciliation(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_project(tmp_path, monkeypatch, AssetManifest(audio=[_audio()]))

    run_post_media_presentation_reconciliation(project_id)

    payload = json.loads((root / CONTENT_REPORT_PATH).read_text(encoding="utf-8"))
    assert payload["state"] == "pass"


def test_adapter_assessment_recomputed_after_reconciliation(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_project(tmp_path, monkeypatch, AssetManifest(audio=[_audio()]))

    report = run_post_media_presentation_reconciliation(project_id)

    assessment = json.loads((root / "quality/presentation_adapter_assessment_report.json").read_text(encoding="utf-8"))
    assert assessment["exact_mappings_count"] == 1
    assert "quality/presentation_adapter_assessment_report.json" in report.recomputed_reports


def test_production_blueprint_and_renderers_remain_unchanged(tmp_path: Path, monkeypatch) -> None:
    project_id, root, _ = _write_project(tmp_path, monkeypatch, AssetManifest(audio=[_audio()]))
    production = root / "blueprints/lesson_blueprint.json"
    before = production.read_text(encoding="utf-8")

    run_post_media_presentation_reconciliation(project_id)

    assert production.read_text(encoding="utf-8") == before


def test_reconciliation_disabled_by_default() -> None:
    assert inspect.signature(run_full_pipeline).parameters["enable_presentation_asset_reconciliation_shadow"].default is False
