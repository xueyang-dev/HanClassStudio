from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import hcs_api.main as main
from hcs_api.illustration_brief import compile_illustration_request
from hcs_api import storage
from hcs_api.main import app
from hcs_api.media import generate_configured_media
from hcs_api.models import (
    AssetFile, AssetManifest, IllustrationBrief, LessonBlueprint, LessonProfile,
    LessonSlide, MediaRequirements, PresentationContentPlan, ProviderSettings,
    QualityReport, VideoGenerationRequestPlan,
)
from hcs_api.presentation_theme import (
    DEFAULT_THEME_ID, THEME_SELECTION_PATH, WARM_THEME_ID,
    persist_theme_decision, persist_visual_theme_selection,
    recommend_visual_theme, resolve_presentation_theme, theme_by_id,
    video_generation_requests, visual_theme_catalog,
    presentation_theme_for_project, visual_theme_selection_for_project,
    visual_theme_state_for_project,
)
from hcs_api.providers import provider_capability_catalog
from hcs_api.renderer import render_lesson
from hcs_api.svg_components import render_scene_spec
from hcs_api.pptx_exporter import export_editable_pptx


def _brief(theme_id: str) -> IllustrationBrief:
    return IllustrationBrief(
        concept="老师好", scene_purpose="primary teaching scenario", learner_age_range="8-14",
        learner_language_level="zero beginner", visual_subject="student and teacher",
        action="a student greets a teacher", environment="classroom", number_of_people=2,
        presentation_theme_id=theme_id, presentation_theme_version="1",
    )


def test_theme_serialization_is_versioned_and_provider_neutral() -> None:
    decision = resolve_presentation_theme(Path("."), selection={"decision_source": "ppt_master_auto"})
    restored = type(decision).model_validate(decision.model_dump(mode="json"))
    assert restored.theme.theme_id == DEFAULT_THEME_ID
    assert restored.theme.version == "1"
    for forbidden in ("provider", "model", "api_key", "endpoint_url"):
        assert forbidden not in type(restored.theme).model_fields


def test_registry_contains_exactly_five_versioned_presets() -> None:
    catalog = visual_theme_catalog()
    assert [preset.theme_id for preset in catalog.presets] == [
        "classroom-clear", "active-learning", "warm-story", "eastern-elegance", "future-exploration",
    ]
    assert catalog.theme_version == "1"
    assert all(preset.version == "1" for preset in catalog.presets)
    assert all(preset.preview.background.startswith("#") for preset in catalog.presets)
    assert "auto" not in {preset.theme_id for preset in catalog.presets}


def test_auto_recommendation_is_deterministic_and_falls_back_to_classroom_clear() -> None:
    assert recommend_visual_theme() == ("classroom-clear", "default_clear")
    assert recommend_visual_theme(LessonProfile(subject="能源工程"))[0] == "future-exploration"
    assert recommend_visual_theme(LessonProfile(lesson_type="中国节日文化"))[0] == "eastern-elegance"
    assert recommend_visual_theme(LessonProfile(target_students="儿童", lesson_type="游戏练习"))[0] == "active-learning"
    assert recommend_visual_theme(LessonProfile(lesson_type="生活情景对话"))[0] == "warm-story"


def test_teacher_selected_theme_falls_back_from_unknown_font(tmp_path: Path) -> None:
    decision = resolve_presentation_theme(tmp_path, selection={
        "decision_source": "teacher_selected", "theme_id": WARM_THEME_ID,
        "overrides": {"typography": {"chinese_font": "Missing Test Font"}},
    })
    assert decision.theme.theme_id == WARM_THEME_ID
    assert decision.theme.typography.chinese_font == "微软雅黑"
    assert any("Unavailable font" in item for item in decision.rationale)


