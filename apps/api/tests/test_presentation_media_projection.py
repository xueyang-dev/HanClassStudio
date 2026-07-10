"""Diagnostic-only projection tests against the real legacy media-plan shape."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import hcs_api.storage as storage
from hcs_api.models import (
    AcceptedResponse,
    AssetFile,
    AssetManifest,
    ChoiceOption,
    LessonBlueprint,
    LessonSlide,
    MediaRequirements,
    PresentationContentItem,
    PresentationContentPlan,
    PresentationMediaProjectionLinkPlan,
    PresentationMediaRequest,
    PresentationMediaRequestPlan,
    PresentationTrace,
    ProviderSettings,
)
from hcs_api.media import generate_configured_media, generate_placeholder_media
from hcs_api.pipeline import run_full_pipeline
from hcs_api.presentation_asset_reconciliation import reconcile_presentation_content_assets
from hcs_api.presentation_media_projection import (
    LEGACY_MEDIA_PLAN_PATH,
    PROJECTION_LINK_PLAN_PATH,
    PROJECTION_REPORT_PATH,
    REQUEST_PLAN_PATH,
    audit_presentation_media_projection,
    run_presentation_media_projection_audit,
)


def _request(*, required: bool = True, media_type: str = "audio", role: str = "listening_prompt") -> PresentationMediaRequest:
    return PresentationMediaRequest(
        id="pmr_hello", content_item_id="content_hello", presentation_unit_id="unit_hello", activity_id="activity_hello",
        evidence_ids=["evidence_hello"], media_type=media_type, media_role=role, source_text="你好",
        source_language_item_ids=["lang_hello"], required=required, expected_asset_type=media_type,
        trace=PresentationTrace(presentation_unit_id="unit_hello", binding_id="binding_hello", activity_id="activity_hello", evidence_ids=["evidence_hello"]),
    )


def _plan(request: PresentationMediaRequest | None = None) -> PresentationMediaRequestPlan:
    request = request or _request()
    return PresentationMediaRequestPlan(requests=[request], trace=[request.trace])


def _legacy(*audio: dict, images: list[dict] | None = None) -> dict:
    return {"schema": "hanclassstudio.media_plan.v1", "audio": list(audio), "images": images or [], "video": []}


def _audio(asset_id: str, text: str = "你好") -> AssetFile:
    return AssetFile(id=asset_id, kind="audio", path=f"assets/audio/{asset_id}.wav", text=text)


def _content_plan() -> PresentationContentPlan:
    trace = _request().trace
    item = PresentationContentItem(
        id="content_hello", presentation_unit_id="unit_hello", activity_id="activity_hello", evidence_ids=["evidence_hello"],
        presentation_mode="listening_choice", prompt="听一听", display_items=["你好"], language_items=["lang_hello"],
        options=[ChoiceOption(id="choice_1", text="你好", value="你好", is_accepted=True), ChoiceOption(id="choice_2", text="再见", value="再见")],
        accepted_responses=[AcceptedResponse(value="你好", normalized_value="你好", response_type="selection", acceptance_mode="exact")], trace=trace,
    )
    return PresentationContentPlan(lesson_title="你好", content_items=[item], trace=[trace])


def _media_blueprint() -> LessonBlueprint:
    return LessonBlueprint(lesson_title="你好", slides=[LessonSlide(
        id=1, slide_type="PracticeSlide", layout_variant="standard", title="你好",
        media_requirements=MediaRequirements(audio_key="legacy_audio", audio_text="你好", image_key="legacy_image", image_prompt="greeting"),
    )])


def test_media_projection_report_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    root = storage.ensure_project("projection")
    storage.write_json("projection", REQUEST_PLAN_PATH, _plan().model_dump(mode="json", by_alias=True))
    storage.write_json("projection", LEGACY_MEDIA_PLAN_PATH, _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好", "required": True}))

    run_presentation_media_projection_audit("projection")

    assert json.loads((root / PROJECTION_REPORT_PATH).read_text(encoding="utf-8"))["schema"] == "hanclassstudio.presentation_media_projection.v1"


def test_media_projection_links_serialize_to_presentation_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    root = storage.ensure_project("projection_links")
    storage.write_json("projection_links", REQUEST_PLAN_PATH, _plan().model_dump(mode="json", by_alias=True))
    storage.write_json("projection_links", LEGACY_MEDIA_PLAN_PATH, _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}))

    run_presentation_media_projection_audit("projection_links")

    assert PresentationMediaProjectionLinkPlan.model_validate_json((root / PROJECTION_LINK_PLAN_PATH).read_text(encoding="utf-8")).links[0].legacy_requirement_id == "legacy_audio"


def test_exact_projection_by_shared_request_id() -> None:
    report, links = audit_presentation_media_projection(_plan(), _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}))

    assert report.state == "pass"
    assert report.exact_matches_count == 1
    assert links.links[0].match_class == "exact"


def test_linkable_projection_by_stable_language_item_identity() -> None:
    report, links = audit_presentation_media_projection(_plan(), _legacy({"id": "lang_hello", "text": "你好"}))

    assert report.linkable_matches_count == 1
    assert links.links[0].matching_strategy == "language_item_identity"


def test_approximate_projection_not_used_as_authoritative_link() -> None:
    report, links = audit_presentation_media_projection(_plan(), _legacy({"id": "legacy_audio", "text": "你好"}))

    assert report.state == "warning"
    assert report.approximate_matches_count == 1
    assert links.links == []


def test_projection_rejects_media_type_mismatch() -> None:
    report, _ = audit_presentation_media_projection(_plan(_request(media_type="image")), _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}))

    assert report.state == "blocked"
    assert report.media_type_mismatches == ["pmr_hello"]


def test_projection_rejects_role_mismatch() -> None:
    report, _ = audit_presentation_media_projection(_plan(), _legacy({"id": "legacy_audio", "text": "你好", "media_role": "decorative_audio"}))

    assert report.state == "blocked"
    assert report.role_mismatches == ["pmr_hello"]


def test_projection_reports_ambiguous_candidates() -> None:
    report, _ = audit_presentation_media_projection(_plan(), _legacy({"id": "a", "language_item_ids": ["lang_hello"]}, {"id": "b", "language_item_ids": ["lang_hello"]}))

    assert report.state == "blocked"
    assert report.ambiguous_matches_count == 1


def test_required_unlinkable_shadow_request_blocks() -> None:
    report, _ = audit_presentation_media_projection(_plan(), _legacy())

    assert report.state == "blocked"
    assert report.findings[0].match_class == "unlinkable"


def test_optional_unlinkable_shadow_request_warns() -> None:
    report, _ = audit_presentation_media_projection(_plan(_request(required=False)), _legacy())

    assert report.state == "warning"
    assert report.findings[0].match_class == "shadow_only"


def test_legacy_only_requirement_is_reported() -> None:
    report, _ = audit_presentation_media_projection(_plan(), _legacy({"id": "lang_hello", "text": "你好"}, {"id": "legacy_extra", "text": "再见"}))

    assert report.legacy_only_requirements_count == 1
    assert any(finding.match_class == "legacy_only" for finding in report.findings)


def test_teacher_only_request_not_projected_to_learner_requirement() -> None:
    request = _request()
    request.generation_constraints = ["teacher_only"]
    report, links = audit_presentation_media_projection(_plan(request), _legacy({"id": "lang_hello", "text": "你好"}))

    assert report.state == "blocked"
    assert links.links == []


def test_projection_is_deterministic() -> None:
    plan = _plan()
    first = audit_presentation_media_projection(plan, _legacy({"id": "lang_hello", "text": "你好"}))
    second = audit_presentation_media_projection(plan, _legacy({"id": "lang_hello", "text": "你好"}))

    assert first[0].model_dump(mode="json") == second[0].model_dump(mode="json")


def test_projection_does_not_change_shadow_request_content() -> None:
    plan = _plan()
    before = plan.model_dump(mode="json")

    audit_presentation_media_projection(plan, _legacy({"id": "lang_hello", "text": "你好"}))

    assert plan.model_dump(mode="json") == before


def test_projection_does_not_treat_legacy_blueprint_as_pedagogical_authority() -> None:
    import hcs_api.presentation_media_projection as projection

    assert "lesson_blueprint" not in inspect.getsource(projection)


def test_projection_disabled_by_default() -> None:
    assert inspect.signature(run_full_pipeline).parameters["enable_presentation_media_projection_shadow"].default is False


def test_projection_does_not_change_provider_calls() -> None:
    import hcs_api.media as media

    assert "presentation_media_projection" not in inspect.getsource(media)


def test_production_assets_renderers_and_exports_remain_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    root = storage.ensure_project("production_unchanged")
    storage.write_json("production_unchanged", REQUEST_PLAN_PATH, _plan().model_dump(mode="json", by_alias=True))
    storage.write_json("production_unchanged", LEGACY_MEDIA_PLAN_PATH, _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}))
    storage.write_json("production_unchanged", "blueprints/lesson_blueprint.json", {"lesson_title": "production", "slides": []})
    storage.write_model("production_unchanged", "asset_manifest.json", AssetManifest(audio=[_audio("legacy_audio")]))
    before = {
        path: (root / path).read_text(encoding="utf-8")
        for path in ("blueprints/lesson_blueprint.json", LEGACY_MEDIA_PLAN_PATH, "assets/data/asset_manifest.json")
    }

    run_presentation_media_projection_audit("production_unchanged")

    assert {path: (root / path).read_text(encoding="utf-8") for path in before} == before


def test_exact_projection_can_improve_shadow_asset_linkage() -> None:
    content = _content_plan()
    requests = _plan()
    _, links = audit_presentation_media_projection(requests, _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}))

    reconciled, report = reconcile_presentation_content_assets(content, AssetManifest(audio=[_audio("legacy_audio", text="unrelated")]), requests, None, links)

    assert report.state == "pass"
    assert reconciled.content_items[0].audio_asset_refs[0].asset_id == "legacy_audio"


def test_approximate_projection_cannot_unblock_reconciliation() -> None:
    content = _content_plan()
    requests = _plan()
    _, links = audit_presentation_media_projection(requests, _legacy({"id": "legacy_audio", "text": "你好"}))

    _, report = reconcile_presentation_content_assets(content, AssetManifest(audio=[_audio("legacy_audio", text="unrelated")]), requests, None, links)

    assert links.links == []
    assert report.state == "blocked"


def test_asset_origin_trace_survives_manifest_serialization() -> None:
    manifest = AssetManifest(audio=[AssetFile(id="asset", kind="audio", path="assets/audio/a.wav", origin_media_requirement_ids=["legacy_audio"])])

    restored = AssetManifest.model_validate(manifest.model_dump(mode="json"))

    assert restored.audio[0].origin_media_requirement_ids == ["legacy_audio"]


def test_existing_manifest_without_origin_trace_deserializes() -> None:
    manifest = AssetManifest.model_validate({"audio": [{"id": "asset", "kind": "audio", "path": "assets/audio/a.wav"}]})

    assert manifest.audio[0].origin_media_requirement_ids == []


def test_generated_asset_preserves_legacy_requirement_identity(tmp_path: Path) -> None:
    manifest = generate_placeholder_media(tmp_path, _media_blueprint(), preserve_media_origin_trace=True)

    assert manifest.audio[0].origin_media_requirement_ids == ["legacy_audio"]
    assert manifest.images[0].origin_media_requirement_ids == ["legacy_image"]


def test_origin_trace_generation_is_opt_in(tmp_path: Path) -> None:
    manifest = generate_placeholder_media(tmp_path, _media_blueprint())

    assert manifest.audio[0].origin_media_requirement_ids == []


def test_provider_call_payload_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    import hcs_api.media as media

    captured: list[str] = []
    monkeypatch.setattr(media, "generate_openai_tts", lambda _settings, text: captured.append(text) or b"audio")
    settings = ProviderSettings()
    settings.audio.provider = "test"

    manifest = generate_configured_media(tmp_path, _media_blueprint(), settings, preserve_media_origin_trace=True)

    assert captured == ["你好"]
    assert manifest.audio[0].origin_media_requirement_ids == ["legacy_audio"]


def test_asset_content_and_path_are_unchanged(tmp_path: Path) -> None:
    manifest = generate_placeholder_media(tmp_path, _media_blueprint(), preserve_media_origin_trace=True)

    assert manifest.audio[0].id == "legacy_audio"
    assert manifest.audio[0].path == "assets/audio/legacy_audio.wav"
    assert (tmp_path / manifest.audio[0].path).exists()


def test_origin_trace_is_deterministic(tmp_path: Path) -> None:
    first = generate_placeholder_media(tmp_path / "one", _media_blueprint(), preserve_media_origin_trace=True)
    second = generate_placeholder_media(tmp_path / "two", _media_blueprint(), preserve_media_origin_trace=True)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_cached_asset_origin_is_preserved_when_explicit() -> None:
    cached = AssetFile(id="cache_asset", kind="audio", path="assets/audio/cached.wav", origin_media_requirement_ids=["legacy_audio"])

    assert AssetFile.model_validate(cached.model_dump(mode="json")).origin_media_requirement_ids == ["legacy_audio"]


def test_cached_asset_origin_is_not_guessed_from_filename() -> None:
    manifest = AssetManifest(audio=[AssetFile(id="cache_asset", kind="audio", path="assets/audio/legacy_audio.wav")])
    report, _ = audit_presentation_media_projection(_plan(), _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}), manifest)

    assert report.asset_origin_trace_mode == "unresolved_origin"
    assert report.projection_chain_complete is False


def test_multiple_assets_can_share_one_requirement_origin() -> None:
    manifest = AssetManifest(audio=[
        AssetFile(id="audio_a", kind="audio", path="assets/audio/a.wav", origin_media_requirement_ids=["legacy_audio"]),
        AssetFile(id="audio_b", kind="audio", path="assets/audio/b.wav", origin_media_requirement_ids=["legacy_audio"]),
    ])
    report, _ = audit_presentation_media_projection(_plan(), _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}), manifest)

    assert report.origin_trace_coverage == 1.0
    assert report.ambiguous_origin_findings == []


def test_conflicting_multiple_origins_are_reported() -> None:
    manifest = AssetManifest(audio=[AssetFile(
        id="asset", kind="audio", path="assets/audio/a.wav", origin_media_requirement_ids=["legacy_audio", "legacy_image"],
    )])
    report, _ = audit_presentation_media_projection(
        _plan(), _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}, images=[{"id": "legacy_image", "prompt": "greeting"}]), manifest,
    )

    assert report.state == "blocked"
    assert report.ambiguous_origin_findings


def test_exact_projection_reaches_asset_through_origin_trace() -> None:
    manifest = AssetManifest(audio=[AssetFile(id="cached_audio", kind="audio", path="assets/audio/cached.wav", origin_media_requirement_ids=["legacy_audio"])])
    requests = _plan()
    report, links = audit_presentation_media_projection(requests, _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}), manifest)
    reconciled, reconciliation = reconcile_presentation_content_assets(_content_plan(), manifest, requests, None, links)

    assert report.projection_chain_complete is True
    assert report.asset_origin_trace_mode == "explicit_origin_metadata"
    assert reconciliation.state == "pass"
    assert reconciled.content_items[0].audio_asset_refs[0].asset_id == "cached_audio"


def test_linkable_projection_reaches_asset_through_origin_trace() -> None:
    manifest = AssetManifest(audio=[AssetFile(id="cached_audio", kind="audio", path="assets/audio/cached.wav", origin_media_requirement_ids=["lang_hello"])])
    report, _ = audit_presentation_media_projection(_plan(), _legacy({"id": "lang_hello", "text": "你好"}), manifest)

    assert report.linkable_matches_count == 1
    assert report.projection_chain_complete is True


def test_approximate_projection_cannot_attach_media_request_id() -> None:
    asset = AssetFile(id="cached_audio", kind="audio", path="assets/audio/cached.wav", origin_media_requirement_ids=["legacy_audio"])
    _report, links = audit_presentation_media_projection(_plan(), _legacy({"id": "legacy_audio", "text": "你好"}), AssetManifest(audio=[asset]))

    assert links.links == []
    assert asset.media_request_id is None


def test_projection_report_records_origin_trace_coverage() -> None:
    manifest = AssetManifest(audio=[
        AssetFile(id="traced", kind="audio", path="assets/audio/traced.wav", origin_media_requirement_ids=["legacy_audio"]),
        AssetFile(id="legacy_extra", kind="audio", path="assets/audio/extra.wav"),
    ])
    report, _ = audit_presentation_media_projection(_plan(), _legacy(
        {"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}, {"id": "legacy_extra", "text": "再见"},
    ), manifest)

    assert report.origin_trace_coverage == 0.5
    assert report.assets_without_origin_trace == ["legacy_extra"]


def test_reconciliation_prefers_explicit_request_id_then_origin_trace() -> None:
    content = _content_plan()
    requests = _plan()
    _report, links = audit_presentation_media_projection(requests, _legacy({"id": "legacy_audio", "media_request_id": "pmr_hello", "text": "你好"}))
    direct = AssetFile(id="direct", kind="audio", path="assets/audio/direct.wav", media_request_id="pmr_hello")
    origin = AssetFile(id="origin", kind="audio", path="assets/audio/origin.wav", origin_media_requirement_ids=["legacy_audio"])

    reconciled, report = reconcile_presentation_content_assets(content, AssetManifest(audio=[direct, origin]), requests, None, links)

    assert report.state == "pass"
    assert reconciled.content_items[0].audio_asset_refs[0].asset_id == "direct"


def test_old_projects_and_manifests_remain_compatible() -> None:
    assert AssetManifest.model_validate({"images": [], "audio": []}).model_dump(mode="json")["audio"] == []


def test_production_blueprint_renderer_export_behavior_is_unchanged() -> None:
    import hcs_api.renderer as renderer
    import hcs_api.pptx_exporter as pptx_exporter

    assert "origin_media_requirement_ids" not in inspect.getsource(renderer)
    assert "origin_media_requirement_ids" not in inspect.getsource(pptx_exporter)
