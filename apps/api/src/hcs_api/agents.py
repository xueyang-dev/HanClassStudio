from __future__ import annotations

import re
from collections import Counter

from pypinyin import Style, lazy_pinyin

from .models import (
    ContentBlock,
    LessonBlueprint,
    LessonProfile,
    LessonSlide,
    MediaRequirements,
    SlideComponent,
    SourceMaterial,
)


SCAFFOLDING_HINTS = {
    "English": "Use short English hints for meaning and task feedback.",
    "Arabic": "استخدم تلميحات عربية قصيرة لدعم الفهم دون استبدال التدريب بالصينية.",
    "Russian": "Используйте краткие русские подсказки для понимания и обратной связи.",
    "Thai": "ใช้คำอธิบายภาษาไทยสั้น ๆ เพื่อช่วยความเข้าใจ",
    "Korean": "짧은 한국어 힌트로 의미와 과제 이해를 돕습니다.",
    "Japanese": "短い日本語のヒントで意味理解を支えます。",
    "Vietnamese": "Dùng gợi ý tiếng Việt ngắn để hỗ trợ hiểu nghĩa.",
    "Indonesian": "Gunakan petunjuk bahasa Indonesia singkat untuk membantu pemahaman.",
}


def infer_profile(source: SourceMaterial) -> LessonProfile:
    title = _first_title(source)
    return LessonProfile(
        lesson_title=title,
        learner_level="Beginner",
        target_students="International Chinese learners",
        scaffolding_language="English",
        lesson_type="New lesson",
        generation_mode="guided_redesign",
        estimated_duration="45 minutes",
    )


def build_blueprint(source: SourceMaterial, profile: LessonProfile) -> LessonBlueprint:
    vocabulary = _extract_vocabulary(source)
    if not vocabulary:
        vocabulary = [
            {"word": "学习", "pinyin": "xue xi", "meaning": _scaffold("to study / to learn", profile)},
            {"word": "中文", "pinyin": "zhong wen", "meaning": _scaffold("Chinese language", profile)},
            {"word": "老师", "pinyin": "lao shi", "meaning": _scaffold("teacher", profile)},
            {"word": "同学", "pinyin": "tong xue", "meaning": _scaffold("classmate", profile)},
        ]

    topic = profile.lesson_title
    grammar = _detect_grammar(source)
    objectives = [
        f"理解并朗读与“{topic}”相关的核心词句。",
        "在课堂互动中使用中文完成听、说、读的操练。",
        f"借助{profile.scaffolding_language}支架理解词义、任务和反馈。",
    ]

    slides = [
        LessonSlide(
            id=1,
            slide_type="CoverSlide",
            layout_variant="centered_title",
            title=topic,
            content_blocks=[
                ContentBlock(
                    id="cover_intro",
                    block_type="subtitle",
                    text=f"{profile.learner_level} · {profile.estimated_duration}",
                    scaffolding_text=_language_hint(profile),
                )
            ],
            media_requirements=MediaRequirements(
                image_prompt=_image_prompt(f"classroom scene for the Chinese lesson topic {topic}", profile),
                image_key="slide_1_scene",
            ),
        ),
        LessonSlide(
            id=2,
            slide_type="ObjectiveSlide",
            layout_variant="three_goals",
            title="学习目标",
            content_blocks=[
                ContentBlock(id=f"obj_{i}", block_type="objective", text=obj, scaffolding_text=_short_scaffold(obj, profile))
                for i, obj in enumerate(objectives, start=1)
            ],
        ),
        LessonSlide(
            id=3,
            slide_type="WarmUpSlide",
            layout_variant="image_prompt",
            title="看图说一说",
            content_blocks=[
                ContentBlock(
                    id="warmup_prompt",
                    block_type="prompt",
                    text="你看到了什么？用中文说一个词或一个句子。",
                    scaffolding_text=_scaffold("Look and say one Chinese word or sentence.", profile),
                )
            ],
            media_requirements=MediaRequirements(
                image_prompt=_image_prompt(f"simple warm-up illustration connected to {topic}", profile),
                image_key="slide_3_warmup",
            ),
        ),
        LessonSlide(
            id=4,
            slide_type="VocabularySlide",
            layout_variant="card_grid",
            title="生词练习",
            components=[
                SlideComponent(
                    id="vocab_cards",
                    component_type="VocabularyFlipCard",
                    title="生词卡",
                    data={
                        "items": [
                            {
                                "word": item["word"],
                                "pinyin": item["pinyin"],
                                "meaning": item["meaning"],
                                "example": f"我会说“{item['word']}”。",
                                "audio_key": f"word_{index}",
                                "audio_text": item["word"],
                            }
                            for index, item in enumerate(vocabulary[:6], start=1)
                        ]
                    },
                )
            ],
        ),
        LessonSlide(
            id=5,
            slide_type="GrammarPatternSlide",
            layout_variant="drag_builder",
            title="句型操练",
            content_blocks=[
                ContentBlock(
                    id="pattern",
                    block_type="pattern",
                    text=grammar,
                    scaffolding_text=_scaffold("Use the pattern to talk about what someone is doing now.", profile),
                )
            ],
            components=[
                SlideComponent(
                    id="sentence_drag",
                    component_type="SentenceDragBuilder",
                    title="拖拽组句",
                    data={
                        "words": ["我", "在", "学习", "中文", "呢"],
                        "answer": ["我", "在", "学习", "中文", "呢"],
                        "success": "很好！这个句子表示动作正在进行。",
                        "hint": _scaffold("Put the words in order to make a Chinese sentence.", profile),
                    },
                )
            ],
            media_requirements=MediaRequirements(audio_text="我在学习中文呢。", audio_key="sentence_pattern_1"),
        ),
        LessonSlide(
            id=6,
            slide_type="DialogueSlide",
            layout_variant="listen_choose",
            title="听一听，选一选",
            content_blocks=[
                ContentBlock(id="dialogue_a", block_type="dialogue", text="A：你在做什么？"),
                ContentBlock(id="dialogue_b", block_type="dialogue", text="B：我在学习中文呢。"),
            ],
            components=[
                SlideComponent(
                    id="listen_choose",
                    component_type="ListenAndChoose",
                    title="听音选择",
                    data={
                        "audio_key": "listen_choose_1",
                        "audio_text": "我在学习中文呢。",
                        "choices": ["我在学习中文呢。", "我喜欢吃苹果。", "老师在写汉字。"],
                        "answer": "我在学习中文呢。",
                        "hint": _scaffold("Listen and choose the sentence you hear.", profile),
                    },
                )
            ],
        ),
        LessonSlide(
            id=7,
            slide_type="PracticeSlide",
            layout_variant="match_pairs",
            title="连一连",
            components=[
                SlideComponent(
                    id="match_vocab",
                    component_type="MatchGame",
                    title="词语匹配",
                    data={
                        "pairs": [
                            {"left": item["word"], "right": item["pinyin"]}
                            for item in vocabulary[:4]
                        ],
                        "hint": _scaffold("Match each Chinese word with its pinyin.", profile),
                    },
                )
            ],
        ),
        LessonSlide(
            id=8,
            slide_type="SummarySlide",
            layout_variant="exit_ticket",
            title="课堂小结",
            content_blocks=[
                ContentBlock(id="sum_1", block_type="summary", text="今天我会读生词。"),
                ContentBlock(id="sum_2", block_type="summary", text="今天我会说一个正在进行的动作。"),
                ContentBlock(
                    id="sum_3",
                    block_type="summary",
                    text="请用中文说一句：我在____呢。",
                    scaffolding_text=_scaffold("Say one sentence in Chinese using the pattern.", profile),
                ),
            ],
        ),
    ]

    return LessonBlueprint(
        lesson_title=topic,
        objectives=objectives,
        key_vocabulary=vocabulary,
        grammar_points=[grammar],
        slides=_adapt_for_mode(slides, source, profile),
    )


