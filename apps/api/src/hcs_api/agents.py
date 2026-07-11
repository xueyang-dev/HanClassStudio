from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pypinyin import Style, lazy_pinyin

from .models import (
    ContentBlock,
    LessonBlueprint,
    LessonProfile,
    LessonSlide,
    MediaRequirements,
    RouteHint,
    SlideComponent,
    SourceMaterial,
    TeachingCandidates,
)


GREETING_GRAMMAR_WHITELIST = {
    "你 vs 您", "问候语", "称呼 + 您好", "A：... B：... 对话结构",
    "sb. + 在 + V + 呢",
}

GREETING_VOCAB_PRIORITY = {"你", "您", "你好", "您好", "你们好", "你们", "好", "老师", "同学", "再见", "谢谢", "不客气", "对不起", "没关系"}

GREETING_VOCAB_BLOCK = {"对话", "画", "笔顺", "读一读", "写一写", "听一听", "说一说", "选一选", "连一连", "做一做"}



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


# ── Route → human-readable lesson type map ──

ROUTE_TYPE_LABELS: dict[str, str] = {
    "greeting_lesson": "问候课（Greeting）",
    "vocabulary_lesson": "词汇课（Vocabulary）",
    "dialogue_lesson": "对话课（Dialogue）",
    "character_lesson": "汉字课（Character Writing）",
    "grammar_pattern_lesson": "语法课（Grammar Pattern）",
    "mixed_lesson": "综合课（Mixed Content）",
}

LEVEL_THRESHOLDS = {
    "Intermediate": (80, 200),   # (unique_chars, avg_chars_per_page)
    "Elementary":   (40, 100),
    "Beginner":     (0, 0),
}


def infer_profile(source: SourceMaterial) -> LessonProfile:
    """Intelligently infer LessonProfile from parsed source material.

    Uses content analysis (route hint, vocabulary density, page count, text
    complexity) instead of hardcoded defaults. Only lesson_title was previously
    inferred; all six other fields are now extracted heuristically.
    """
    from .analysis import extract_candidates

    title = _first_title(source)

    # Run full content analysis — reuse existing extraction pipeline
    candidates = extract_candidates(source)
    route = candidates.route_hint

    # Smart field inference
    level = _infer_learner_level(source, candidates)
    lesson_type = _infer_lesson_type(route)
    duration = _estimate_duration(source)

    return LessonProfile(
        lesson_title=title,
        subject="国际中文",
        learner_level=level,
        target_students="国际中文学习者",
        scaffolding_language="English",
        lesson_type=lesson_type,
        generation_mode="guided_redesign",
        estimated_duration=duration,
    )


def _infer_learner_level(source: SourceMaterial, candidates: TeachingCandidates) -> str:
    """Estimate learner level from text complexity signals."""
    # Greeting lessons are universally beginner / zero-beginner
    if candidates.route_hint == "greeting_lesson":
        return "Beginner"

    text = _source_text(source)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    unique_chars = set(chinese_chars)
    pages = max(len(source.pages), 1)

    avg_density = len(chinese_chars) / pages
    unique_count = len(unique_chars)

    # Grammar pattern count as difficulty signal
    grammar_count = len(candidates.grammar_candidates)

    # Character-focused lessons tend toward beginner (stroke practice)
    if candidates.route_hint == "character_lesson":
        return "Beginner"

    # High unique vocabulary + dense text + multiple grammar points → intermediate+
    if unique_count > 80 or (avg_density > 200 and grammar_count >= 3):
        return "Intermediate"
    if unique_count > 40 or (avg_density > 100 and grammar_count >= 2):
        return "Elementary"

    return "Beginner"


def _infer_lesson_type(route: str) -> str:
    """Map analysis route_hint to a human-readable lesson type label."""
    return ROUTE_TYPE_LABELS.get(route, "新授课（New Lesson）")


