from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from .models import AssetManifest, LessonBlueprint, LessonProfile, QualityReport
from .storage import ensure_project, read_json, read_model, write_json


SUPPORTED_SLIDE_TYPES = {
    "CoverSlide",
    "ObjectiveSlide",
    "VocabularySlide",
    "GrammarPatternSlide",
    "ReadingSlide",
    "DialogueSlide",
    "PracticeSlide",
    "SummarySlide",
    "HomeworkSlide",
}

BG = RGBColor(248, 250, 247)
SURFACE = RGBColor(255, 255, 255)
INK = RGBColor(34, 50, 54)
MUTED = RGBColor(95, 115, 112)
TEAL = RGBColor(8, 126, 139)
MINT = RGBColor(221, 247, 229)
CORAL = RGBColor(242, 95, 92)
GOLD = RGBColor(247, 179, 43)
LINE = RGBColor(220, 232, 226)


import re as _re

PROVIDER_REQUIRED_PPTX = _re.compile(r"provider_required|\[Arabic\]|\[.*?\].*?provider_required")


def _clean_classroom_text(text: str) -> str:
    if PROVIDER_REQUIRED_PPTX.search(text):
        return ""
    return text


def export_editable_pptx(project_id: str, force: bool = False, export_mode: str = "debug") -> Path:
    root = ensure_project(project_id)
    blueprint = read_model(project_id, "lesson_blueprint.json", LessonBlueprint)
    if not blueprint:
        raise ValueError("Project needs blueprints/lesson_blueprint.json before editable PPTX export")

    report = read_model(project_id, "quality_report.json", QualityReport)
    if not report and not force:
        raise PermissionError("Run quality gate before editable PPTX export")
    if report and report.state == "blocked" and not force:
        raise PermissionError("Quality gate is blocked; pass force=true to export editable PPTX anyway")

    # Classroom mode: check classroom_quality gate
    is_classroom = export_mode == "classroom"
    if is_classroom:
        from .storage import read_model as _rm
        from .models import ClassroomQualityReport as _CQR
        cqr = _rm(project_id, "classroom_quality_report.json", _CQR)
        if cqr and cqr.state == "blocked" and not force:
            raise PermissionError("Classroom quality gate blocked this export; pass force=true to proceed")

    spec_lock = read_json(project_id, "specs/spec_lock.json") or {}
    interaction_plan = read_json(project_id, "blueprints/interaction_plan.json") or {}
    media_plan = read_json(project_id, "blueprints/media_plan.json") or {}
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest) or AssetManifest()

    # Build PPTX deck plan with kernel artifacts
    from .pptx_deck import build_pptx_deck_plan, build_pptx_structure_report
    from .storage import read_model as _rm, write_json as _wj, read_json as _rj
    from .models import LearnerModel as _LM
    profile = _rm(project_id, "lesson_profile.json", LessonProfile)
    level = getattr(profile, "learner_level", "zero_beginner") if profile else "zero_beginner"
    # Read kernel artifacts (use read_json for dicts, then construct models)
    ep_data = _rj(project_id, "learning/evidence_plan.json")
    ap_data = _rj(project_id, "learning/activity_plan.json")
    sp_data = _rj(project_id, "learning/learning_state_plan.json")
    from .models import EvidencePlan as _EP, ActivityPlan as _AP, LearningStatePlan as _LSP
    evidence_plan = _EP(**ep_data) if ep_data else None
    activity_plan = _AP(**ap_data) if ap_data else None
    state_plan = _LSP(**sp_data) if sp_data else None
    deck_plan = build_pptx_deck_plan(
        blueprint, "Chinese", profile.scaffolding_language if profile else "English",
        level or "zero_beginner",
        evidence_plan=evidence_plan, activity_plan=activity_plan, state_plan=state_plan,
    )
    _wj(project_id, "blueprints/pptx_deck_plan.json", deck_plan.model_dump(mode="json"))
    struct_report = build_pptx_structure_report(deck_plan)
    _wj(project_id, "quality/pptx_structure_report.json", struct_report)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    is_classroom = export_mode == "classroom"
    blank = prs.slide_layouts[6]
    for deck_slide in deck_plan.slides:
        _render_deck_slide(prs.slides.add_slide(blank), deck_slide, is_classroom)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    is_diagnostic = force and is_classroom
    prefix = "HanClassStudio_Diagnostic" if is_diagnostic else "HanClassStudio_Editable"
    export_path = root / "exports" / f"{prefix}_{timestamp}.pptx"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(export_path)

    quality_state = report.state if report else "warning"
    pptx_report = _build_pptx_quality_report(blueprint, report, force)
    write_json(project_id, "quality/pptx_quality_report.json", pptx_report)
    write_json(
        project_id,
        "exports/pptx_export_manifest.json",
        {
            "schema": "hanclassstudio.pptx_export_manifest.v1",
            "project_id": project_id,
            "filename": export_path.name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "export_type": "pptx_editable",
            "editable": True,
            "forced": force,
            "diagnostic": is_diagnostic,
            "quality_state": quality_state,
            "interaction_policy": "classroom_static_activity",
            "source_artifacts": {
                "spec_lock": bool(spec_lock),
                "interaction_plan": bool(interaction_plan),
                "media_plan": bool(media_plan),
                "asset_manifest": bool(manifest.model_dump(mode="json")),
            },
        },
    )
    return export_path


