"""Syllabus-Aware Comprehensible Input Engine."""

from __future__ import annotations

import re
from typing import Any

from .models import (
    AllowedSlideText,
    AllowedTextPlan,
    DifficultyProfile,
    LanguageInventory,
    LearnerLevel,
    LearnerModel,
    LessonBlueprint,
    LessonProfile,
    OffLevelItem,
    OffLevelReport,
    SourceLessonProfile,
    SourceMaterial,
    StandardScheme,
)


# Phrases that zero_beginner should not see as target-language text
ZERO_BEGINNER_FORBIDDEN = {
    "我会说", "我会读", "我会写", "朋友之间", "同学之间",
    "老师之间", "家人之间", "熟悉的人", "不熟悉的人",
    "敬称", "谦称", "礼貌用语", "正式场合", "非正式场合",
    "口语", "书面语",
}


def build_source_lesson_profile(source: SourceMaterial) -> SourceLessonProfile:
    """Extract structured units from source material."""
    all_text = _source_text(source)
    pages_text = "\n".join(p.title + "\n" + " ".join(b.text for b in p.text_blocks) for p in source.pages)

    profile = SourceLessonProfile(
        source_title=source.original_filename,
        lesson_topic=_extract_topic(source),
    )

    # Dialogue detection
    for m in re.finditer(r"[A-Za-z\u4e00-\u9fff][：:]\s*(.*?)(?=[A-Za-z\u4e00-\u9fff][：:]|\Z)", all_text, re.DOTALL):
        line = m.group(1).strip()
        if line and len(line) <= 100:
            profile.dialogue_units.append(line)

    # Vocabulary units: words with pinyin or translation nearby (handle parentheses too)
    for m in re.finditer(r"[\u4e00-\u9fff]{1,4}[\s（(]*[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+", all_text):
        profile.vocabulary_units.append(m.group().strip())

    # Grammar units: pattern-like text
    grammar_signals = ["语法", "句型", "知识点", "Grammar", "Pattern", "在.*呢", "了", "喜欢", "是", "有"]
    for signal in grammar_signals:
        if re.search(signal, all_text, re.UNICODE):
            profile.grammar_units.append(signal)

    # Exercise units
    exercise_signals = ["练习", "Exercise", "读一读", "写一写", "听一听", "说一说", "选一选", "连一连"]
    ex_found = set()
    for line in all_text.split("\n"):
        for sig in exercise_signals:
            if sig in line and sig not in ex_found:
                profile.exercise_units.append(line.strip()[:80])
                ex_found.add(sig)

    # Teacher instruction units
    for line in all_text.split("\n"):
        if any(kw in line for kw in ["Listen", "Read", "Write", "Say", "跟着", "跟你的", "请"]):
            profile.teacher_instruction_units.append(line.strip()[:80])

    # Visible text units: all non-noise text blocks
    for page in source.pages:
        for block in page.text_blocks:
            txt = block.text.strip()
            if txt and len(txt) > 1:
                profile.visible_text_units.append(txt[:120])

    return profile


def build_difficulty_profile(source: SourceMaterial, profile: LessonProfile, source_lesson: SourceLessonProfile) -> DifficultyProfile:
    """Infer difficulty level from source content."""
    from .learner_comprehension import resolve_profile_learner_level

    confirmed_level = resolve_profile_learner_level(profile)
    if confirmed_level == "zero_beginner":
        return DifficultyProfile(
            estimated_level="zero_beginner",
            standard_scheme="HSK",
            standard_level="Pre-HSK / HSK1",
            evidence=["confirmed learner profile: zero_beginner"],
            confidence=1.0,
            source_scope_notes="Teacher-confirmed zero-beginner level overrides textbook explanation density.",
        )

    all_text = _source_text(source).lower()
    evidence: list[str] = []
    confidence = 0.5

    # Check for greeting/hello signals
    greeting_signals = ["你好", "您好", "hello", "greeting", "打招呼", "第1课"]
    greeting_hits = sum(1 for s in greeting_signals if s in all_text)

    # Check for pinyin/spelling aids
    has_pinyin = bool(re.search(r"[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+", all_text))

    # Check complexity
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", all_text)
    unique_chars = len(set(chinese_chars))

    if greeting_hits >= 2 and has_pinyin and unique_chars <= 15:
        evidence.append(f"问候/问候+拼音+不重复汉字≤15 ({unique_chars})")
        confidence = 0.9
        return DifficultyProfile(
            estimated_level="zero_beginner", standard_scheme="HSK", standard_level="HSK1",
            evidence=evidence, confidence=confidence,
            source_scope_notes="Source appears to be a first lesson with pinyin support and limited characters.",
        )
    if greeting_hits >= 1 and has_pinyin and unique_chars <= 30:
        evidence.append(f"含问候信号+拼音+不重复汉字≤30 ({unique_chars})")
        confidence = 0.7
        return DifficultyProfile(
            estimated_level="beginner", standard_scheme="HSK", standard_level="HSK1",
            evidence=evidence, confidence=confidence,
            source_scope_notes="Source contains beginner-level content with pinyin.",
        )

    evidence.append(f"默认推定：问候信号={greeting_hits}, 不重复汉字={unique_chars}")
    return DifficultyProfile(
        estimated_level="beginner", standard_scheme="HSK", standard_level="HSK1",
        evidence=evidence, confidence=confidence,
    )


