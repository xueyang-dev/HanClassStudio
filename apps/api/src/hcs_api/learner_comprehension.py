"""Learner Comprehension Core — plan comprehensible input based on learner model."""

from __future__ import annotations

import json
import re
from typing import Any

from .content_contract import check_scaffold_language
from .models import (
    ComprehensibilityReport,
    InputSequenceItem,
    InputSequencePlan,
    LanguageItem,
    LearnerLevel,
    LearnerModel,
    LessonBlueprint,
    LessonProfile,
    SourceMaterial,
    TeachingCandidates,
)


# ── Built-in minimal gloss tables ──

GREETING_GLOSS: dict[str, dict[str, str]] = {
    "你好": {
        "Arabic": "مرحبًا",
        "English": "hello",
    },
    "您好": {
        "Arabic": "مرحبًا / تحية رسمية",
        "English": "hello (polite)",
    },
    "你": {
        "Arabic": "أنتَ / أنتِ",
        "English": "you (informal)",
    },
    "您": {
        "Arabic": "حضرتك / أنتَ باحترام",
        "English": "you (polite/formal)",
    },
    "你们": {
        "Arabic": "أنتم",
        "English": "you (plural)",
    },
    "你们好": {
        "Arabic": "مرحبًا بكم",
        "English": "hello (to a group)",
    },
    "好": {
        "Arabic": "جيد / بخير",
        "English": "good / fine",
    },
    "老师": {
        "Arabic": "مُعَلِّم / مُعَلِّمَة",
        "English": "teacher",
    },
    "再见": {
        "Arabic": "إلى اللقاء / مَعَ السَّلَامَة",
        "English": "goodbye",
    },
    "同学": {
        "Arabic": "زَمِيل / زَمِيلَة",
        "English": "classmate",
    },
    "谢谢": {
        "Arabic": "شُكْرًا",
        "English": "thank you",
    },
}

# Words that should not appear in example sentences unless explicitly taught
META_WORDS = {"我会说", "我会读", "我会写", "请用中文说", "请用中文回答"}
KNOWN_FUNCTIONAL = {"我", "的", "了", "是", "在", "有", "不", "和", "也", "都", "就", "很", "会", "能", "要"}


def resolve_profile_learner_level(profile: LessonProfile) -> LearnerLevel:
    """Normalize teacher-facing level labels into the backend learner contract."""
    value = (profile.learner_level or "").strip().lower()
    if any(marker in value for marker in ("zero", "零基础", "pre-a1", "pre-hsk")) or value in {"0", "zb"}:
        return "zero_beginner"
    if any(marker in value for marker in ("beginner", "初级", "hsk 1", "hsk1", "a1")):
        return "beginner"
    if any(marker in value for marker in ("elementary", "初中级", "hsk 2", "hsk2", "a2")):
        return "elementary"
    if any(marker in value for marker in ("intermediate", "中级", "hsk 3", "hsk3", "b1")):
        return "intermediate"
    return "zero_beginner"


def _age_group(profile: LessonProfile) -> str:
    value = (profile.target_students or "").lower()
    if any(marker in value for marker in ("成年", "成人", "adult")):
        return "adult"
    if any(marker in value for marker in ("老年", "senior", "older adult")):
        return "older_adult"
    if any(marker in value for marker in ("幼儿", "preschool")):
        return "preschool"
    if any(marker in value for marker in ("少年", "teen", "adolescent")):
        return "adolescent"
    if any(marker in value for marker in ("儿童", "child")):
        return "child"
    return "unspecified"


