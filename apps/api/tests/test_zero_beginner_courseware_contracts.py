from __future__ import annotations

from pathlib import Path

import pytest

from hcs_api import storage
from hcs_api.learner_comprehension import build_learner_model, check_comprehensibility
from hcs_api.models import (
    AssetManifest,
    ContentBlock,
    LessonBlueprint,
    LessonProfile,
    LessonSlide,
    LanguageItem,
    MediaRequirements,
    QualityReport,
    SlideComponent,
    SourceMaterial,
    SourcePage,
    TextBlock,
)
from hcs_api.pipeline import render_and_check
from hcs_api.pinyin_annotation import pinyin_for_text, pinyin_segments
from hcs_api.pptx_deck import build_pptx_deck_plan, build_pptx_structure_report
from hcs_api.pptx_exporter import _rasterize_svg, export_editable_pptx
from hcs_api.providers import _blueprint_prompt, normalize_blueprint
from hcs_api.strategist import build_media_plan
from hcs_api.syllabus_engine import build_difficulty_profile, build_source_lesson_profile
from hcs_api.renderer import _render_slide, _target_html


def _first_lesson_source() -> SourceMaterial:
    return SourceMaterial(
        source_type="pdf",
        original_filename="第一课.pdf",
        pages=[
            SourcePage(
                page_number=1,
                title="第1课 你好",
                text_blocks=[
                    TextBlock(
                        id="source",
                        text=(
                            "LESSON 1 Hello 入门篇 语音 Phonetics "
                            "声母 Initials 韵母 Finals 声调 Tones 声调位置 Tone position "
                            "轻声 Neutral tone 变调 Tone changes nǐ hǎo → ní hǎo "
                            "你好 您 谢谢 不客气 对不起 没关系 再见"
                        ),
                    )
                ],
            )
        ],
    )


def test_confirmed_zero_beginner_profile_preserves_adult_age_group() -> None:
    learner = build_learner_model(
        LessonProfile(
            learner_level="零基础（Pre-HSK / CEFR Pre-A1）",
            target_students="成年初学者",
        )
    )
    assert learner.level == "zero_beginner"
    assert learner.age_group == "adult"
    assert learner.known_words == []


def test_difficulty_uses_confirmed_zero_beginner_instead_of_textbook_explanation_density() -> None:
    source = _first_lesson_source()
    profile = LessonProfile(learner_level="零基础（Pre-A1）", target_students="成年初学者")
    difficulty = build_difficulty_profile(source, profile, build_source_lesson_profile(source))
    assert difficulty.estimated_level == "zero_beginner"
    assert any("confirmed learner profile" in item for item in difficulty.evidence)


def test_codex_prompt_requires_source_first_phonetics_and_scaffold_language() -> None:
    prompt = _blueprint_prompt(
        _first_lesson_source(),
        LessonProfile(
            learner_level="零基础（Pre-A1）",
            target_students="成年初学者",
            generation_mode="faithful",
            scaffolding_language="English",
        ),
    )
    assert "source order and textbook scope" in prompt
    assert "声母, 韵母, 声调" in prompt
    assert "learner-facing instructions and explanations" in prompt
    assert "decorative stock imagery" in prompt
    assert "Every VocabularySlide and DialogueSlide" in prompt