def _first_title(source: SourceMaterial) -> str:
    for page in source.pages:
        if page.title.strip():
            return page.title.strip()
    return source.original_filename.rsplit(".", 1)[0] or "未命名中文课"


def _source_text(source: SourceMaterial) -> str:
    chunks: list[str] = []
    for page in source.pages:
        chunks.append(page.title)
        chunks.extend(block.text for block in page.text_blocks)
        chunks.append(page.ocr_text)
    return "\n".join(chunk for chunk in chunks if chunk)


def _extract_vocabulary(source: SourceMaterial) -> list[dict[str, str]]:
    text = _source_text(source)
    candidates = re.findall(r"[\u4e00-\u9fff]{1,4}", text)
    stop = {"第", "课", "学习", "目标", "练习", "中文", "老师", "同学"}
    counter = Counter(word for word in candidates if word not in stop and len(word) <= 4)
    common = [word for word, _ in counter.most_common(8)]
    if "中文" in text and "中文" not in common:
        common.insert(0, "中文")
    if "学习" in text and "学习" not in common:
        common.insert(0, "学习")
    vocabulary: list[dict[str, str]] = []
    for word in common[:8]:
        pinyin = " ".join(lazy_pinyin(word, style=Style.TONE3, neutral_tone_with_five=True))
        vocabulary.append({"word": word, "pinyin": pinyin, "meaning": "Meaning scaffold"})
    return vocabulary


def _detect_grammar(source: SourceMaterial) -> str:
    text = _source_text(source)
    if "在" in text and "呢" in text:
        return "sb. + 在 + V + 呢"
    if "了" in text:
        return "V + 了"
    if "喜欢" in text:
        return "sb. + 喜欢 + noun / verb"
    return "sb. + 在 + V + 呢"


def _language_hint(profile: LessonProfile) -> str:
    return SCAFFOLDING_HINTS.get(profile.scaffolding_language, "Use concise scaffolding hints.")


def _scaffold(text: str, profile: LessonProfile) -> str:
    if profile.scaffolding_language == "English":
        return text
    return f"{profile.scaffolding_language}: {text}"


def _short_scaffold(text: str, profile: LessonProfile) -> str:
    return _scaffold(text[:80], profile)


def _image_prompt(content: str, profile: LessonProfile) -> str:
    return (
        "Clean educational illustration, simple composition, no text, clear classroom use, "
        "soft colors, suitable for Chinese language teaching. "
        f"Scene: {content}. Scaffolding language context: {profile.scaffolding_language}."
    )


def _adapt_for_mode(slides: list[LessonSlide], source: SourceMaterial, profile: LessonProfile) -> list[LessonSlide]:
    if profile.generation_mode == "faithful":
        parsed_slides: list[LessonSlide] = []
        for page in source.pages:
            parsed_slides.append(
                LessonSlide(
                    id=page.page_number,
                    slide_type="ReadingSlide",
                    layout_variant="source_enhanced",
                    title=page.title,
                    content_blocks=[
                        ContentBlock(
                            id=block.id,
                            block_type=block.kind,
                            text=block.text,
                            scaffolding_text="",
                        )
                        for block in page.text_blocks[:4]
                    ],
                    media_requirements=MediaRequirements(
                        image_prompt=None,
                        image_key=page.images[0].id if page.images else None,
                    ),
                )
            )
        return parsed_slides or slides
    if profile.generation_mode == "reimagined":
        slides[0].layout_variant = "immersive_topic"
        slides[3].layout_variant = "large_cards"
        return slides
    return slides

