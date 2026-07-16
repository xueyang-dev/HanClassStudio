"""Traditional PPTX Deck Plan — pedagogical intent → structured slide composition."""

from __future__ import annotations

from typing import Any

from .content_contract import is_allowed_learner_text, load_language_profile, resolve_scaffold_text, resolve_scaffold_usage
from .models import (
    LessonBlueprint,
    LessonSlide,
    PresentationBindingPlan,
    PptxDeckPlan,
    PptxDeckSlide,
    TraditionalLayout,
)


def build_pptx_deck_plan(
    blueprint: LessonBlueprint,
    target_language: str = "Chinese",
    scaffold_language: str = "English",
    learner_level: str = "zero_beginner",
    language_items: list | None = None,
    evidence_plan: Any | None = None,
    activity_plan: Any | None = None,
    state_plan: Any | None = None,
    activity_bindings: PresentationBindingPlan | None = None,
) -> PptxDeckPlan:
    """Build a traditional PPTX deck plan from a lesson blueprint."""
    plan = PptxDeckPlan(
        target_language=target_language,
        scaffold_language=scaffold_language,
        learner_level=learner_level,
    )
    item_lookup = {li.target_form: li for li in (language_items or [])}

    for slide in blueprint.slides:
        deck_slide = _map_slide_to_deck(slide, scaffold_language, learner_level, item_lookup)
        plan.slides.append(deck_slide)

    if activity_bindings:
        _apply_bindings_to_deck(plan, activity_bindings, evidence_plan)

    return plan


def _apply_bindings_to_deck(plan: PptxDeckPlan, activity_bindings: PresentationBindingPlan, evidence_plan: Any | None) -> None:
    ev_map: dict[str, Any] = {ev.evidence_id: ev for ev in (evidence_plan.evidence_specs if evidence_plan else [])}
    bindings_by_slide = {}
    for binding in sorted(activity_bindings.bindings, key=lambda b: b.binding_id):
        if "pptx_classroom" in binding.presentation_modes or "speaker_notes" in binding.presentation_modes:
            bindings_by_slide.setdefault(binding.slide_id, []).append(binding)

    for deck in plan.slides:
        bindings = bindings_by_slide.get(deck.slide_id, [])
        if not bindings:
            continue
        # Defensive path only: binding_quality_report blocks duplicate targets before export.
        binding = bindings[0]
        ev = ev_map.get(binding.evidence_id)
        deck.binding_id = binding.binding_id
        deck.activity_id = binding.activity_id
        deck.evidence_id = binding.evidence_id
        if ev:
            deck.evidence_claim = ev.learning_claim
            deck.expected_behavior = ev.expected_behavior
            deck.failure_action = ev.failure_action
        deck.speaker_notes.append(f"Binding: {binding.binding_id}")
        deck.speaker_notes.append(f"Activity: {binding.activity_id}")
        deck.speaker_notes.append(f"Evidence: {binding.evidence_id}")
        if ev:
            deck.speaker_notes.append(f"Claim: {ev.learning_claim}")
            deck.speaker_notes.append(f"Pass: {ev.pass_criteria.get('min_correct', 1)}/{ev.pass_criteria.get('attempts_allowed', 2)}")
            if ev.failure_action:
                fa = ev.failure_action
                deck.speaker_notes.append(f"Fail: {fa.get('remediation_type','')} -> {fa.get('recommended_activity','')}")