def test_zero_beginner_blueprint_normalization_requires_semantic_scene_visuals() -> None:
    blueprint = LessonBlueprint(
        lesson_title="你好",
        slides=[
            LessonSlide(
                id=8,
                slide_type="VocabularySlide",
                layout_variant="cards",
                title="Thanking",
                components=[
                    SlideComponent(
                        id="vocab",
                        component_type="VocabularyFlipCard",
                        data={
                            "items": [
                                {
                                    "word": "谢谢",
                                    "pinyin": "xièxie",
                                    "meaning": "thank you",
                                    "usage_context": "Use after someone helps you.",
                                },
                                {
                                    "word": "不客气",
                                    "pinyin": "bú kèqi",
                                    "meaning": "you are welcome",
                                },
                            ]
                        },
                    )
                ],
            ),
            LessonSlide(
                id=9,
                slide_type="DialogueSlide",
                layout_variant="dialogue",
                title="Textbook dialogue",
                content_blocks=[
                    ContentBlock(id="a", block_type="dialogue", text="A：谢谢！", scaffolding_text="Thank you!"),
                    ContentBlock(id="b", block_type="dialogue", text="B：不客气！", scaffolding_text="You're welcome!"),
                ],
            ),
            LessonSlide(
                id=10,
                slide_type="PhoneticsSlide",
                layout_variant="diagram",
                title="声调 · Tones",
            ),
            LessonSlide(
                id=11,
                slide_type="PracticeSlide",
                layout_variant="matching",
                title="Practice",
            ),
            LessonSlide(
                id=12,
                slide_type="VocabularySlide",
                layout_variant="cards",
                title="Teacher-selected scene",
                media_requirements=MediaRequirements(
                    image_key="teacher_scene",
                    image_prompt="Teacher-approved source-aligned scene",
                    media_kind="raster",
                ),
            ),
        ],
    )

    normalized = normalize_blueprint(
        blueprint,
        LessonProfile(
            learner_level="零基础（Pre-A1）",
            target_students="成年初学者",
            scaffolding_language="English",
        ),
    )

    vocabulary, dialogue, phonetics, practice, teacher_selected = normalized.slides
    for slide in (vocabulary, dialogue):
        assert slide.media_requirements.media_kind == "raster"
        assert slide.media_requirements.image_key
        assert slide.media_requirements.image_prompt
        assert "adult" in slide.media_requirements.image_prompt.lower()
        assert "no written words" in slide.media_requirements.image_prompt.lower()
    assert "谢谢" in vocabulary.media_requirements.image_prompt
    assert "A：谢谢！" in dialogue.media_requirements.image_prompt
    assert phonetics.media_requirements.image_key is None
    assert practice.media_requirements.image_key is None
    assert teacher_selected.media_requirements.image_key == "teacher_scene"

    media_plan = build_media_plan(normalized)
    assert {item["id"] for item in media_plan["images"]} == {
        vocabulary.media_requirements.image_key,
        dialogue.media_requirements.image_key,
        "teacher_scene",
    }


def test_zero_beginner_gate_blocks_missing_phonetics_chinese_instructions_and_vocab_overload() -> None:
    blueprint = LessonBlueprint(
        lesson_title="你好",
        slides=[
            LessonSlide(
                id=1,
                slide_type="VocabularySlide",
                layout_variant="cards",
                title="你好",
                content_blocks=[
                    ContentBlock(id="instruction", block_type="instruction", text="先看中文，再跟老师读三遍。")
                ],
                components=[
                    SlideComponent(
                        id="vocab",
                        component_type="VocabularyFlipCard",
                        data={
                            "hint": "请跟老师读。",
                            "items": [
                                {"word": "你好", "pinyin": "nǐ hǎo", "meaning": "hello"},
                                {"word": "谢谢", "pinyin": "xièxie", "meaning": "thank you"},
                                {"word": "再见", "pinyin": "zàijiàn", "meaning": "goodbye"},
                            ]
                        },
                    )
                ],
            )
        ],
    )
    report = check_comprehensibility(
        blueprint,
        [],
        build_learner_model(LessonProfile(learner_level="零基础", scaffolding_language="English")),
        _first_lesson_source(),
    )
    assert report.state == "blocked"
    assert any("新词数" in item for item in report.blocking)
    assert any("拼音教学覆盖" in item for item in report.blocking)
    assert any("中介语" in item for item in report.blocking)


