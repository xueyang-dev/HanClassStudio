"""Slide Canvas Plan — blueprint + intent → structured slide composition."""

from __future__ import annotations

from .models import (
    CanvasBlock, LayoutTemplate, LessonBlueprint, LessonSlide, SlideCanvas, SlideCanvasPlan,
)


def build_slide_canvas_plan(blueprint: LessonBlueprint, level: str = "zero_beginner") -> SlideCanvasPlan:
    """Build slide canvas plan from lesson blueprint."""
    plan = SlideCanvasPlan()
    for slide in blueprint.slides:
        canvas = _map_slide_to_canvas(slide, level)
        plan.slides.append(canvas)
    return plan


def _map_slide_to_canvas(slide: LessonSlide, level: str) -> SlideCanvas:
    is_zb = level in ("zero_beginner",)
    blocks: list[CanvasBlock] = []
    notes: list[str] = []
    template: LayoutTemplate = "title_focus"
    visual = "none"
    role = "vocabulary"

    st = slide.slide_type

    if st == "CoverSlide":
        template = "simple_cover"
        role = "cover"
        blocks.append(CanvasBlock(role="hero", text=slide.title or "", position="center"))
        visual = "geometric"

    elif st == "ObjectiveSlide":
        template = "objectives_list"
        role = "objectives"
        for b in slide.content_blocks[:3]:
            blocks.append(CanvasBlock(role="subtitle", text=b.text[:30], position="top"))
        visual = "none"

    elif st == "VocabularySlide":
        role = "vocabulary"
        items = []
        for c in slide.components:
            for item in c.data.get("items", []):
                items.append(item)
        if is_zb and len(items) == 1:
            template = "single_word_focus"
            word = items[0]["word"]
            pinyin = items[0].get("pinyin", "")
            meaning = items[0].get("meaning", "")
            blocks.append(CanvasBlock(role="hero", text=word, position="center"))
            if pinyin:
                blocks.append(CanvasBlock(role="pinyin", text=pinyin, position="bottom"))
            if meaning:
                blocks.append(CanvasBlock(role="meaning", text=meaning, position="bottom"))
            visual = "geometric"
        else:
            template = "title_focus"
            for item in items[:3]:
                blocks.append(CanvasBlock(role="hero", text=item.get("word", ""), position="center"))
            visual = "geometric"
        notes.append(f"Teacher: present {len(items)} vocabulary item(s)")

    elif st == "GrammarPatternSlide":
        if is_zb and ("你" in (slide.title or "") or "您" in (slide.title or "")):
            template = "two_scene_contrast"
            role = "grammar_contrast"
            blocks.append(CanvasBlock(role="hero", text="你好！", position="left", image_key="scene_friend"))
            blocks.append(CanvasBlock(role="hero", text="您好！", position="right", image_key="scene_teacher"))
            blocks.append(CanvasBlock(role="scaffold", text="Student → Student：你", position="bottom"))
            blocks.append(CanvasBlock(role="scaffold", text="Student → Teacher：您", position="bottom"))
            visual = "image"
            notes.append("Teacher: explain 你 vs 您 contrast using scenes")
        else:
            template = "title_focus"
            for b in slide.content_blocks[:2]:
                blocks.append(CanvasBlock(role="subtitle", text=b.text[:40], position="top"))
            notes.append("Teacher: grammar pattern explanation")

    elif st == "DialogueSlide":
        template = "dialogue_bubbles"
        role = "dialogue"
        for b in slide.content_blocks[:4]:
            blocks.append(CanvasBlock(role="hero", text=b.text[:30], position="center" if "A：" in b.text else "bottom"))
        visual = "audio"

    elif st == "PracticeSlide":
        template = "match_pairs" if "连" in (slide.title or "") else "listen_choose"
        role = "practice"
        for c in slide.components:
            pairs = c.data.get("pairs", [])
            for p in pairs[:4]:
                blocks.append(CanvasBlock(role="hero", text=f"{p.get('left','')} → {p.get('right','')}", position="center"))
            visual = "image"

    elif st == "SummarySlide":
        template = "summary_check"
        role = "review"
        for b in slide.content_blocks[:3]:
            blocks.append(CanvasBlock(role="subtitle", text=b.text[:30], position="top"))
        visual = "none"

    return SlideCanvas(
        slide_id=slide.id, layout_template=template, learner_level=level,
        slide_role=role, blocks=blocks, teacher_notes=notes, visual_support_mode=visual,
    )