def test_existing_warm_images_select_master_warm_variant_and_propagate(tmp_path: Path) -> None:
    image_path = tmp_path / "assets/images/scene.png"
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGB", (160, 90), "#EFA37E")
    image.putpixel((0, 0), (255, 255, 255))
    image.save(image_path)
    manifest = AssetManifest(images=[AssetFile(
        id="scene", kind="image", path="assets/images/scene.png", content_hash="abc",
    )])
    (tmp_path / "presentation").mkdir()
    (tmp_path / "presentation/presentation_content_plan.json").write_text(
        PresentationContentPlan(lesson_title="问候").model_dump_json(by_alias=True), encoding="utf-8",
    )
    decision = resolve_presentation_theme(
        tmp_path, manifest=manifest, selection={"decision_source": "inherited_from_existing_assets"},
    )
    persist_theme_decision(tmp_path, decision, manifest)
    assert decision.theme.theme_id == WARM_THEME_ID
    assert manifest.presentation_theme_id == WARM_THEME_ID
    assert manifest.images[0].presentation_theme_id == WARM_THEME_ID
    assert all(len(color) == 7 for color in decision.asset_observations["dominant_colors"])
    plan = json.loads((tmp_path / "presentation/presentation_content_plan.json").read_text())
    assert plan["presentation_theme_id"] == WARM_THEME_ID


def test_brief_html_and_svg_consume_one_theme(tmp_path: Path) -> None:
    decision = resolve_presentation_theme(tmp_path, selection={"decision_source": "teacher_selected", "theme_id": WARM_THEME_ID})
    persist_theme_decision(tmp_path, decision)
    request = compile_illustration_request(_brief(WARM_THEME_ID), "greeting")
    assert request.theme_id == WARM_THEME_ID
    assert "Presentation theme warm-story@1" in request.scene_description
    svg = render_scene_spec({"concept": "喝水", "illustration_level": "scene", "setting": "neutral", "subjects": [], "objects": []}, presentation_theme=decision.theme)
    assert "#FCF7F0" in svg
    html = render_lesson(tmp_path, LessonProfile(lesson_title="问候"), LessonBlueprint(lesson_title="问候"), AssetManifest(), QualityReport())
    text = html.read_text(encoding="utf-8")
    assert "--bg: #FCF7F0" in text
    assert '"微软雅黑"' in text


def test_selection_persists_and_reload_restores_manual_mode(tmp_path: Path) -> None:
    selection = persist_visual_theme_selection(
        tmp_path, mode="manual", selected_theme_id="active-learning",
        profile=LessonProfile(lesson_title="问候"),
    )
    assert selection.selected_theme_id == "active-learning"
    assert (tmp_path / THEME_SELECTION_PATH).is_file()
    restored = visual_theme_selection_for_project(tmp_path, profile=LessonProfile(lesson_title="问候"))
    assert restored.mode == "manual"
    assert restored.selected_theme_id == "active-learning"
    assert resolve_presentation_theme(tmp_path).theme.theme_id == "active-learning"


def test_legacy_theme_files_remain_readable_without_freezing_old_auto_choice(tmp_path: Path) -> None:
    inherited_root = tmp_path / "inherited"
    image_path = inherited_root / "assets/images/scene.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (80, 45), "#EFA37E").save(image_path)
    data_dir = inherited_root / "assets/data"
    data_dir.mkdir(parents=True)
    (data_dir / "asset_manifest.json").write_text(AssetManifest(images=[AssetFile(
        id="scene", kind="image", path="assets/images/scene.png",
    )]).model_dump_json(by_alias=True), encoding="utf-8")
    selection_path = inherited_root / THEME_SELECTION_PATH
    selection_path.parent.mkdir(parents=True)
    selection_path.write_text(json.dumps({
        "decision_source": "inherited_from_existing_assets",
    }), encoding="utf-8")
    inherited = visual_theme_selection_for_project(inherited_root)
    assert inherited.mode == "manual"
    assert inherited.selected_theme_id == "warm-story"

    auto_root = tmp_path / "auto"
    auto_data = auto_root / "assets/data"
    auto_data.mkdir(parents=True)
    (auto_data / "lesson_profile.json").write_text(
        LessonProfile(subject="能源工程").model_dump_json(by_alias=True), encoding="utf-8",
    )
    old_theme = theme_by_id("classroom-clear").model_dump(mode="json")
    old_theme["theme_id"] = "ppt_master_blue_classroom_v1"
    old_theme.pop("video_treatment")
    decision_path = auto_root / "presentation/presentation_theme.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text(json.dumps({
        "schema": "hanclassstudio.presentation_theme.v1",
        "decision_source": "ppt_master_auto",
        "theme": old_theme,
    }), encoding="utf-8")
    assert visual_theme_selection_for_project(auto_root).selected_theme_id == "future-exploration"
    assert presentation_theme_for_project(auto_root).theme_id == "future-exploration"