def build_learner_model(profile: LessonProfile) -> LearnerModel:
    """Build a LearnerModel from the lesson profile and level defaults."""
    level = resolve_profile_learner_level(profile)

    return LearnerModel(
        target_language="Chinese",
        scaffold_language=profile.scaffolding_language,
        level=level,
        age_group=_age_group(profile),
        known_words=[] if level == "zero_beginner" else list(KNOWN_FUNCTIONAL),
        new_word_limit_per_slide=2 if level in ("zero_beginner", "beginner") else 4,
        new_word_limit_per_lesson=10 if level in ("zero_beginner", "beginner") else 20,
        max_sentence_length=8 if level == "zero_beginner" else 12,
        require_scaffold_meaning=True,
        require_usage_scene=level in ("zero_beginner", "beginner"),
        allow_meta_language=False,
        classroom_instruction_policy="scaffold_first",
    )


def build_language_items(
    candidates: TeachingCandidates,
    learner: LearnerModel,
) -> list[LanguageItem]:
    """Convert teaching candidates into LanguageItems with gloss lookup."""
    items: list[LanguageItem] = []
    gloss_table = GREETING_GLOSS

    for idx, v in enumerate(candidates.core_vocabulary):
        word = v["word"]
        meaning = v.get("meaning", "")
        if not meaning or meaning == "":
            meaning = _lookup_gloss(word, learner.scaffold_language, gloss_table)
        items.append(LanguageItem(
            id=f"vocab_{idx}",
            item_type="word",
            target_form=word,
            pronunciation=v.get("pinyin", ""),
            scaffold_meaning=meaning or "",
            usage_context=_usage_context(word, candidates.route_hint),
            example=_example_sentence(word, learner),
            example_gloss=_lookup_gloss(word, learner.scaffold_language, gloss_table) if not meaning else "",
            difficulty=1,
            source_evidence="core_vocabulary",
        ))

    if candidates.route_hint == "greeting_lesson" and not any(item.target_form == "您好" for item in items):
        items.append(LanguageItem(
            id="vocab_polite_hello",
            item_type="word",
            target_form="您好",
            pronunciation="nín hǎo",
            scaffold_meaning=_lookup_gloss("您好", learner.scaffold_language, gloss_table),
            usage_context="对老师、长辈等尊敬的人使用",
            example="您好！",
            difficulty=1,
            source_evidence="greeting_composition",
        ))

    # Add politeness pattern as a LanguageItem
    for gc in candidates.grammar_candidates:
        if "vs" in gc["pattern"] or "对比" in gc.get("note", ""):
            items.append(LanguageItem(
                id="pattern_politeness",
                item_type="pattern",
                target_form=gc["pattern"],
                pronunciation="",
                scaffold_meaning=_grammar_meaning(gc, learner.scaffold_language),
                usage_context="当与老师或长辈说话时使用“您”",
                example="老师，您好！",
                example_gloss="أستاذ، مرحبًا! (معلم, مرحبا)",
                difficulty=1,
                source_evidence="grammar_candidate",
            ))

    return items


def _lookup_gloss(word: str, language: str, table: dict[str, dict[str, str]] | None = None) -> str:
    if table and word in table:
        return table[word].get(language, table[word].get("English", ""))
    return ""


def _usage_context(word: str, route: str) -> str:
    if route == "greeting_lesson":
        if word in ("你好", "您好"):
            return "初次见面或打招呼时使用"
        if word == "您":
            return "对老师、长辈等尊敬的人使用"
        if word == "你":
            return "对朋友、同学等平辈使用"
        if word == "你们":
            return "对两个或两个以上的人使用"
        if word == "好":
            return "表示状态良好，也可用于问候"
        if word == "老师":
            return "称呼在学校教课的人"
        if word in ("再见",):
            return "道别时使用"
    return ""


def _example_sentence(word: str, learner: LearnerModel) -> str:
    if word in ("你好", "您好"):
        return f"{word}！"
    if word == "你":
        return "你好！"
    if word == "您":
        return "您好！"
    if word == "好":
        return "你好！"
    return f"{word}。"


def _grammar_meaning(gc: dict, lang: str) -> str:
    if lang == "Arabic":
        return "الفرق بين '你' (للمألوف) و '您' (للاحترام)"
    return "Difference between 你 (informal) and 您 (polite)"