def _estimate_duration(source: SourceMaterial) -> str:
    """Heuristic duration estimate from page/slide count."""
    pages = len(source.pages)
    if source.source_type == "pptx":
        # Slides: cover (~2 min) + content slides (~5 min each)
        estimated = 8 + max(0, pages - 1) * 5
    else:
        # PDF: denser per page, ~3-4 min each
        estimated = pages * 4

    # Clamp to sane teaching range
    estimated = max(15, min(120, estimated))
    # Round up to nearest 5
    estimated = ((estimated + 4) // 5) * 5
    return f"{estimated} minutes"


def build_blueprint(
    source: SourceMaterial,
    profile: LessonProfile,
    candidates: TeachingCandidates | None = None,
    language_items: list | None = None,
) -> LessonBlueprint:
    """Build lesson blueprint from source material and optional teaching candidates."""
    from .analysis import extract_candidates

    if candidates is None:
        candidates = extract_candidates(source)

    route = candidates.route_hint
    vocabulary = candidates.core_vocabulary[:8]
    fallback_vocab = [
        {"word": "你好", "pinyin": "nǐ hǎo", "meaning": "hello"},
        {"word": "谢谢", "pinyin": "xiè xiè", "meaning": "thank you"},
        {"word": "再见", "pinyin": "zài jiàn", "meaning": "goodbye"},
    ]
    # Greeting lesson: filter out blocked words
    if route == "greeting_lesson":
        vocabulary = [v for v in vocabulary if v["word"] not in GREETING_VOCAB_BLOCK]
        # Ensure priority greeting words come first
        priority = [v for v in vocabulary if v["word"] in GREETING_VOCAB_PRIORITY]
        other = [v for v in vocabulary if v["word"] not in GREETING_VOCAB_PRIORITY]
        vocabulary = (priority + other)[:8]
    if not vocabulary:
        vocabulary = fallback_vocab

    topic = profile.lesson_title
    grammar = candidates.grammar_candidates[0]["pattern"] if candidates.grammar_candidates else ""
    objectives = _build_objectives(topic, route, profile)

    if route == "greeting_lesson":
        slides = _build_greeting_lesson(topic, vocabulary, candidates, grammar, profile, language_items)
    elif route == "dialogue_lesson":
        slides = _build_dialogue_lesson(topic, vocabulary, candidates, grammar, profile)
    elif route == "character_lesson":
        slides = _build_character_lesson(topic, vocabulary, candidates, grammar, profile)
    else:
        slides = _build_mixed_lesson(topic, vocabulary, candidates, grammar, profile)

    slides = _renumber_slides(slides)
    grammar_points = [c["pattern"] for c in candidates.grammar_candidates] if candidates.grammar_candidates else []

    # Route relevance filter: greeting_lesson only keeps whitelisted grammar points
    if route == "greeting_lesson":
        grammar_points = [gp for gp in grammar_points if gp in GREETING_GRAMMAR_WHITELIST]
    if not grammar_points and not grammar:
        grammar_points = [candidates.grammar_candidates[0]["pattern"]] if candidates.grammar_candidates else []

    return LessonBlueprint(
        lesson_title=topic,
        objectives=objectives,
        key_vocabulary=vocabulary,
        grammar_points=grammar_points,
        slides=slides,
        route_hint=route,
    )


# ── Objective building ──

def _build_objectives(topic: str, route: RouteHint, profile: LessonProfile) -> list[str]:
    base = [
        f"理解并朗读与“{topic}”相关的核心词句。",
        "在课堂互动中使用中文完成听、说、读的操练。",
    ]
    if route == "greeting_lesson":
        base.append("学会用中文向不同对象问好。")
        base.append(f"借助{profile.scaffolding_language}支架理解礼貌用语的区别。")
    elif route == "character_lesson":
        base.append("掌握本课汉字的笔顺和结构。")
        base.append(f"借助{profile.scaffolding_language}支架理解笔画名称。")
    elif route == "dialogue_lesson":
        base.append("能朗读并角色扮演本课对话。")
        base.append(f"借助{profile.scaffolding_language}支架理解对话内容。")
    else:
        base.append(f"借助{profile.scaffolding_language}支架理解词义、任务和反馈。")
    return base


# ── Greeting lesson builder ──

def _build_greeting_lesson(
    topic: str,
    vocabulary: list[dict[str, str]],
    candidates: TeachingCandidates,
    grammar: str,
    profile: LessonProfile,
    language_items: list | None = None,
) -> list[LessonSlide]:
    """Build greeting lesson following i+1: 1 new item per slide for zero_beginner."""
    from .learner_comprehension import GREETING_GLOSS
    slides: list[LessonSlide] = []
    slide_id = 0
    item_lookup = {li.target_form: li for li in (language_items or [])}
    gloss_lang = profile.scaffolding_language

    def _gloss(word: str) -> str:
        """Look up gloss from built-in table or language item."""
        if word in GREETING_GLOSS:
            return GREETING_GLOSS[word].get(gloss_lang, GREETING_GLOSS[word].get("English", ""))
        li = item_lookup.get(word)
        if li and li.scaffold_meaning:
            return li.scaffold_meaning
        return ""

    # 1. Cover
    slide_id += 1
    slides.append(LessonSlide(
        id=slide_id, slide_type="CoverSlide", layout_variant="centered_title",
        title=topic,
        content_blocks=[ContentBlock(
            id="cover_intro", block_type="subtitle",
            text=topic,
            scaffolding_text=_scaffold("Lesson 1: Hello (polite form)", profile),
        )],
    ))

    # 2. Objectives — in scaffold language for zero_beginner
    slide_id += 1
    slides.append(LessonSlide(
        id=slide_id, slide_type="ObjectiveSlide", layout_variant="three_goals",
        title="学习目标",
        content_blocks=[
            ContentBlock(id="obj_1", block_type="objective", text="你好！",
                         scaffolding_text=_scaffold("Greet others in Chinese", profile)),
            ContentBlock(id="obj_2", block_type="objective", text="您好！",
                         scaffolding_text=_scaffold("Use polite greetings", profile)),
            ContentBlock(id="obj_3", block_type="objective", text="一、二、三",
                         scaffolding_text=_scaffold("Write three characters", profile)),
        ],
    ))

    # 3. First word: 你好 — one item per slide
    slide_id += 1
    slides.append(_vocab_slide_zb(slide_id, [{"word": "你好", "pinyin": "nǐ hǎo"}], profile, _gloss,
                                   usage="", item_lookup=item_lookup, scaffold_lang=gloss_lang))

    # 4. Second word: 您好
    slide_id += 1
    slides.append(_vocab_slide_zb(slide_id, [{"word": "您好", "pinyin": "nín hǎo"}], profile, _gloss,
                                   usage="", item_lookup=item_lookup, scaffold_lang=gloss_lang))

    # 5. Politeness: 你 vs 您
    slide_id += 1
    slides.append(LessonSlide(
        id=slide_id, slide_type="GrammarPatternSlide", layout_variant="drag_builder",
        title="练一练",
        content_blocks=[ContentBlock(
            id="politeness_note", block_type="pattern",
            text="",
            scaffolding_text=_scaffold("", profile),
        )],
        components=[SlideComponent(
            id="sentence_drag", component_type="SentenceDragBuilder", title="",
            data={
                "words": ["你好", "您好", "！"],
                "answer": "您好！",
                "hint": _scaffold("Drag the words to make a polite greeting.", profile),
                "audio_key": "politeness_1", "audio_text": "您好！",
            },
        )],
    ))

    # 6. Dialogue practice
    slide_id += 1
    slides.append(LessonSlide(
        id=slide_id, slide_type="DialogueSlide", layout_variant="listen_and_choose",
        title="听一听，说一说",
        content_blocks=[
            ContentBlock(id="dialogue_1", block_type="dialogue_line", text="A：你好！",
                         scaffolding_text=_scaffold("Hello!", profile)),
            ContentBlock(id="dialogue_2", block_type="dialogue_line", text="B：你好！",
                         scaffolding_text=_scaffold("Hello!", profile)),
            ContentBlock(id="dialogue_3", block_type="dialogue_line", text="A：您好，老师！",
                         scaffolding_text=_scaffold("Hello, teacher!", profile)),
        ],
        components=[SlideComponent(
            id="dialogue_choice", component_type="ListenAndChoose", title="听音选择",
            data={
                "audio_key": "dialogue_1", "audio_text": "你好！",
                "choices": ["你好！", "您好！", "再见！"],
                "answer": "你好！",
                "hint": _scaffold("Listen and choose the correct greeting.", profile),
            },
        )],
    ))

    # 7. Match practice
    slide_id += 1
    slides.append(LessonSlide(
        id=slide_id, slide_type="PracticeSlide", layout_variant="match_game",
        title="连一连：问候配对",
        components=[SlideComponent(
            id="match_game", component_type="MatchGame", title="问候配对",
            data={
                "pairs": [
                    {"left": "你好", "right": "nǐ hǎo"},
                    {"left": "您好", "right": "nín hǎo"},
                ],
                "hint": _scaffold("Match each greeting with its pinyin.", profile),
            },
        )],
    ))

    # 8. Summary — in scaffold language
    slide_id += 1
    slides.append(LessonSlide(
        id=slide_id, slide_type="SummarySlide", layout_variant="review",
        title="课堂小结",
        content_blocks=[
            ContentBlock(id="sum_1", block_type="summary",
                         text="你好！",
                         scaffolding_text=_scaffold("Now I can greet in Chinese.", profile)),
            ContentBlock(id="sum_2", block_type="summary",
                         text="您好！",
                         scaffolding_text=_scaffold("I know when to use 您.", profile)),
        ],
    ))

    return slides


def _vocab_slide_zb(
    slide_id: int,
    vocabulary: list[dict[str, str]],
    profile: LessonProfile,
    gloss_fn,
    usage: str = "",
    item_lookup: dict | None = None,
    scaffold_lang: str = "English",
) -> LessonSlide:
    """Build vocabulary flip card for zero_beginner: 1 item, safe example, scaffold-language usage context."""
    from .content_contract import resolve_scaffold_usage
    items_data = []
    for item in vocabulary:
        word = item["word"]
        meaning = item.get("meaning", "") or gloss_fn(word)
        sc_usage = resolve_scaffold_usage(word, scaffold_lang, None, item_lookup) or usage
        items_data.append({
            "word": word,
            "pinyin": item["pinyin"],
            "meaning": meaning,
            "usage_context": sc_usage,
            "example": f"{word}！",
        })
    return LessonSlide(
        id=slide_id, slide_type="VocabularySlide", layout_variant="card_grid",
        title="生词卡",
        components=[SlideComponent(
            id="vocab_cards", component_type="VocabularyFlipCard", title="生词卡",
            data={"items": items_data},
        )],
    )

# ── Dialogue lesson builder ──

def _build_dialogue_lesson(
    topic: str, vocabulary: list[dict[str, str]], candidates: TeachingCandidates,
    grammar: str, profile: LessonProfile,
) -> list[LessonSlide]:
    slides: list[LessonSlide] = []
    slide_id = 0

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="CoverSlide", layout_variant="centered_title", title=topic,
        content_blocks=[ContentBlock(id="cover_intro", block_type="subtitle", text=f"{profile.learner_level} · {profile.estimated_duration}",
             scaffolding_text=_language_hint(profile))],
        media_requirements=MediaRequirements(image_prompt=_image_prompt(f"dialogue scene for {topic}", profile), image_key="slide_1_scene", media_kind="svg_illustration")))

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="ObjectiveSlide", layout_variant="three_goals", title="学习目标",
        content_blocks=[ContentBlock(id=f"obj_{i}", block_type="objective", text=obj, scaffolding_text=_short_scaffold(obj, profile))
                        for i, obj in enumerate(_build_objectives(topic, "dialogue_lesson", profile), start=1)]))

    # Vocabulary
    slide_id += 1
    slides.append(_vocab_slide(slide_id, vocabulary[:6], profile))

    # Dialogue slides
    dialogues = candidates.dialogue_candidates or [{"speaker": "A", "text": "你好！"}, {"speaker": "B", "text": "你好！"}]
    for i in range(0, len(dialogues), 2):
        slide_id += 1
        pair = dialogues[i:i + 2]
        audio = pair[0].get("text", "") if pair else ""
        slides.append(LessonSlide(id=slide_id, slide_type="DialogueSlide", layout_variant="listen_choose",
            title=f"对话练习 {i // 2 + 1}",
            content_blocks=[ContentBlock(id=f"dia_{i + j}", block_type="dialogue", text=f"{d.get('speaker','')}：{d.get('text','')}")
                            for j, d in enumerate(pair)],
            components=[SlideComponent(id=f"listen_{i // 2}", component_type="ListenAndChoose", title="听音选择",
                data={"audio_key": f"dialogue_{i // 2}", "audio_text": audio,
                      "choices": [d.get("text", "") for d in pair] or ["你好！"],
                      "answer": audio,
                      "hint": _scaffold("Listen and choose.", profile)})]))

    # Fill remaining with practice and summary
    if slide_id < 5:
        slide_id += 1
        slides.append(_match_slide(slide_id, vocabulary[:4], profile))
    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="SummarySlide", layout_variant="exit_ticket", title="课堂小结",
        content_blocks=[ContentBlock(id="sum_1", block_type="summary", text="今天我会朗读本课的对话。"),
                        ContentBlock(id="sum_2", block_type="summary", text="我能用中文和同学进行简单的对话。")]))

    return slides