def _render_slide(slide, root: Path, slide_model, manifest: AssetManifest, is_classroom: bool = False) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = BG
    slide_type = slide_model.slide_type if slide_model.slide_type in SUPPORTED_SLIDE_TYPES else "GenericContentSlide"
    if not is_classroom:
        _add_label(slide, slide_type)
    if slide_type == "CoverSlide":
        _add_text(slide, slide_model.title, 0.8, 1.55, 7.6, 1.35, 42, bold=True, color=INK)
        _add_text(slide, _content_text(slide_model), 0.85, 3.05, 6.9, 1.2, 21, color=MUTED)
        _add_media_card(slide, root, slide_model, manifest, 8.4, 1.35, 4.1, 3.4, is_classroom)
    elif slide_type == "ObjectiveSlide":
        _add_title(slide, slide_model.title or "学习目标")
        objectives = [block.text for block in slide_model.content_blocks if block.text] or ["完成本课学习任务"]
        for index, text in enumerate(objectives[:4]):
            _add_card(slide, str(index + 1), text, 0.85 + (index % 2) * 6.05, 1.75 + (index // 2) * 1.85, 5.55, 1.45)
    else:
        _add_title(slide, slide_model.title or "课堂活动")
        _add_content_blocks(slide, slide_model)
        _add_media_card(slide, root, slide_model, manifest, 8.55, 1.25, 3.9, 2.35, is_classroom)

    y = 4.0 if slide_model.components else 6.55
    for component in slide_model.components[:3]:
        y = _render_component(slide, component, y)
    if not is_classroom:
        _add_footer(slide, "Editable PPTX export · HTML interactions are converted to classroom static activity pages")


def _render_component(slide, component, y: float) -> float:
    data = component.data or {}
    title = component.title or component.component_type
    if component.component_type == "AudioButton":
        _add_activity_box(slide, f"Audio · {title}", data.get("audio_text") or data.get("label") or "Audio prompt", 0.85, y, 3.7, 1.1, icon="Audio")
        return y + 1.25
    if component.component_type == "VocabularyFlipCard":
        items = _list(data.get("items"))[:4]
        if not items:
            _add_activity_box(slide, title, "Vocabulary cards need items.", 0.85, y, 5.0, 1.0)
            return y + 1.15
        for index, item in enumerate(items):
            x = 0.85 + index * 3.05
            body = "\n".join(
                part
                for part in [
                    item.get("word", ""),
                    item.get("pinyin", ""),
                    item.get("meaning", ""),
                    item.get("example", ""),
                ]
                if part
            )
            _add_activity_box(slide, title if index == 0 else "词卡", body, x, y, 2.75, 1.85)
        return y + 2.05
    if component.component_type == "SentenceDragBuilder":
        words = [str(word) for word in _list(data.get("words"))]
        answer = " ".join(str(word) for word in _list(data.get("answer")))
        _add_activity_box(slide, title, "排序词块: " + "  /  ".join(words), 0.85, y, 7.3, 1.05)
        _add_activity_box(slide, "答案提示", answer or "Teacher answer area", 8.45, y, 3.9, 1.05)
        return y + 1.25
    if component.component_type == "ListenAndChoose":
        choices = "\n".join(f"{i + 1}. {choice}" for i, choice in enumerate(_list(data.get("choices"))))
        body = "\n".join(part for part in [data.get("audio_text", ""), choices, f"Answer: {data.get('answer', '')}"] if part)
        _add_activity_box(slide, title, body or "Listen and choose activity", 0.85, y, 6.4, 1.55)
        return y + 1.75
    if component.component_type == "MatchGame":
        pairs = [pair for pair in _list(data.get("pairs")) if isinstance(pair, dict)]
        body = "\n".join(f"{pair.get('left', '')}   ⟷   {pair.get('right', '')}" for pair in pairs) or "Match pairs"
        _add_activity_box(slide, title, body, 0.85, y, 6.4, 1.55)
        return y + 1.75
    if component.component_type == "CharacterFormation":
        parts = " + ".join(str(part) for part in _list(data.get("parts")))
        character = str(data.get("character", "字"))
        body = f"{parts}  =  {character}\n{data.get('explanation', '')}".strip()
        _add_activity_box(slide, title, body, 0.85, y, 6.4, 1.55)
        return y + 1.75
    if component.component_type == "ClassroomGame":
        _add_activity_box(slide, title, json.dumps(data, ensure_ascii=False, indent=2), 0.85, y, 6.4, 1.55)
        return y + 1.75
    _add_activity_box(slide, f"{title} · static fallback", "Unsupported component rendered as editable activity notes.", 0.85, y, 6.4, 1.1)
    return y + 1.25


def _add_title(slide, title: str) -> None:
    _add_text(slide, title, 0.85, 0.62, 8.8, 0.68, 31, bold=True, color=INK)


def _add_content_blocks(slide, slide_model) -> None:
    text = _content_text(slide_model)
    if text:
        _add_text(slide, text, 0.9, 1.35, 7.0, 2.3, 22, color=INK)


def _add_media_card(slide, root: Path, slide_model, manifest: AssetManifest, x: float, y: float, w: float, h: float, is_classroom: bool = False) -> None:
    path = _image_path(root, slide_model.media_requirements.image_key, manifest)
    if path and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        slide.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w), height=Inches(h))
        return
    if is_classroom:
        # Classroom: hide prompt text, use minimal placeholder or nothing
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = MINT
        shape.line.color.rgb = LINE
        shape.line.fill.background()
        return
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = MINT
    shape.line.color.rgb = LINE
    frame = shape.text_frame
    frame.clear()
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = slide_model.media_requirements.image_prompt or "Image placeholder"
    run.font.size = Pt(16)
    run.font.color.rgb = TEAL
    run.font.bold = True