def build_language_inventory(
    source_lesson: SourceLessonProfile,
    difficulty: DifficultyProfile,
    learner: LearnerModel,
) -> LanguageInventory:
    """Classify items into known, target, support, off-level, teacher-only, excluded."""
    inv = LanguageInventory()
    inv.known_items = list(learner.known_words)

    vocab_words = []
    for v in source_lesson.vocabulary_units:
        words = re.findall(r"[\u4e00-\u9fff]{1,4}", v)
        vocab_words.extend(words)

    # Lesson target items: from vocabulary units in source
    for w in vocab_words:
        if w not in inv.known_items and len(w) >= 1:
            inv.lesson_target_items.append(w)

    # Teacher-only: instruction units
    for u in source_lesson.teacher_instruction_units:
        words = re.findall(r"[\u4e00-\u9fff]{1,4}", u)
        for w in words:
            if w not in inv.known_items and w not in inv.lesson_target_items:
                inv.teacher_only_items.append(w)

    # Off-level: if estimated level is zero_beginner, mark non-HSK1 or complex items
    if difficulty.estimated_level in ("zero_beginner", "beginner"):
        for w in inv.lesson_target_items[:]:
            if len(w) > 2:
                inv.off_level_items.append(w)
                inv.lesson_target_items.remove(w)

    # Excluded: noise or meta items
    meta = {"第", "课", "学习", "目标", "练习", "复习", "生词"}
    inv.excluded_items = [w for w in inv.lesson_target_items[:] if w in meta]
    inv.lesson_target_items = [w for w in inv.lesson_target_items if w not in meta]

    # Deduplicate
    inv.lesson_target_items = list(dict.fromkeys(inv.lesson_target_items))
    inv.teacher_only_items = list(dict.fromkeys(inv.teacher_only_items))
    inv.off_level_items = list(dict.fromkeys(inv.off_level_items))

    return inv


def build_allowed_text_plan(
    blueprint: LessonBlueprint,
    inventory: LanguageInventory,
    difficulty: DifficultyProfile,
) -> AllowedTextPlan:
    """Build per-slide allowed text plan based on learner level."""
    plan = AllowedTextPlan()
    is_zb = difficulty.estimated_level in ("zero_beginner",)
    max_new = 1 if is_zb else 2

    for slide in blueprint.slides:
        atp = AllowedSlideText(slide_id=slide.id, max_new_items=max_new)
        # Collect target items introduced on this slide
        seen_on_slide: set[str] = set()
        for comp in slide.components:
            if comp.component_type == "VocabularyFlipCard":
                for item in comp.data.get("items", []):
                    word = str(item.get("word", ""))
                    if word:
                        atp.allowed_target_text.append(word)
                        seen_on_slide.add(word)
        atp.allowed_target_text = list(dict.fromkeys(atp.allowed_target_text))

        # Forbidden: ZERO_BEGINNER_FORBIDDEN for zero_beginner
        if is_zb:
            atp.forbidden_target_text = list(ZERO_BEGINNER_FORBIDDEN)
            # Also forbid teacher-only items
            for t in inventory.teacher_only_items:
                if t not in atp.forbidden_target_text:
                    atp.forbidden_target_text.append(t)

        # Teacher-only text
        for t in inventory.teacher_only_items:
            if t not in atp.teacher_only_text:
                atp.teacher_only_text.append(t)

        plan.slides.append(atp)

    return plan