# ── Character lesson builder ──

def _build_character_lesson(
    topic: str, vocabulary: list[dict[str, str]], candidates: TeachingCandidates,
    grammar: str, profile: LessonProfile,
) -> list[LessonSlide]:
    slides: list[LessonSlide] = []
    slide_id = 0
    chars = candidates.character_candidates or [v["word"] for v in vocabulary[:3] if len(v["word"]) <= 2]

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="CoverSlide", layout_variant="centered_title", title=topic,
        content_blocks=[ContentBlock(id="cover_intro", block_type="subtitle", text=f"{profile.learner_level} · {profile.estimated_duration}",
             scaffolding_text=_language_hint(profile))],
        media_requirements=MediaRequirements(image_prompt=_image_prompt(f"character writing scene for {topic}", profile), image_key="slide_1_scene", media_kind="svg_illustration")))

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="ObjectiveSlide", layout_variant="three_goals", title="学习目标",
        content_blocks=[ContentBlock(id=f"obj_{i}", block_type="objective", text=obj, scaffolding_text=_short_scaffold(obj, profile))
                        for i, obj in enumerate(_build_objectives(topic, "character_lesson", profile), start=1)]))

    if vocabulary:
        slide_id += 1
        slides.append(_vocab_slide(slide_id, vocabulary[:4], profile))

    for char in chars[:3]:
        slide_id += 1
        parts = list(char)
        slides.append(LessonSlide(id=slide_id, slide_type="PracticeSlide", layout_variant="formation", title=f"汉字：{char}",
            components=[SlideComponent(id=f"char_{char}", component_type="CharacterFormation", title="汉字构形",
                data={"character": char, "parts": parts, "explanation": f"“{char}”由 {len(parts)} 个笔画/部件组成。"})]))

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="SummarySlide", layout_variant="exit_ticket", title="课堂小结",
        content_blocks=[ContentBlock(id="sum_1", block_type="summary", text="今天我会写了新的汉字。"),
                        ContentBlock(id="sum_2", block_type="summary", text="我知道汉字的笔顺规则。")]))

    return slides