def plan_comprehensible_input(
    language_items: list[LanguageItem],
    learner: LearnerModel,
) -> InputSequencePlan:
    """Plan the sequence of introducing new language items."""
    plan = InputSequencePlan(learner_level=learner.level)
    warnings: list[str] = []

    known = set(learner.known_words)
    order = 0
    seen: set[str] = set()

    for item in language_items:
        if item.target_form in seen:
            continue
        seen.add(item.target_form)
        order += 1

        # Check for prerequisite violations
        for prereq in item.prerequisites:
            if prereq not in known and prereq not in seen:
                warnings.append(f"'{item.target_form}' 依赖前置词 '{prereq}'，但尚未介绍")

        # Check scaffold meaning
        if learner.require_scaffold_meaning and not item.scaffold_meaning:
            warnings.append(f"'{item.target_form}' 缺少支架释义")

        # Check usage context
        if learner.require_usage_scene and not item.usage_context:
            warnings.append(f"'{item.target_form}' 缺少使用场景")

        # Check example sentence for unknown words
        if item.example:
            example_words = re.findall(r"[\u4e00-\u9fff]+", item.example)
            unknown_in_example = [w for w in example_words if w not in known and w != item.target_form and w not in seen and w not in KNOWN_FUNCTIONAL and len(w) <= 4]
            if unknown_in_example:
                warnings.append(f"例句“{item.example}”包含未教授词：{', '.join(unknown_in_example[:3])}")

        plan.items.append(InputSequenceItem(
            order=order,
            language_item_id=item.id,
            presentation_type="vocabulary",
            notes=item.usage_context or "",
        ))

    plan.warnings = warnings
    return plan