def is_allowed_learner_text(text: str, slide_plan: AllowedSlideText, difficulty: DifficultyProfile) -> tuple[bool, str]:
    """Check if text is allowed for learner-facing display on a given slide."""
    for forbidden in slide_plan.forbidden_target_text:
        if forbidden in text:
            return False, f"Contains forbidden text: '{forbidden}'"
    if difficulty.estimated_level in ("zero_beginner",):
        # Check no "我会说" template
        if "我会说" in text or "我会读" in text or "我会写" in text:
            return False, "Zero_beginner should not see '我会X' templates"
    return True, ""


def check_off_level(
    blueprint: LessonBlueprint,
    plan: AllowedTextPlan,
    inventory: LanguageInventory,
    difficulty: DifficultyProfile,
) -> OffLevelReport:
    """Check final blueprint for off-level items."""
    report = OffLevelReport()
    slide_plans = {sp.slide_id: sp for sp in plan.slides}
    known = set(inventory.known_items)
    target = set(inventory.lesson_target_items)

    for slide in blueprint.slides:
        sp = slide_plans.get(slide.id)
        label = f"第 {slide.id} 页"
        slide_words: set[str] = set()

        for comp in slide.components:
            if comp.component_type == "VocabularyFlipCard":
                for item in comp.data.get("items", []):
                    word = str(item.get("word", ""))
                    if not word:
                        continue
                    slide_words.add(word)

                    # Unknown target item
                    if word not in known and word not in target:
                        report.unknown_target_items.append(OffLevelItem(
                            text=word, location=label, reason="Not in known or target items", severity="blocked"
                        ))
                        report.blocking.append(f"{label}: '{word}' 不属于已知或目标词汇")

                    # Check forbidden text
                    if sp:
                        allowed, reason = is_allowed_learner_text(word, sp, difficulty)
                        if not allowed:
                            report.teacher_text_leaks.append(OffLevelItem(
                                text=word, location=label, reason=reason, severity="blocked"
                            ))
                            report.blocking.append(f"{label}: {reason}")

            # Check component titles and hints
            if comp.title and sp:
                allowed, reason = is_allowed_learner_text(comp.title, sp, difficulty)
                if not allowed:
                    report.teacher_text_leaks.append(OffLevelItem(
                        text=comp.title, location=label, reason=reason, severity="warning"
                    ))
                    report.warnings.append(f"{label} 组件标题 '{comp.title}': {reason}")

            # Check for meta language exposure
            for meta in ("生词卡", "词卡", "组件"):
                if meta in (comp.title or ""):
                    report.teacher_text_leaks.append(OffLevelItem(
                        text=comp.title, location=label, reason=f"元标签 {meta} 不应暴露给学生",
                        severity="blocked"
                    ))
                    report.blocking.append(f"{label}: 元标签 '{meta}' 暴露")

        # Check new word count
        new_on_slide = len(slide_words - known)
        if sp and new_on_slide > sp.max_new_items:
            report.unsupported_new_items.append(OffLevelItem(
                text=str(slide_words), location=label,
                reason=f"新词数 {new_on_slide} 超过限制 {sp.max_new_items}",
                severity="warning"
            ))
            report.warnings.append(f"{label}: 新词数 {new_on_slide} 超限 {sp.max_new_items}")

    if report.blocking:
        report.state = "blocked"
    elif report.warnings:
        report.state = "warning"
    if not report.suggestions:
        report.suggestions.append("检查词汇是否在已知/目标范围内，排除禁止文本。")
    return report


def _source_text(source: SourceMaterial) -> str:
    chunks: list[str] = []
    for page in source.pages:
        chunks.append(page.title)
        chunks.append(page.content_text())
        if page.notes:
            chunks.append(page.notes)
    return "\n".join(chunk for chunk in chunks if chunk)


def _extract_topic(source: SourceMaterial) -> str:
    for page in source.pages:
        if page.title.strip():
            return page.title.strip()
    return source.original_filename.rsplit(".", 1)[0] or "unknown"