def _add_label(slide, text: str) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.82), Inches(0.25), Inches(2.35), Inches(0.32))
    shape.fill.solid()
    shape.fill.fore_color.rgb = MINT
    shape.line.color.rgb = MINT
    frame = shape.text_frame
    frame.clear()
    p = frame.paragraphs[0]
    run = p.add_run()
    run.text = text
    run.font.size = Pt(10)
    run.font.bold = True
    run.font.color.rgb = TEAL


def _add_card(slide, label: str, body: str, x: float, y: float, w: float, h: float) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = SURFACE
    shape.line.color.rgb = LINE
    frame = shape.text_frame
    frame.clear()
    p = frame.paragraphs[0]
    run = p.add_run()
    run.text = f"{label}. {body}"
    run.font.size = Pt(19)
    run.font.color.rgb = INK


def _add_activity_box(slide, title: str, body: str, x: float, y: float, w: float, h: float, icon: str = "") -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = SURFACE
    shape.line.color.rgb = LINE
    frame = shape.text_frame
    frame.clear()
    title_p = frame.paragraphs[0]
    title_run = title_p.add_run()
    title_run.text = f"{icon} {title}".strip()
    title_run.font.size = Pt(14)
    title_run.font.bold = True
    title_run.font.color.rgb = TEAL
    body_p = frame.add_paragraph()
    body_run = body_p.add_run()
    body_run.text = body or "Static classroom activity"
    body_run.font.size = Pt(15)
    body_run.font.color.rgb = INK


def _add_text(slide, text: str, x: float, y: float, w: float, h: float, size: int, bold: bool = False, color: RGBColor = INK, center: bool = False) -> None:
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    p = frame.paragraphs[0]
    if center:
        p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def _add_footer(slide, text: str) -> None:
    _add_text(slide, text, 0.85, 6.93, 11.6, 0.28, 9, color=MUTED)