# ── Mixed lesson builder (default) ──

def _build_mixed_lesson(
    topic: str, vocabulary: list[dict[str, str]], candidates: TeachingCandidates,
    grammar: str, profile: LessonProfile,
) -> list[LessonSlide]:
    slides: list[LessonSlide] = []
    slide_id = 0

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="CoverSlide", layout_variant="centered_title", title=topic,
        content_blocks=[ContentBlock(id="cover_intro", block_type="subtitle", text=f"{profile.learner_level} · {profile.estimated_duration}",
             scaffolding_text=_language_hint(profile))],
        media_requirements=MediaRequirements(image_prompt=_image_prompt(f"classroom scene for {topic}", profile), image_key="slide_1_scene", media_kind="svg_illustration")))

    slide_id += 1
    objectives = _build_objectives(topic, "mixed_lesson", profile)
    slides.append(LessonSlide(id=slide_id, slide_type="ObjectiveSlide", layout_variant="three_goals", title="学习目标",
        content_blocks=[ContentBlock(id=f"obj_{i}", block_type="objective", text=obj, scaffolding_text=_short_scaffold(obj, profile))
                        for i, obj in enumerate(objectives, start=1)]))

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="WarmUpSlide", layout_variant="image_prompt", title="看图说一说",
        content_blocks=[ContentBlock(id="warmup_prompt", block_type="prompt", text="你看到了什么？用中文说一个词或一个句子。",
             scaffolding_text=_scaffold("Look and say one Chinese word or sentence.", profile))],
        media_requirements=MediaRequirements(image_prompt=_image_prompt(f"simple warm-up for {topic}", profile), image_key="slide_3_warmup", media_kind="svg_illustration")))

    slide_id += 1
    slides.append(_vocab_slide(slide_id, vocabulary[:6], profile))

    if grammar:
        slide_id += 1
        slides.append(LessonSlide(id=slide_id, slide_type="GrammarPatternSlide", layout_variant="drag_builder", title="句型操练",
            content_blocks=[ContentBlock(id="pattern", block_type="pattern", text=grammar,
                 scaffolding_text=_scaffold("Use the pattern to talk about what someone is doing now.", profile))],
            components=[SlideComponent(id="sentence_drag", component_type="SentenceDragBuilder", title="拖拽组句",
                data={"words": ["我", "在", "学习", "中文", "呢"], "answer": ["我", "在", "学习", "中文", "呢"],
                      "success": "很好！", "hint": _scaffold("Put the words in order.", profile)})],
            media_requirements=MediaRequirements(audio_text="我在学习中文呢。", audio_key="sentence_pattern_1")))

    dialogues = candidates.dialogue_candidates
    if dialogues:
        slide_id += 1
        slides.append(LessonSlide(id=slide_id, slide_type="DialogueSlide", layout_variant="listen_choose", title="对话练习",
            content_blocks=[ContentBlock(id=f"dia_{i}", block_type="dialogue", text=f"{d.get('speaker','')}：{d.get('text','')}")
                            for i, d in enumerate(dialogues[:2])],
            components=[SlideComponent(id="listen_dialogue", component_type="ListenAndChoose", title="听音选择",
                data={"audio_key": "dialogue_1", "audio_text": dialogues[0].get("text", ""),
                      "choices": [d.get("text", "") for d in dialogues[:3]] or ["你好！"],
                      "answer": dialogues[0].get("text", ""),
                      "hint": _scaffold("Listen and choose.", profile)})]))

    slide_id += 1
    slides.append(_match_slide(slide_id, vocabulary[:4], profile))

    slide_id += 1
    slides.append(LessonSlide(id=slide_id, slide_type="SummarySlide", layout_variant="exit_ticket", title="课堂小结",
        content_blocks=[ContentBlock(id="sum_1", block_type="summary", text="今天我会读生词和句子。"),
                        ContentBlock(id="sum_2", block_type="summary", text="我可以用中文回答简单的问题。")]))

    return slides