def _map_slide_to_deck(
    slide: LessonSlide,
    scaffold_lang: str,
    level: str,
    item_lookup: dict,
) -> PptxDeckSlide:
    is_zb = level in ("zero_beginner",)
    st = slide.slide_type
    title = slide.title or ""
    notes: list[str] = []

    # Default: generic content
    deck = PptxDeckSlide(slide_id=slide.id, slide_purpose=st, traditional_layout="generic_content")
    deck.image_key = slide.media_requirements.image_key or ""
    deck.audio_key = slide.media_requirements.audio_key or ""
    deck.teacher_notes.append(f"Slide type: {st}")
    deck.teacher_notes.append(f"Teacher instruction: present {title}")

    if st == "CoverSlide":
        deck.traditional_layout = "cover_title"
        deck.main_focus = title
        deck.target_text = title
        deck.visual_hint = "course cover"
        deck.teacher_notes = ["Welcome students. Introduce today's topic."]
        deck.speaker_notes = [f"Today we will learn: {title}"]

    elif st == "ObjectiveSlide":
        deck.traditional_layout = "objectives_cards"
        deck.main_focus = "学习目标"
        objectives = [b.text for b in slide.content_blocks[:4] if b.text]
        deck.target_text = "\n".join(objectives)
        deck.teacher_notes = ["Show lesson objectives. Explain what students will achieve."]
        deck.speaker_notes = [f"By the end of this lesson, you will be able to:"] + objectives

    elif st == "VocabularySlide":
        items = []
        for c in slide.components:
            for item in c.data.get("items", []):
                items.append(item)
        if is_zb and len(items) == 1:
            deck.traditional_layout = "single_item_focus"
            item = items[0]
            deck.main_focus = item.get("word", "")
            deck.target_text = item.get("word", "")
            deck.pronunciation = item.get("pinyin", "")
            deck.scaffold_text = resolve_scaffold_text(item.get("word", ""), scaffold_lang, None, item_lookup)
            deck.usage_context = item.get("usage_context", "")
            deck.visual_hint = "vocabulary focus"
            deck.teacher_notes = [
                "Present the word with audio.",
                "Show pronunciation.",
                "Give scaffold meaning.",
                f"Usage: {deck.usage_context}",
            ]
            deck.speaker_notes = [
                f"Target: {deck.target_text}",
                f"Pronunciation: {deck.pronunciation}",
                f"Meaning: {deck.scaffold_text}",
            ]
        else:
            deck.traditional_layout = "single_item_focus"
            if items:
                deck.main_focus = items[0].get("word", "")
                deck.target_text = items[0].get("word", "")
                deck.pronunciation = items[0].get("pinyin", "")
                deck.scaffold_text = resolve_scaffold_text(items[0].get("word", ""), scaffold_lang, None, item_lookup)
            deck.teacher_notes = [f"Vocabulary slide: {len(items)} item(s)"]

    elif st == "GrammarPatternSlide":
        deck.traditional_layout = "two_card_contrast"
        deck.main_focus = "你 vs 您"
        deck.target_text = "你好！ / 您好！"
        deck.pronunciation = "nǐ hǎo / nín hǎo"
        deck.scaffold_text = resolve_scaffold_text("您", scaffold_lang, None, item_lookup)
        # Usage context in scaffold language only
        deck.usage_context = resolve_scaffold_usage("你", scaffold_lang, None, item_lookup)
        deck.teacher_notes = [
            "你 for friends/peers. 您 for teachers/elders.",
            "Left card = 你好 (friend), Right card = 您好 (teacher)",
            f"Scaffold: {deck.scaffold_text}",
            f"Usage: {deck.usage_context}",
        ]
        deck.speaker_notes = [
            "Use 你 with friends and classmates.",
            "Use 您 with teachers and elders.",
            "Practice: greet your classmate vs greet your teacher.",
        ]
        deck.visual_hint = "two_scene_contrast"

    elif st == "DialogueSlide":
        deck.traditional_layout = "two_card_contrast" if "contrast" in slide.layout_variant else "dialogue_bubbles"
        texts = [b.text for b in slide.content_blocks[:4] if b.text]
        deck.main_focus = texts[0] if texts else "对话"
        deck.target_text = "\n".join(texts)
        deck.teacher_notes = ["Play audio. Students listen and repeat.", "Practice with a partner."]
        deck.speaker_notes = ["Listen to the dialogue, then practice with your classmate."]

    elif st == "PracticeSlide":
        component_types = {component.component_type for component in slide.components}
        deck.traditional_layout = "listen_choose" if "ListenAndChoose" in component_types else "match_pairs"
        pairs = []
        for c in slide.components:
            for p in c.data.get("pairs", []):
                pairs.append(f"{p.get('left','')} ↔ {p.get('right','')}")
        deck.main_focus = title
        deck.target_text = "\n".join(pairs[:6])
        deck.teacher_notes = ["Matching activity.", "Answer key is in speaker notes."]
        deck.speaker_notes = ["Answers:"] + pairs
        deck.visual_hint = "match_pairs"

    elif st == "SummarySlide":
        deck.traditional_layout = "summary_cards"
        summaries = [b.text for b in slide.content_blocks if b.text]
        deck.main_focus = "课堂小结"
        deck.target_text = "\n".join(summaries)
        deck.teacher_notes = ["Review key points.", "Encourage students to share what they learned."]
        deck.speaker_notes = ["Let's review what we learned today."]

    return deck


def build_pptx_structure_report(plan: PptxDeckPlan) -> dict:
    """Build PPTX structure quality report."""
    report = {
        "state": "pass",
        "component_label_leak": [],
        "teacher_text_leak": [],
        "answer_visible_on_slide": [],
        "missing_traditional_layout": [],
        "tiny_main_content": [],
        "empty_placeholder_block": [],
        "scaffold_language_mismatch": [],
        "blocked": [],
        "warnings": [],
        "passed": [],
    }
    for slide in plan.slides:
        # Check for forbidden labels in main_focus
        allowed, reason = is_allowed_learner_text(slide.target_text, "target", "zero_beginner")
        if not allowed:
            report["teacher_text_leak"].append(f"S{slide.slide_id}: '{slide.target_text}' - {reason}")
            report["warnings"].append(f"S{slide.slide_id}: {reason}")
        # Check layout is assigned
        if slide.traditional_layout == "generic_content":
            report["missing_traditional_layout"].append(f"S{slide.slide_id}: no specific layout")
        # Check main_focus exists
        if not slide.main_focus:
            report["tiny_main_content"].append(f"S{slide.slide_id}: no main_focus")
        if slide.traditional_layout == "summary_cards":
            for item in slide.target_text.splitlines():
                if len(item.strip()) > 32:
                    report["blocked"].append(
                        f"S{slide.slide_id}: summary card text exceeds the 32-character layout budget"
                    )
                    break
        if slide.traditional_layout == "objectives_cards":
            for item in slide.target_text.splitlines():
                if len(item.strip()) > 60:
                    report["blocked"].append(
                        f"S{slide.slide_id}: objective card text exceeds the 60-character layout budget"
                    )
                    break
    if report["blocked"]:
        report["state"] = "blocked"
    if report["warnings"]:
        report["state"] = "blocked" if report["blocked"] else "warning"
    if not report["warnings"] and not report["blocked"]:
        report["passed"].append("All slides pass PPTX structure check")
    return report
