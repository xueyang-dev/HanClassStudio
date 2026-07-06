from __future__ import annotations

import json
import zipfile
from pathlib import Path

from pptx import Presentation

import hcs_api.quality as quality_module
import hcs_api.renderer as renderer_module
from hcs_api.agents import build_blueprint, infer_profile
from hcs_api.components import load_component_registry
from hcs_api.media import generate_placeholder_media
from hcs_api.models import (
    AssetManifest,
    AudioProviderSettings,
    ContentBlock,
    ImageProviderSettings,
    LessonBlueprint,
    LessonProfile,
    LessonSlide,
    LLMProviderSettings,
    ProviderSettings,
    QualityReport,
    SlideComponent,
)
from hcs_api.parser import parse_pptx
from hcs_api.pipeline import (
    generate_lesson_blueprint,
    generate_project_media,
    render_and_check,
    write_blueprint_artifacts,
    write_spec_artifacts,
)
from hcs_api.quality import check_quality
from hcs_api.renderer import render_lesson
from hcs_api.storage import ensure_project, write_json, write_model, zip_output


def test_pptx_to_offline_zip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("hcs_api.storage.RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr("hcs_api.storage.PROJECTS_DIR", tmp_path / "runtime" / "projects")
    pptx_path = tmp_path / "lesson.pptx"
    _make_pptx(pptx_path)

    project_id = "testproject"
    project_root = ensure_project(project_id)
    source = parse_pptx(pptx_path, project_root, "lesson.pptx")
    profile = infer_profile(source)
    blueprint = build_blueprint(source, profile)
    write_model(project_id, "source_material.json", source)
    write_model(project_id, "lesson_profile.json", profile)
    write_spec_artifacts(project_id, source, profile)
    write_blueprint_artifacts(project_id, blueprint)
    manifest = generate_placeholder_media(project_root, blueprint)
    write_model(project_id, "asset_manifest.json", manifest)
    write_json(project_id, "assets/data/attribution.json", {"schema": "hanclassstudio.attribution.v1", "items": []})
    report = render_and_check(project_id, project_root, profile, blueprint, manifest)
    html_path = project_root / "courseware" / "lesson.html"
    zip_path = zip_output(project_id)

    assert source.pages[0].title == "第14课 我在学习中文呢"
    assert blueprint.slides
    assert manifest.audio
    assert report.state == "warning"
    assert html_path.exists()
    html = html_path.read_text(encoding="utf-8")
    assert 'class="slide-frame"' in html
    assert "player-nav" in html
    assert 'data-mode="bilingual"' in html
    assert "component-container" in html
    assert "https://" not in html
    assert "http://" not in html
    assert (project_root / "sources" / "source_material.json").exists()
    assert (project_root / "specs" / "lesson_spec.md").exists()
    assert (project_root / "specs" / "spec_lock.json").exists()
    assert (project_root / "blueprints" / "interaction_plan.json").exists()
    assert (project_root / "blueprints" / "media_plan.json").exists()
    assert (project_root / "quality" / "quality_report.json").exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        export_manifest = json.loads(zf.read("export_manifest.json"))
    assert "lesson.html" in names
    assert "assets/data/lesson_profile.json" in names
    assert "assets/data/source_material.json" in names
    assert "assets/data/lesson_blueprint.json" in names
    assert "assets/data/interaction_plan.json" in names
    assert "assets/data/media_plan.json" in names
    assert "assets/data/asset_manifest.json" in names
    assert "assets/data/quality_report.json" in names
    assert "assets/data/attribution.json" in names
    assert "quality_summary.md" in names
    assert any(name.startswith("assets/images/") for name in names)
    assert any(name.startswith("assets/audio/") for name in names)
    assert export_manifest["forced"] is False


def test_quality_gate_states_targeted_fixtures(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("hcs_api.storage.RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr("hcs_api.storage.PROJECTS_DIR", tmp_path / "runtime" / "projects")
    profile = LessonProfile(lesson_title="测试课")

    pass_root = ensure_project("passproject")
    pass_blueprint = _minimal_blueprint()
    render_lesson(pass_root, profile, pass_blueprint, AssetManifest(), QualityReport())
    pass_report = check_quality(pass_root, pass_blueprint, AssetManifest())
    assert pass_report.state == "pass"

    warning_root = ensure_project("warningproject")
    warning_blueprint = _minimal_blueprint(slide_title="")
    render_lesson(warning_root, profile, warning_blueprint, AssetManifest(), QualityReport())
    warning_report = check_quality(warning_root, warning_blueprint, AssetManifest())
    assert warning_report.state == "warning"
    assert warning_report.warnings

    blocked_root = ensure_project("blockedproject")
    blocked_blueprint = _minimal_blueprint(
        components=[
            SlideComponent(
                id="listen_bad",
                component_type="ListenAndChoose",
                title="听音选择",
                data={"choices": ["A", "B"], "answer": "C"},
            )
        ]
    )
    render_lesson(blocked_root, profile, blocked_blueprint, AssetManifest(), QualityReport())
    blocked_report = check_quality(blocked_root, blocked_blueprint, AssetManifest())
    assert blocked_report.state == "blocked"
    assert any("答案不在选项中" in item for item in blocked_report.blocking)


def test_component_registry_matches_frontend_renderer_and_quality() -> None:
    registry = load_component_registry()
    frontend_source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")
    renderer_source = Path(renderer_module.__file__).read_text(encoding="utf-8")
    quality_source = Path(quality_module.__file__).read_text(encoding="utf-8")

    assert "const componentTypes" not in frontend_source
    assert "getComponentRegistry" in frontend_source
    for component_name, config in registry.items():
        if config.get("experimental"):
            continue
        assert f'component.component_type == "{component_name}"' in renderer_source
        assert f'component.component_type == "{component_name}"' in quality_source


def test_runtime_html_is_slide_based_and_local_only(tmp_path: Path) -> None:
    profile = LessonProfile(lesson_title="互动演示课")
    blueprint = LessonBlueprint(
        lesson_title="互动演示课",
        objectives=["完成互动练习"],
        key_vocabulary=[{"word": "学", "pinyin": "xue2", "meaning": "study"}],
        grammar_points=["在...呢"],
        slides=[
            LessonSlide(
                id=1,
                slide_type="InteractiveSlide",
                layout_variant="demo",
                title="互动练习",
                content_blocks=[
                    ContentBlock(id="intro", text="我在学习中文呢。", scaffolding_text="I am studying Chinese now.")
                ],
                components=[
                    SlideComponent(
                        id="audio_demo",
                        component_type="AudioButton",
                        title="听句子",
                        data={"audio_key": "missing_audio", "audio_text": "我在学习中文呢。", "label": "播放句子"},
                    ),
                    SlideComponent(
                        id="vocab_demo",
                        component_type="VocabularyFlipCard",
                        title="生词卡",
                        data={"items": [{"word": "学", "pinyin": "xue2", "meaning": "study", "example": "我学习中文。"}]},
                    ),
                    SlideComponent(
                        id="sentence_demo",
                        component_type="SentenceDragBuilder",
                        title="组句",
                        data={"words": ["我", "在", "学习", "中文", "呢"], "answer": ["我", "在", "学习", "中文", "呢"]},
                    ),
                    SlideComponent(
                        id="listen_demo",
                        component_type="ListenAndChoose",
                        title="听选",
                        data={"audio_key": "missing_audio", "choices": ["我在学习中文呢。", "你好"], "answer": "我在学习中文呢。"},
                    ),
                    SlideComponent(
                        id="match_demo",
                        component_type="MatchGame",
                        title="匹配",
                        data={"pairs": [{"left": "学", "right": "xue2"}]},
                    ),
                    SlideComponent(
                        id="character_demo",
                        component_type="CharacterFormation",
                        title="汉字构形",
                        data={"character": "学", "parts": ["⺍", "冖", "子"], "explanation": "部件组合成汉字。"},
                    ),
                ],
            )
        ],
    )

    html_path = render_lesson(tmp_path, profile, blueprint, AssetManifest(), QualityReport())
    html = html_path.read_text(encoding="utf-8")

    assert 'class="slide-frame"' in html
    assert "player-nav" in html
    assert 'data-mode="bilingual"' in html
    assert "component-container" in html
    assert "audio-component" in html
    assert "vocab-component" in html
    assert "drag-builder" in html
    assert "listen-choose" in html
    assert "match-game" in html
    assert "character-formation" in html
    assert "loading-state" in html
    assert "https://" not in html
    assert "http://" not in html
    assert "cdn" not in html.lower()


def test_llm_blueprint_provider_can_drive_pipeline(tmp_path: Path, monkeypatch) -> None:
    project_root, source, profile = _parsed_source(tmp_path, monkeypatch)
    settings = ProviderSettings(
        llm=LLMProviderSettings(
            provider="openai_compatible",
            base_url="https://api.example.com/v1",
            api_key="test-key",
            model="demo-llm",
        )
    )

    def fake_post_json(url, payload, headers, timeout):
        assert url == "https://api.example.com/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test-key"
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "lesson_title": "LLM 生成的中文课",
                                "objectives": ["会说目标句"],
                                "key_vocabulary": [{"word": "学习", "pinyin": "xue2 xi2", "meaning": "study"}],
                                "grammar_points": ["在...呢"],
                                "slides": [
                                    {
                                        "id": 9,
                                        "slide_type": "CoverSlide",
                                        "layout_variant": "centered_title",
                                        "title": "LLM 封面",
                                        "content_blocks": [],
                                        "components": [],
                                        "media_requirements": {},
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("hcs_api.providers._post_json", fake_post_json)
    blueprint = generate_lesson_blueprint(source, profile, settings)

    assert project_root.exists()
    assert blueprint.lesson_title == "LLM 生成的中文课"
    assert blueprint.slides[0].id == 1
    assert blueprint.slides[0].title == "LLM 封面"


def test_llm_blueprint_pipeline_falls_back_without_credentials(tmp_path: Path, monkeypatch) -> None:
    _, source, profile = _parsed_source(tmp_path, monkeypatch)
    settings = ProviderSettings(
        llm=LLMProviderSettings(
            provider="openai_compatible",
            base_url="https://api.example.com/v1",
            api_key="",
            model="demo-llm",
        )
    )

    blueprint = generate_lesson_blueprint(source, profile, settings)

    assert blueprint.lesson_title == "第14课 我在学习中文呢"
    assert len(blueprint.slides) >= 6


def test_media_pipeline_replaces_placeholder_assets_when_provider_returns_bytes(tmp_path: Path, monkeypatch) -> None:
    project_root, source, profile = _parsed_source(tmp_path, monkeypatch)
    blueprint = build_blueprint(source, profile)
    settings = ProviderSettings(
        image=ImageProviderSettings(provider="openai_images", api_key="image-key", model="demo-image"),
        audio=AudioProviderSettings(provider="openai_tts", api_key="audio-key", model="demo-tts", voice="demo"),
    )

    monkeypatch.setattr("hcs_api.media.generate_openai_image", lambda settings, prompt: b"png-bytes")
    monkeypatch.setattr("hcs_api.media.generate_openai_tts", lambda settings, text: b"mp3-bytes")

    manifest = generate_project_media(project_root, blueprint, settings)

    assert manifest.images
    assert manifest.audio
    assert all(asset.path.endswith(".png") for asset in manifest.images)
    assert all(asset.path.endswith(".mp3") for asset in manifest.audio)
    assert (project_root / manifest.images[0].path).read_bytes() == b"png-bytes"
    assert (project_root / manifest.audio[0].path).read_bytes() == b"mp3-bytes"


def _make_pptx(path: Path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "第14课 我在学习中文呢"
    slide.placeholders[1].text = "学习\n中文\n我在学习中文呢。"
    prs.save(path)


def _minimal_blueprint(slide_title: str = "第一页", components: list[SlideComponent] | None = None) -> LessonBlueprint:
    return LessonBlueprint(
        lesson_title="测试课",
        objectives=["完成一个练习"],
        key_vocabulary=[{"word": "好", "pinyin": "hao3", "meaning": "good"}],
        grammar_points=[],
        slides=[
            LessonSlide(
                id=1,
                slide_type="PracticeSlide",
                layout_variant="basic",
                title=slide_title,
                content_blocks=[ContentBlock(id="c1", text="你好")],
                components=components or [],
            )
        ],
    )


def _parsed_source(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("hcs_api.storage.RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr("hcs_api.storage.PROJECTS_DIR", tmp_path / "runtime" / "projects")
    pptx_path = tmp_path / "lesson.pptx"
    _make_pptx(pptx_path)
    project_root = ensure_project("testproject")
    source = parse_pptx(pptx_path, project_root, "lesson.pptx")
    profile = infer_profile(source)
    return project_root, source, profile