# ── Reusable slide builders ──

def _vocab_slide(slide_id: int, vocabulary: list[dict[str, str]], profile: LessonProfile,
                  language_items: list | None = None) -> LessonSlide:
    """Build vocabulary slide with comprehensible cards. No '我会说' template for zero_beginner."""
    lookup = {li.target_form: li for li in (language_items or [])}
    items_data = []
    for item in vocabulary:
        word = item["word"]
        li = lookup.get(word)
        meaning = item.get("meaning", "") or (li.scaffold_meaning if li else "")
        context = li.usage_context if li else ""
        example = f"{word}！"
        items_data.append({"word": word, "pinyin": item["pinyin"], "meaning": meaning,
                           "usage_context": context, "example": example})
    return LessonSlide(
        id=slide_id, slide_type="VocabularySlide", layout_variant="card_grid", title="生词练习",
        components=[SlideComponent(
            id="vocab_cards", component_type="VocabularyFlipCard", title="生词卡",
            data={"items": items_data},
        )],
    )


def _match_slide(slide_id: int, vocabulary: list[dict[str, str]], profile: LessonProfile) -> LessonSlide:
    pairs = [{"left": item["word"], "right": item["pinyin"]} for item in vocabulary[:4]]
    return LessonSlide(
        id=slide_id, slide_type="PracticeSlide", layout_variant="match_pairs", title="连一连",
        components=[SlideComponent(
            id="match_vocab", component_type="MatchGame", title="词语匹配",
            data={"pairs": pairs, "hint": _scaffold("Match each word with its pinyin.", profile)},
        )],
    )


# ── Helpers ──

def _renumber_slides(slides: list[LessonSlide]) -> list[LessonSlide]:
    for i, slide in enumerate(slides):
        slide.id = i + 1
    return slides


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


def _language_hint(profile: LessonProfile) -> str:
    return SCAFFOLDING_HINTS.get(profile.scaffolding_language, "Use concise scaffolding hints.")


def _scaffold(text: str, profile: LessonProfile) -> str:
    if profile.scaffolding_language == "English":
        return text
    return f"[{profile.scaffolding_language}] — provider_required: translate '{text}'"


def _short_scaffold(text: str, profile: LessonProfile) -> str:
    return _scaffold(text[:80], profile)


def _image_prompt(content: str, profile: LessonProfile) -> str:
    return (
        "Clean educational illustration, simple composition, no text, clear classroom use, "
        "soft colors, suitable for Chinese language teaching. "
        f"Scene: {content}. Scaffolding language context: {profile.scaffolding_language}."
    )