# ── New: Traditional Deck Slide Renderer ──

SUPPORTED_DECK_LAYOUTS: set[str] = {
    "cover_title", "objectives_cards", "single_item_focus",
    "two_card_contrast", "listen_choose", "dialogue_bubbles",
    "match_pairs", "summary_cards", "generic_content",
}


def _render_deck_slide(slide, deck_slide, is_classroom: bool = False) -> None:
    """Render a traditional deck slide from a PptxDeckSlide plan."""
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    layout = deck_slide.traditional_layout if deck_slide.traditional_layout in SUPPORTED_DECK_LAYOUTS else "generic_content"

    if layout == "single_item_focus":
        _render_deck_single_item(slide, deck_slide)
    elif layout == "two_card_contrast":
        _render_deck_two_card_contrast(slide, deck_slide)
    elif layout == "cover_title":
        _render_deck_cover(slide, deck_slide)
    elif layout == "objectives_cards":
        _render_deck_objectives(slide, deck_slide)
    elif layout == "dialogue_bubbles":
        _render_deck_dialogue(slide, deck_slide)
    elif layout == "match_pairs":
        _render_deck_match(slide, deck_slide)
    elif layout == "summary_cards":
        _render_deck_summary(slide, deck_slide)
    else:
        _render_deck_generic(slide, deck_slide)

    if not is_classroom:
        _add_footer(slide, "Editable PPTX · HanClassStudio")
    if deck_slide.speaker_notes:
        notes_slide = slide.notes_slide
        if notes_slide:
            tf = notes_slide.notes_text_frame
            tf.clear()
            p = tf.paragraphs[0]
            p.add_run().text = "\n".join(deck_slide.speaker_notes)


def _render_deck_single_item(slide, ds) -> None:
    """Hero target word centered, pronunciation below, scaffold below."""
    # Decorative background
    bg = slide.shapes.add_shape(1, Inches(0.5), Inches(0.5), Inches(12.3), Inches(6.5))
    bg.fill.solid(); bg.fill.fore_color.rgb = RGBColor(0xF5, 0xF5, 0xF5)
    bg.line.fill.background()
    # Hero text
    _add_text(slide, ds.target_text or ds.main_focus, 2.5, 1.2, 8.3, 2.0, 52, bold=True, color=RGBColor(0x33, 0x33, 0x33), center=True)
    # Pronunciation
    if ds.pronunciation:
        _add_text(slide, ds.pronunciation, 2.5, 3.3, 8.3, 0.7, 26, color=RGBColor(0x99, 0x99, 0x99), center=True)
    # Scaffold meaning
    if ds.scaffold_text:
        _add_text(slide, ds.scaffold_text, 2.5, 4.1, 8.3, 0.8, 22, color=RGBColor(0x66, 0x66, 0x66), center=True)
    # Usage context
    if ds.usage_context:
        _add_text(slide, ds.usage_context, 2.5, 5.0, 8.3, 0.6, 18, color=RGBColor(0x99, 0x99, 0x99), center=True)
    # Teacher notes in classroom mode only via speaker notes


def _render_deck_two_card_contrast(slide, ds) -> None:
    """Two scene cards side by side."""
    left_label = ds.target_text.split("/")[0].strip() if "/" in ds.target_text else ""
    right_label = ds.target_text.split("/")[1].strip() if "/" in ds.target_text else ""
    # Left card
    card1 = slide.shapes.add_shape(1, Inches(0.8), Inches(1.0), Inches(5.5), Inches(5.0))
    card1.fill.solid(); card1.fill.fore_color.rgb = RGBColor(0xFF, 0xF3, 0xE0)
    card1.line.fill.background()
    _add_text(slide, left_label or "你好！", 1.0, 2.0, 5.1, 1.5, 40, bold=True, color=RGBColor(0x33, 0x33, 0x33), center=True)
    _add_text(slide, ds.scaffold_text, 1.0, 3.8, 5.1, 1.0, 20, color=RGBColor(0x66, 0x66, 0x66), center=True)
    # Right card
    card2 = slide.shapes.add_shape(1, Inches(6.8), Inches(1.0), Inches(5.5), Inches(5.0))
    card2.fill.solid(); card2.fill.fore_color.rgb = RGBColor(0xE3, 0xF2, 0xFD)
    card2.line.fill.background()
    _add_text(slide, right_label or "您好！", 7.0, 2.0, 5.1, 1.5, 40, bold=True, color=RGBColor(0x33, 0x33, 0x33), center=True)
    _add_text(slide, ds.usage_context or ds.scaffold_text, 7.0, 3.8, 5.1, 1.0, 20, color=RGBColor(0x66, 0x66, 0x66), center=True)


