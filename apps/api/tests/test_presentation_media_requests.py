"""Shadow media request identity and request-to-asset linkage tests."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import hcs_api.storage as storage
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
    PresentationMediaRequest,
)
from hcs_api.pipeline import run_full_pipeline
from hcs_api.presentation_asset_reconciliation import reconcile_presentation_content_assets
from hcs_api.presentation_blueprint import compile_shadow_presentation
from hcs_api.presentation_content import build_presentation_content_plan
from hcs_api.presentation_media_requests import (
    ASSET_LINK_PLAN_PATH,
    REQUEST_PLAN_PATH,
    REQUEST_REPORT_PATH,
    build_presentation_media_request_plan,
    link_presentation_media_requests_to_assets,
    run_presentation_media_request_shadow,
)


def _content_plan(*, teacher_only: bool = False):
    goal = LearningGoal(id="goal_1", description="Listen to 你好", skill_focus="recognition", target_language=["你好"])
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
    bindings, canonical, _ = compile_shadow_presentation(
        state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), EvidenceAlignmentReport(),
    )
    assert canonical is not None
    language_items = [
        LanguageItem(id="lang_nihao", target_form="你好", scaffold_meaning="hello"),
        LanguageItem(id="lang_ninhao", target_form="您好", scaffold_meaning="hello (polite)"),
    ]
    plan, _ = build_presentation_content_plan(
        state, EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity]), bindings, canonical, language_items,
    )
    return plan


def _audio(asset_id: str = "audio_nihao", *, request_id: str | None = None, text: str = "你好") -> AssetFile:
    return AssetFile(id=asset_id, kind="audio", path=f"assets/audio/{asset_id}.wav", text=text, media_request_id=request_id)


def test_media_request_plan_serializes_to_presentation_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    storage.ensure_project("media_request")
    storage.write_json("media_request", "presentation/presentation_content_plan.json", _content_plan().model_dump(mode="json", by_alias=True))

    run_presentation_media_request_shadow("media_request")

    assert (tmp_path / "runtime" / "projects" / "media_request" / REQUEST_PLAN_PATH).exists()


def test_media_request_report_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    storage.ensure_project("media_request_report")
    storage.write_json("media_request_report", "presentation/presentation_content_plan.json", _content_plan().model_dump(mode="json", by_alias=True))

    run_presentation_media_request_shadow("media_request_report")

    payload = json.loads((tmp_path / "runtime" / "projects" / "media_request_report" / REQUEST_REPORT_PATH).read_text(encoding="utf-8"))
    assert payload["schema"] == "hanclassstudio.presentation_media_request_report.v1"


def test_media_request_ids_are_deterministic() -> None:
    first, _ = build_presentation_media_request_plan(_content_plan())
    second, _ = build_presentation_media_request_plan(_content_plan())

    assert first.requests[0].id == second.requests[0].id


def test_unrelated_content_does_not_change_existing_request_ids() -> None:
    plan = _content_plan()
    unrelated = plan.content_items[0].model_copy(update={"id": "content_unrelated", "presentation_mode": "guided_response"})
    changed = plan.model_copy(update={"content_items": [plan.content_items[0], unrelated]})

    baseline, _ = build_presentation_media_request_plan(plan)
    revised, _ = build_presentation_media_request_plan(changed)

    assert baseline.requests[0].id == revised.requests[0].id


def test_media_request_plan_does_not_read_lesson_blueprint() -> None:
    import hcs_api.presentation_media_requests as requests

    assert "lesson_blueprint" not in inspect.getsource(requests)


def test_media_request_models_reject_slide_component_layout_fields() -> None:
    plan, _ = build_presentation_media_request_plan(_content_plan())
    for forbidden in ("slide_id", "component_id", "layout_variant", "font", "color"):
        payload = plan.requests[0].model_dump(mode="json")
        payload[forbidden] = "forbidden"
        with pytest.raises(ValidationError):
            PresentationMediaRequest.model_validate(payload)


def test_listening_choice_creates_required_audio_request() -> None:
    plan, report = build_presentation_media_request_plan(_content_plan())

    assert report.state == "warning"
    assert plan.requests[0].media_type == "audio"
    assert plan.requests[0].required is True


def test_non_media_mode_does_not_create_unnecessary_request() -> None:
    plan = _content_plan()
    plan.content_items[0].presentation_mode = "guided_response"

    requests, _ = build_presentation_media_request_plan(plan)

    assert requests.requests == []


def test_teacher_only_content_does_not_create_learner_media_request() -> None:
    requests, report = build_presentation_media_request_plan(_content_plan(teacher_only=True))

    assert requests.requests == []
    assert report.requests_count == 0


def test_required_media_request_blocks_when_source_text_missing() -> None:
    plan = _content_plan()
    plan.content_items[0].accepted_responses = []
    plan.content_items[0].display_items = []

    _, report = build_presentation_media_request_plan(plan)

    assert report.state == "blocked"
    assert report.missing_source_findings


def test_duplicate_semantic_media_requests_are_rejected() -> None:
    plan = _content_plan()
    plan.content_items.append(plan.content_items[0].model_copy())

    _, report = build_presentation_media_request_plan(plan)

    assert report.state == "blocked"
    assert report.duplicate_requests


def test_existing_projects_deserialize_without_media_request_trace() -> None:
    manifest = AssetManifest.model_validate({"audio": [{"id": "audio_1", "kind": "audio", "path": "assets/audio/1.wav", "text": "你好"}]})

    assert manifest.audio[0].media_request_id is None


def test_asset_manifest_preserves_optional_media_request_id() -> None:
    manifest = AssetManifest(audio=[_audio(request_id="pmr_example")])

    assert AssetManifest.model_validate(manifest.model_dump(mode="json")).audio[0].media_request_id == "pmr_example"


def test_reconciliation_prefers_exact_media_request_id() -> None:
    content = _content_plan()
    requests, _ = build_presentation_media_request_plan(content)
    direct = _audio("audio_direct", request_id=requests.requests[0].id, text="unrelated")
    fallback = _audio("audio_text", text="你好")

    reconciled, report = reconcile_presentation_content_assets(content, AssetManifest(audio=[direct, fallback]), requests)

    assert report.state == "pass"
    assert reconciled.content_items[0].audio_asset_refs[0].asset_id == "audio_direct"


def test_reconciliation_rejects_wrong_media_type_for_request() -> None:
    content = _content_plan()
    requests, _ = build_presentation_media_request_plan(content)
    wrong = AssetFile(id="image_request", kind="image", path="assets/images/1.png", media_request_id=requests.requests[0].id)

    _, report = reconcile_presentation_content_assets(content, AssetManifest(images=[wrong]), requests)

    assert report.state == "blocked"
    assert report.invalid_asset_findings


def test_reconciliation_reports_duplicate_assets_for_request_id() -> None:
    content = _content_plan()
    requests, _ = build_presentation_media_request_plan(content)
    assets = AssetManifest(audio=[_audio("audio_1", request_id=requests.requests[0].id), _audio("audio_2", request_id=requests.requests[0].id)])

    _, report = reconcile_presentation_content_assets(content, assets, requests)

    assert report.state == "blocked"
    assert report.ambiguous_audio_items


def test_media_request_generation_is_disabled_by_default() -> None:
    assert inspect.signature(run_full_pipeline).parameters["enable_presentation_media_request_shadow"].default is False


def test_production_media_generation_semantics_remain_unchanged() -> None:
    import hcs_api.media as media

    assert "presentation_media_request" not in inspect.getsource(media)


def test_production_blueprint_renderers_and_exports_remain_unchanged() -> None:
    import hcs_api.presentation_media_requests as requests

    source = inspect.getsource(requests)
    assert "render_lesson" not in source
    assert "export_editable_pptx" not in source


def test_shadow_linkage_artifact_uses_existing_assets_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    root = storage.ensure_project("media_links")
    requests, _ = build_presentation_media_request_plan(_content_plan())
    storage.write_json("media_links", REQUEST_PLAN_PATH, requests.model_dump(mode="json", by_alias=True))
    storage.write_model("media_links", "asset_manifest.json", AssetManifest(audio=[_audio()]))

    from hcs_api.presentation_media_requests import run_presentation_media_asset_linkage
    links = run_presentation_media_asset_linkage("media_links")

    assert links is not None
    assert (root / ASSET_LINK_PLAN_PATH).exists()
    assert links.links[0].asset_id == "audio_nihao"
