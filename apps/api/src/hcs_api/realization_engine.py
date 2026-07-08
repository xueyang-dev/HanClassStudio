"""Pedagogical Realization Layer — transform teaching intent into learner-facing content."""

from __future__ import annotations

from .models import (
    ActivityPolicy, LearnerFacingBlock, LearnerLevel, LessonBlueprint, LessonSlide,
    PedagogicalIntent, PedagogicalIntentKind, PedagogicalActivityType,
    PresentationPlan, RealizationReport, SlideRealization, TeacherFacingBlock,
    ZB_FORBIDDEN_ACTIVITIES, ZB_FORBIDDEN_LABELS,
)


def build_presentation_plan(blueprint: LessonBlueprint, level: LearnerLevel = "zero_beginner") -> PresentationPlan:
    """Analyze blueprint slides and determine learner-facing presentation per intent."""
    plan = PresentationPlan(level=level)
    policy = ActivityPolicy(level=level)

    for slide in blueprint.slides:
        intent = _detect_intent(slide)
        realization = _realize_slide(slide, intent, level, policy)
        plan.realizations.append(realization)

    return plan


def _detect_intent(slide: LessonSlide) -> PedagogicalIntentKind:
    title = slide.title or ""
    if slide.slide_type == "VocabularySlide":
        return "introduce_vocabulary"
    if "礼貌" in title or "对比" in title or "你 vs" in title or "您" in title:
        return "introduce_polite_vs_neutral_form"
    if slide.slide_type == "DialogueSlide":
        return "guided_dialogue"
    if "listen" in slide.slide_type.lower() or "听" in title:
        return "listening_check"
    if "match" in slide.slide_type.lower() or "连" in title:
        return "scene_match"
    if slide.slide_type == "PracticeSlide":
        return "simple_recall"
    if slide.slide_type == "SummarySlide":
        return "simple_recall"
    return "introduce_vocabulary"


def _realize_slide(slide: LessonSlide, intent: PedagogicalIntentKind, level: LearnerLevel, policy: ActivityPolicy) -> SlideRealization:
    """Map pedagogical intent to learner-facing realization."""
    is_zb = level in ("zero_beginner",)
    meta_labels = [lb for lb in policy.forbidden_labels if lb in (slide.title or "")]
    blocked = bool(meta_labels)

    if is_zb and intent == "introduce_polite_vs_neutral_form":
        return _realize_politeness_zb(slide, meta_labels)
    if is_zb and intent == "guided_dialogue":
        return _realize_dialogue_zb(slide, meta_labels)
    if is_zb and intent in ("simple_recall", "scene_match"):
        return _realize_practice_zb(slide, meta_labels)

    # Default: use safe learner title
    learner_title = _zb_safe_title(slide.title or "", is_zb)
    blocks = [
        LearnerFacingBlock(target_text=b.text if i == 0 else b.text, scaffold_text=b.scaffolding_text)
        for i, b in enumerate(slide.content_blocks[:2])
    ]
    return SlideRealization(
        slide_id=slide.id, intent=intent, learner_title=learner_title,
        activity_type=_safe_activity_type(slide, policy),
        learner_visible_blocks=blocks, meta_labels_detected=meta_labels, blocked=blocked,
    )


def _realize_politeness_zb(slide: LessonSlide, meta: list[str]) -> SlideRealization:
    """Politeness contrast as scene-based choose activity for zero_beginner."""
    return SlideRealization(
        slide_id=slide.id, intent="introduce_polite_vs_neutral_form",
        learner_title="", activity_type="scene_choose",
        learner_visible_blocks=[
            LearnerFacingBlock(target_text="", scaffold_text="Choose the polite greeting for a teacher.",
                               visual_cue="scene_student_teacher", audio_key="politeness_1"),
            LearnerFacingBlock(target_text="你好！", scaffold_text="for a friend"),
            LearnerFacingBlock(target_text="您好！", scaffold_text="for a teacher"),
        ],
        teacher_only_blocks=[TeacherFacingBlock(intent="politeness_contrast",
                              title="礼貌对比：你 vs 您", instruction="Teacher: explain 你 vs 您")],
        meta_labels_detected=meta, blocked=bool(meta),
    )


def _realize_dialogue_zb(slide: LessonSlide, meta: list[str]) -> SlideRealization:
    texts = [b.text for b in slide.content_blocks[:2] if b.text]
    return SlideRealization(
        slide_id=slide.id, intent="guided_dialogue", learner_title="", activity_type="listen_choose",
        learner_visible_blocks=[LearnerFacingBlock(target_text=t or "你好！", audio_key="dialogue_1") for t in texts[:2]],
        teacher_only_blocks=[TeacherFacingBlock(intent="guided_dialogue", title=slide.title or "对话练习")],
        meta_labels_detected=meta, blocked=bool(meta),
    )


def _realize_practice_zb(slide: LessonSlide, meta: list[str]) -> SlideRealization:
    return SlideRealization(
        slide_id=slide.id, intent="simple_recall", learner_title="", activity_type="choose",
        learner_visible_blocks=[LearnerFacingBlock(target_text=slide.title or "", scaffold_text="")],
        meta_labels_detected=meta,
    )


def _zb_safe_title(title: str, is_zb: bool) -> str:
    if not is_zb:
        return title
    # Remove all forbidden labels from title
    for lb in ZB_FORBIDDEN_LABELS:
        title = title.replace(lb, "")
    title = title.strip()
    return title if title else ""


def _safe_activity_type(slide: LessonSlide, policy: ActivityPolicy) -> str:
    for c in slide.components:
        ct = c.component_type
        if ct == "VocabularyFlipCard":
            return "choose"
        if ct == "ListenAndChoose":
            return "listen_choose"
        if ct == "MatchGame":
            return "scene_match_game"
        if ct == "SentenceDragBuilder":
            return "choose" if "drag" in policy.forbidden_activities else "drag_sentence"
    return "choose"


def check_realization(blueprint: LessonBlueprint, level: LearnerLevel = "zero_beginner") -> RealizationReport:
    """Check blueprint for meta labels and forbidden activities in learner-facing content."""
    report = RealizationReport()
    policy = ActivityPolicy(level=level)

    for slide in blueprint.slides:
        title = slide.title or ""
        for label in policy.forbidden_labels:
            if label in title:
                report.meta_labels_exposed.append(f"第{slide.id}页标题含'{label}'")
                report.blocked.append(f"第{slide.id}页: 标签'{label}'不应展示给学生")
        
        for comp in slide.components:
            ct = comp.component_type
            if level in ("zero_beginner",) and ct == "SentenceDragBuilder":
                report.forbidden_activities.append(f"第{slide.id}页: 活动'{ct}'对{level}禁止")
                msg = f"第{slide.id}页: SentenceDragBuilder 不适合 {level}"
                report.blocked.append(msg)

        for block in slide.content_blocks:
            for label in policy.forbidden_labels:
                if label in (block.text or ""):
                    report.meta_labels_exposed.append(f"第{slide.id}页内容含'{label}'")
                    report.blocked.append(f"第{slide.id}页: 内容含标签'{label}'")

    if not report.blocked and not report.forbidden_activities:
        report.state = "pass"
        report.passed.append(f"所有幻灯片通过 pedagogical realization 检查 (level={level})")
    elif not report.blocked:
        report.state = "warning"
    else:
        report.state = "blocked"

    return report