def test_zero_beginner_gate_blocks_lesson_vocab_budget() -> None:
    slides = []
    for index in range(6):
        slides.append(
            LessonSlide(
                id=index + 1,
                slide_type="VocabularySlide",
                layout_variant="cards",
                title=f"Vocabulary {index + 1}",
                components=[
                    SlideComponent(
                        id=f"vocab-{index}",
                        component_type="VocabularyFlipCard",
                        data={
                            "items": [
                                {"word": f"词{index * 2 + 1}", "meaning": "item"},
                                {"word": f"词{index * 2 + 2}", "meaning": "item"},
                            ]
                        },
                    )
                ],
            )
        )
    report = check_comprehensibility(
        LessonBlueprint(lesson_title="你好", slides=slides),
        [],
        build_learner_model(LessonProfile(learner_level="零基础", scaffolding_language="English")),
    )
    assert any("全课新词数" in item for item in report.blocking)


def test_final_blueprint_usage_context_satisfies_zero_beginner_gate() -> None:
    blueprint = LessonBlueprint(
        lesson_title="你好",
        slides=[
            LessonSlide(
                id=1,
                slide_type="VocabularySlide",
                layout_variant="cards",
                title="Thanking",
                components=[
                    SlideComponent(
                        id="vocab",
                        component_type="VocabularyFlipCard",
                        data={
                            "items": [
                                {
                                    "word": "谢谢",
                                    "pinyin": "xièxie",
                                    "meaning": "thank you",
                                    "usage_context": "Use after someone helps you.",
                                }
                            ]
                        },
                    )
                ],
            )
        ],
    )
    report = check_comprehensibility(
        blueprint,
        [LanguageItem(id="thanks", target_form="谢谢", usage_context="")],
        build_learner_model(LessonProfile(learner_level="零基础", scaffolding_language="English")),
    )
    assert not report.missing_usage_context


def test_pptx_structure_blocks_dense_summary_cards() -> None:
    blueprint = LessonBlueprint(
        lesson_title="你好",
        slides=[
            LessonSlide(
                id=1,
                slide_type="SummarySlide",
                layout_variant="summary",
                title="Exit task",
                content_blocks=[
                    ContentBlock(
                        id="dense",
                        block_type="summary",
                        text="This instruction is much too long to fit inside a single summary card without wrapping across the card boundary.",
                    )
                ],
            )
        ],
    )
    report = build_pptx_structure_report(build_pptx_deck_plan(blueprint, learner_level="zero_beginner"))
    assert report["state"] == "blocked"
    assert any("summary card" in item for item in report["blocked"])


def test_phonetics_slide_has_exportable_content_and_svg_rasterization(tmp_path: Path) -> None:
    slide = LessonSlide(
        id=1,
        slide_type="PhoneticsSlide",
        layout_variant="diagram",
        title="声调 · Tones",
        content_blocks=[
            ContentBlock(id="tones", block_type="phonetic_example", text="mā má mǎ mà", scaffolding_text="four tones")
        ],
    )
    deck_slide = build_pptx_deck_plan(
        LessonBlueprint(lesson_title="你好", slides=[slide]), learner_level="zero_beginner"
    ).slides[0]
    assert deck_slide.main_focus == "声调 · Tones"
    assert deck_slide.target_text == "mā má mǎ mà"

    svg = tmp_path / "tones.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
        '<rect width="320" height="180" fill="#f5f5f5"/>'
        '<path d="M20 140 L300 40" stroke="#087e8b" stroke-width="8"/>'
        '</svg>',
        encoding="utf-8",
    )
    png = _rasterize_svg(svg)
    assert png is not None and png.exists()