def test_theme_switch_keeps_old_media_provenance_and_exposes_backend_action(tmp_path: Path) -> None:
    settings = ProviderSettings()
    old = AssetFile(
        id="scene", kind="image", path="assets/images/scene.svg",
        presentation_theme_id="classroom-clear", presentation_theme_version="1",
    )
    manifest = AssetManifest(images=[old])
    persist_visual_theme_selection(tmp_path, mode="manual", selected_theme_id="warm-story")
    state = visual_theme_state_for_project(
        tmp_path,
        manifest=manifest,
        provider_catalog=provider_capability_catalog(settings),
        provider_settings=settings,
    )
    assert old.presentation_theme_id == "classroom-clear"
    assert state.media_state == "mixed"
    assert state.mismatched_media_ids == ["scene"]
    assert state.regeneration_available is True


def test_manual_theme_persistence_does_not_relabel_unknown_historical_media(tmp_path: Path) -> None:
    old = AssetFile(id="legacy", kind="image", path="assets/images/legacy.svg")
    manifest = AssetManifest(images=[old])
    decision = resolve_presentation_theme(
        tmp_path,
        selection={"mode": "manual", "selected_theme_id": "warm-story"},
    )

    persist_theme_decision(tmp_path, decision, manifest)

    assert manifest.presentation_theme_id == "warm-story"
    assert old.presentation_theme_id is None
    assert old.presentation_theme_version is None
    state = visual_theme_state_for_project(
        tmp_path,
        manifest=manifest,
        provider_catalog=provider_capability_catalog(ProviderSettings()),
        provider_settings=ProviderSettings(),
    )
    assert state.media_state == "mixed"
    assert state.mismatched_media_ids == ["legacy"]


def test_video_request_retains_theme_and_reports_unsupported_provider() -> None:
    settings = ProviderSettings()
    state = visual_theme_state_for_project(
        Path("."), provider_catalog=provider_capability_catalog(settings), provider_settings=settings,
    )
    video_support = next(item for item in state.provider_support if item.capability == "video")
    blueprint = LessonBlueprint(slides=[LessonSlide(
        id=1, slide_type="video", layout_variant="media",
        title="场景", media_requirements=MediaRequirements(video_key="scene-video", video_scene_prompt="A greeting scene"),
    )])
    requests = video_generation_requests(blueprint, theme_by_id("eastern-elegance"), video_support)
    assert requests[0].theme_id == "eastern-elegance"
    assert requests[0].theme_direction.color_grade
    assert requests[0].theme_application_state == "unsupported"
    assert requests[0].theme_application_reason


def test_media_pipeline_persists_video_theme_request_without_fake_asset(tmp_path: Path) -> None:
    persist_visual_theme_selection(tmp_path, mode="manual", selected_theme_id="future-exploration")
    blueprint = LessonBlueprint(slides=[LessonSlide(
        id=1, slide_type="video", layout_variant="media",
        title="能源", media_requirements=MediaRequirements(video_key="energy-video", video_scene_prompt="A safe energy lab"),
    )])
    manifest = generate_configured_media(tmp_path, blueprint, ProviderSettings())
    assert manifest.video == []
    payload = VideoGenerationRequestPlan.model_validate_json(
        (tmp_path / "assets/data/video_generation_requests.json").read_text(encoding="utf-8")
    )
    assert payload.requests[0].theme_id == "future-exploration"
    assert payload.requests[0].theme_application_state == "unsupported"


