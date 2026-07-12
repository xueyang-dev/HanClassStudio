from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from hcs_api.illustration_brief import compile_illustration_request
from hcs_api import storage
from hcs_api.models import (
    AssetFile, AssetManifest, IllustrationBrief, LessonBlueprint, LessonProfile,
    PresentationContentPlan, QualityReport,
)
from hcs_api.presentation_theme import (
    DEFAULT_THEME_ID, WARM_THEME_ID, persist_theme_decision,
    resolve_presentation_theme,
)
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
    Image.new("RGB", (160, 90), "#EFA37E").save(image_path)
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
    plan = json.loads((tmp_path / "presentation/presentation_content_plan.json").read_text())
    assert plan["presentation_theme_id"] == WARM_THEME_ID


def test_brief_html_and_svg_consume_one_theme(tmp_path: Path) -> None:
    decision = resolve_presentation_theme(tmp_path, selection={"decision_source": "teacher_selected", "theme_id": WARM_THEME_ID})
    persist_theme_decision(tmp_path, decision)
    request = compile_illustration_request(_brief(WARM_THEME_ID), "greeting")
    assert request.theme_id == WARM_THEME_ID
    assert "Presentation theme ppt_master_warm_classroom_v1@1" in request.scene_description
    svg = render_scene_spec({"concept": "喝水", "illustration_level": "scene", "setting": "neutral", "subjects": [], "objects": []}, presentation_theme=decision.theme)
    assert "#FCF8F3" in svg
    html = render_lesson(tmp_path, LessonProfile(lesson_title="问候"), LessonBlueprint(lesson_title="问候"), AssetManifest(), QualityReport())
    text = html.read_text(encoding="utf-8")
    assert "--bg: #FCF8F3" in text
    assert '"微软雅黑"' in text


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
    assert "#FCF8F3" in html.read_text(encoding="utf-8")
    report = storage.read_json("themed", "quality/pptx_quality_report.json")
    assert report["presentation_theme"]["theme_id"] == WARM_THEME_ID