def _render_deck_cover(slide, ds) -> None:
    _add_text(slide, ds.target_text or ds.main_focus, 2.0, 2.5, 9.3, 2.0, 48, bold=True, color=RGBColor(0x33, 0x33, 0x33), center=True)


def _render_deck_objectives(slide, ds) -> None:
    _add_text(slide, "学习目标", 1.0, 0.5, 11.3, 0.8, 28, bold=True, color=RGBColor(0x33, 0x33, 0x33))
    lines = ds.target_text.split("\\n")
    y = 1.5
    for line in lines[:4]:
        _add_text(slide, f"• {line}", 1.5, y, 10.3, 0.7, 20, color=RGBColor(0x33, 0x33, 0x33))
        y += 1.0


def _render_deck_dialogue(slide, ds) -> None:
    lines = ds.target_text.split("\\n")
    y = 1.0
    for i, line in enumerate(lines[:6]):
        side = 1.0 if i % 2 == 0 else 4.5
        _add_text(slide, line, side, y, 8.0, 0.7, 20, color=RGBColor(0x33, 0x33, 0x33))
        y += 0.9


def _render_deck_match(slide, ds) -> None:
    lines = ds.target_text.split("\\n")
    y = 1.5
    for line in lines[:8]:
        _add_text(slide, line, 2.0, y, 9.3, 0.6, 18, color=RGBColor(0x33, 0x33, 0x33))
        y += 0.8


def _render_deck_summary(slide, ds) -> None:
    _add_text(slide, "课堂小结", 1.0, 0.5, 11.3, 0.8, 28, bold=True, color=RGBColor(0x33, 0x33, 0x33))
    lines = ds.target_text.split("\\n")
    y = 1.5
    for line in lines[:4]:
        _add_text(slide, f"☐ {line}", 1.5, y, 10.3, 0.7, 20, color=RGBColor(0x33, 0x33, 0x33))
        y += 1.0


def _render_deck_generic(slide, ds) -> None:
    _add_text(slide, ds.main_focus or ds.target_text or "课堂活动", 1.0, 0.5, 11.3, 0.8, 28, bold=True, color=RGBColor(0x33, 0x33, 0x33))
    if ds.target_text:
        _add_text(slide, ds.target_text, 1.0, 1.5, 11.3, 4.0, 20, color=RGBColor(0x33, 0x33, 0x33))


def _content_text(slide_model) -> str:
    lines = []
    for block in slide_model.content_blocks:
        if block.text:
            lines.append(block.text)
        if block.scaffolding_text and not PROVIDER_REQUIRED_PPTX.search(block.scaffolding_text):
            lines.append(block.scaffolding_text)
    return "\n".join(lines)


def _image_path(root: Path, image_key: str | None, manifest: AssetManifest) -> Path | None:
    if not image_key:
        return None
    for asset in manifest.images:
        if asset.id == image_key:
            path = root / asset.path
            return path if path.exists() else None
    return None


def _build_pptx_quality_report(blueprint: LessonBlueprint, report: QualityReport | None, force: bool) -> dict[str, Any]:
    warnings = [
        "HTML interactions were converted to editable classroom static activity pages.",
        "Audio is represented as text prompts or labels; real audio is not embedded.",
    ]
    if force:
        warnings.append("PPTX export was forced.")
    if not report:
        warnings.append("Source quality_report.json was missing.")
    return {
        "schema": "hanclassstudio.pptx_quality_report.v1",
        "state": "warning" if warnings else "pass",
        "blocking": [],
        "warnings": warnings,
        "passed": [
            "pptx_file_created",
            f"slide_count:{len(blueprint.slides)}",
            "editable_shapes_created",
        ],
        "source_quality_state": report.state if report else None,
    }


def _list(value) -> list:
    return value if isinstance(value, list) else []