def test_editable_pptx_uses_normalized_level_and_refuses_dense_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "zero_beginner_pptx"
    storage.ensure_project(project_id)
    storage.write_model(
        project_id,
        "lesson_profile.json",
        LessonProfile(learner_level="零基础（Pre-A1）", target_students="成年初学者"),
    )
    storage.write_model(project_id, "quality_report.json", QualityReport(state="pass"))
    storage.write_model(
        project_id,
        "lesson_blueprint.json",
        LessonBlueprint(
            lesson_title="你好",
            slides=[
                LessonSlide(
                    id=1,
                    slide_type="SummarySlide",
                    layout_variant="summary",
                    title="Exit task",
                    content_blocks=[
                        ContentBlock(
                            id="dense",
                            block_type="summary",
                            text="This instruction is much too long to fit inside a single summary card without wrapping across the card boundary.",
                        )
                    ],
                )
            ],
        ),
    )
    with pytest.raises(PermissionError, match="PPTX structure gate"):
        export_editable_pptx(project_id)
    plan = storage.read_json(project_id, "blueprints/pptx_deck_plan.json")
    assert plan["learner_level"] == "zero_beginner"


def test_render_gate_persists_zero_beginner_comprehensibility_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "zero_beginner_render_gate"
    project_root = storage.ensure_project(project_id)
    profile = LessonProfile(
        learner_level="零基础（Pre-A1）",
        target_students="成年初学者",
        scaffolding_language="English",
    )
    blueprint = LessonBlueprint(
        lesson_title="你好",
        slides=[
            LessonSlide(
                id=1,
                slide_type="PracticeSlide",
                layout_variant="prompt",
                title="Practice",
                content_blocks=[
                    ContentBlock(id="instruction", block_type="instruction", text="请跟老师读。")
                ],
            )
        ],
    )
    storage.write_model(project_id, "source_material.json", _first_lesson_source())
    storage.write_model(project_id, "lesson_profile.json", profile)
    storage.write_json(
        project_id,
        "analysis/learner_model.json",
        build_learner_model(profile).model_dump(mode="json", by_alias=True),
    )
    storage.write_json(project_id, "analysis/language_items.json", [])

    report = render_and_check(
        project_id,
        project_root,
        profile,
        blueprint,
        AssetManifest(),
        render_mode="classroom",
    )

    assert report.state == "blocked"
    assert any("拼音教学覆盖" in item for item in report.blocking)
    persisted = storage.read_model(project_id, "quality_report.json", QualityReport)
    assert persisted is not None
    assert persisted.state == "blocked"
    assert persisted.blocking == report.blocking


def test_zero_beginner_target_text_gets_tone_mark_pinyin_annotation() -> None:
    assert pinyin_for_text("你好！") == "nǐ hǎo"
    assert pinyin_segments("A：你好！") == [("A：", ""), ("你好", "nǐ hǎo"), ("！", "")]
    assert _target_html("A：你好！", True) == "A：<ruby>你好<rt>nǐ hǎo</rt></ruby>！"
    assert _target_html("谢谢！", True, {"谢谢": "xièxie"}) == "<ruby>谢谢<rt>xièxie</rt></ruby>！"
    assert _target_html("A：你好！", False) == "A：你好！"


def test_zero_beginner_cover_merges_duplicate_target_into_annotated_title() -> None:
    slide = LessonSlide(
        id=1,
        slide_type="CoverSlide",
        layout_variant="cover",
        title="你好！",
        content_blocks=[ContentBlock(id="cover", block_type="target", text="你好！", scaffolding_text="nǐ hǎo · Hello!")],
    )
    html = _render_slide(slide, {}, {}, annotate_pinyin=True, pronunciations={"你好": "nǐ hǎo"})
    assert html.count("<ruby>你好<rt>nǐ hǎo</rt></ruby>") == 1
    assert "Hello!" in html
    assert "nǐ hǎo · Hello!" not in html


def test_classroom_component_slide_uses_single_column_without_media() -> None:
    slide = LessonSlide(
        id=1,
        slide_type="PracticeSlide",
        layout_variant="matching",
        title="Exit check · Complete the textbook exchange",
        components=[SlideComponent(id="match", component_type="MatchGame", data={"pairs": []})],
    )
    html = _render_slide(slide, {}, {}, render_mode="classroom", annotate_pinyin=True)
    assert 'class="slide PracticeSlide has-components"' in html
    assert 'class="slide-content no-media"' in html