def check_comprehensibility(
    blueprint: LessonBlueprint,
    language_items: list[LanguageItem],
    learner: LearnerModel,
    source: SourceMaterial | None = None,
) -> ComprehensibilityReport:
    """Check final blueprint for comprehensibility issues."""
    report = ComprehensibilityReport()
    item_by_form = {li.target_form: li for li in language_items}
    known = set(learner.known_words)

    # Track which items have been introduced
    introduced: set[str] = set()
    NEW_WORD_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,4}")

    for slide in blueprint.slides:
        label = f"第 {slide.id} 页"

        # Check new word count per slide
        slide_new_words = set()
        for component in slide.components:
            if component.component_type == "VocabularyFlipCard":
                for item in component.data.get("items", []):
                    word = str(item.get("word", ""))
                    if word and word not in known and word not in introduced:
                        slide_new_words.add(word)
                        introduced.add(word)

        if len(slide_new_words) > learner.new_word_limit_per_slide:
            msg = f"{label} 新词数 {len(slide_new_words)} 超过限制 {learner.new_word_limit_per_slide}"
            report.new_word_violations.append(msg)
            (report.blocking if learner.level == "zero_beginner" else report.warnings).append(msg)

        if learner.level == "zero_beginner" and learner.classroom_instruction_policy == "scaffold_first":
            instruction_types = {
                "instruction", "directions", "prompt", "teacher_instruction", "coach_note",
                "rubric", "success_criteria", "reflection", "performance_task", "explanation",
            }
            for block in slide.content_blocks:
                if block.block_type not in instruction_types or not block.text.strip():
                    continue
                allowed, _ = check_scaffold_language(block.text, learner.scaffold_language)
                if not allowed:
                    msg = f"{label} 零基础学习者指示词/解释未使用中介语 {learner.scaffold_language}"
                    report.target_scaffold_mixing.append(msg)
                    report.blocking.append(msg)

            for component in slide.components:
                for key in ("hint", "instruction", "directions", "prompt", "feedback_correct", "feedback_wrong"):
                    value = component.data.get(key)
                    if not isinstance(value, str) or not value.strip():
                        continue
                    allowed, _ = check_scaffold_language(value, learner.scaffold_language)
                    if not allowed:
                        msg = f"{label} 互动组件 {key} 未使用中介语 {learner.scaffold_language}"
                        report.target_scaffold_mixing.append(msg)
                        report.blocking.append(msg)

        # Check for scaffold meaning
        for component in slide.components:
            if component.component_type == "VocabularyFlipCard":
                for item in component.data.get("items", []):
                    word = str(item.get("word", ""))
                    meaning = str(item.get("meaning", ""))
                    if learner.require_scaffold_meaning and not meaning.strip():
                        msg = f"{label} 词汇 '{word}' 缺少支架释义"
                        report.missing_meaning.append(msg)
                        if learner.level in ("zero_beginner", "beginner"):
                            report.blocking.append(msg)

        # Check example sentences for unknown words
        for component in slide.components:
            if component.component_type == "VocabularyFlipCard":
                for item in component.data.get("items", []):
                    word = str(item.get("word", ""))
                    example = str(item.get("example", ""))
                    if example:
                        example_words = NEW_WORD_PATTERN.findall(example)
                        unknown = [w for w in example_words if w not in known and w != word and w not in introduced and w not in KNOWN_FUNCTIONAL and len(w) <= 4]
                        # Check "我会说" template
                        if "我会说" in example and "我" not in known and "会" not in known:
                            msg = f"{label} 例句“{example}”使用“我会说”模板，“我/会/说”尚未教授"
                            report.unknown_example_words.append(msg)
                            report.blocking.append(msg)
                            break

        # Check usage context
        if learner.require_usage_scene:
            for component in slide.components:
                if component.component_type == "VocabularyFlipCard":
                    for item in component.data.get("items", []):
                        word = str(item.get("word", ""))
                        if word in item_by_form and not item_by_form[word].usage_context:
                            msg = f"{label} 词汇 '{word}' 缺少使用场景"
                            report.missing_usage_context.append(msg)
                            (report.blocking if learner.level == "zero_beginner" else report.warnings).append(msg)

    if learner.level == "zero_beginner" and len(introduced) > learner.new_word_limit_per_lesson:
        msg = f"全课新词数 {len(introduced)} 超过限制 {learner.new_word_limit_per_lesson}"
        report.new_word_violations.append(msg)
        report.blocking.append(msg)

    if learner.level == "zero_beginner" and source is not None:
        source_text = "\n".join(
            text
            for page in source.pages
            for text in [page.title, *(block.text for block in page.text_blocks)]
        )
        blueprint_text = json.dumps(blueprint.model_dump(mode="json"), ensure_ascii=False)
        required_concepts = {
            "声母": ("声母",),
            "韵母": ("韵母",),
            "声调": ("声调",),
            "声调位置": ("声调位置", "标调", "tone-mark placement", "tone position"),
            "轻声": ("轻声", "neutral tone"),
            "变调": ("变调", "tone change", "tone sandhi"),
        }
        missing = [
            concept
            for concept, accepted_labels in required_concepts.items()
            if concept in source_text and not any(label in blueprint_text.lower() for label in accepted_labels)
        ]
        if missing:
            msg = f"零基础课件缺少教材拼音教学覆盖：{', '.join(missing)}"
            report.blocking.append(msg)

    # Meta labels in classroom content
    meta_labels = ["生词卡", "词卡", "互动组件", "组件"]
    for slide in blueprint.slides:
        for comp in slide.components:
            if comp.title in meta_labels:
                report.meta_labels_exposed.append(f"第 {slide.id} 页 组件标题 '{comp.title}' 不应展示给学生")

    # Derive state
    if report.blocking:
        report.state = "blocked"
    elif report.warnings:
        report.state = "warning"
    else:
        report.state = "pass"

    if not report.suggestions:
        report.suggestions.append("检查词汇释义、例句和引入顺序是否符合学习者水平。")
    return report