def test_media_pipeline_tags_only_new_placeholder_with_current_theme(tmp_path: Path) -> None:
    persist_visual_theme_selection(tmp_path, mode="manual", selected_theme_id="active-learning")
    blueprint = LessonBlueprint(slides=[LessonSlide(
        id=1,
        slide_type="scene",
        layout_variant="media",
        title="练习",
        media_requirements=MediaRequirements(
            image_key="activity-scene",
            image_prompt="Two adult learners practise a greeting",
        ),
    )])

    manifest = generate_configured_media(tmp_path, blueprint, ProviderSettings())

    assert manifest.images[0].presentation_theme_id == "active-learning"
    assert manifest.images[0].presentation_theme_version == "1"


def test_pptx_and_html_report_the_same_persisted_theme(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    root = storage.ensure_project("themed")
    decision = resolve_presentation_theme(root, selection={"decision_source": "teacher_selected", "theme_id": WARM_THEME_ID})
    persist_theme_decision(root, decision)
    blueprint = LessonBlueprint(lesson_title="问候")
    storage.write_model("themed", "lesson_blueprint.json", blueprint)
    storage.write_model("themed", "lesson_profile.json", LessonProfile(lesson_title="问候"))
    storage.write_model("themed", "asset_manifest.json", AssetManifest())
    storage.write_model("themed", "quality_report.json", QualityReport(state="pass"))
    html = render_lesson(root, LessonProfile(lesson_title="问候"), blueprint, AssetManifest(), QualityReport())
    pptx = export_editable_pptx("themed")
    assert pptx.is_file()
    assert "#FCF7F0" in html.read_text(encoding="utf-8")
    report = storage.read_json("themed", "quality/pptx_quality_report.json")
    assert report["presentation_theme"]["theme_id"] == WARM_THEME_ID


def test_visual_theme_api_persists_without_relabeling_or_regenerating_media(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(storage, "PROJECTS_DIR", runtime / "projects")
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime / "config/provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", runtime / "projects")
    root = storage.ensure_project("theme-api")
    storage.write_model("theme-api", "lesson_profile.json", LessonProfile(lesson_title="问候"))
    storage.write_model("theme-api", "lesson_blueprint.json", LessonBlueprint(lesson_title="问候"))
    storage.write_model("theme-api", "asset_manifest.json", AssetManifest(images=[AssetFile(
        id="existing", kind="image", path="assets/images/existing.png",
        presentation_theme_id="classroom-clear", presentation_theme_version="1",
    )]))
    (root / "courseware/lesson.html").write_text("<!doctype html><title>old render</title>", encoding="utf-8")
    storage.bump_project_revision("theme-api")
    client = TestClient(app)

    catalog = client.get("/api/visual-themes")
    assert catalog.status_code == 200
    assert len(catalog.json()["presets"]) == 5
    revision = storage.project_revision("theme-api")
    response = client.put(
        f"/api/projects/theme-api/visual-theme?expected_revision={revision}",
        json={"mode": "manual", "selected_theme_id": "active-learning"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["visual_theme"]["selection"]["selected_theme_id"] == "active-learning"
    assert body["visual_theme"]["mismatched_media_ids"] == ["existing"]
    assert body["visual_theme"]["regeneration_available"] is True
    presentation = next(stage for stage in body["stages"] if stage["stage_id"] == "presentation")
    assert "regenerate_media_for_theme" in presentation["available_actions"]
    assert set(body["stale_state"]["stale_stages"]) >= {"render", "quality", "delivery"}
    stored_manifest = storage.read_model("theme-api", "asset_manifest.json", AssetManifest)
    assert stored_manifest is not None
    assert stored_manifest.images[0].presentation_theme_id == "classroom-clear"
    assert not (root / "assets/images/active-learning.png").exists()

    reloaded = client.get("/api/projects/theme-api").json()
    assert reloaded["visual_theme"]["selection"]["selected_theme_id"] == "active-learning"

    def unreadable_provider_settings() -> ProviderSettings:
        raise ValueError("simulated corrupt optional provider settings")

    monkeypatch.setattr(storage, "read_provider_settings", unreadable_provider_settings)
    recovered = storage.get_project_state("theme-api")
    assert recovered.visual_theme is not None
    assert recovered.visual_theme.selection.selected_theme_id == "active-learning"
