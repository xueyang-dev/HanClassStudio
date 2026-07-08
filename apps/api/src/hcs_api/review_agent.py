"""Courseware Review Agent — 4-dimension review of lesson blueprints and rendered artifacts."""

from __future__ import annotations

import re
from typing import Any

from .content_contract import (
    LEARNER_FACING_FORBIDDEN_LABELS,
    is_allowed_learner_text as _is_allowed,
    resolve_scaffold_text,
    resolve_scaffold_usage,
)
from .models import (
    CoursewareReviewReport,
    LearnerLevel,
    LessonBlueprint,
    LessonSlide,
    QualityState,
    RenderedArtifactReview,
    ReviewDimension,
    ReviewFinding,
    ReviewSeverity,
    RevisionPatch,
    RevisionPlan,
)


FORBIDDEN_COMPONENTS_ZB = {"SentenceDragBuilder", "ClassroomGame"}
FORBIDDEN_TASK_LABELS = {
    "Teacher answer", "答案提示", "拖拽组句", "连一连",
    "排序", "判断", "归类", "分类",
}
ALLOWED_ACTIVITIES_ZB = {"AudioButton", "VocabularyFlipCard", "ListenAndChoose", "MatchGame"}


def review_blueprint(
    blueprint: LessonBlueprint,
    level: str = "zero_beginner",
    scaffold_lang: str = "Arabic",
    language_items: list | None = None,
    kernel_alignment: Any = None,
) -> CoursewareReviewReport:
    """Run 4-dimension review on a lesson blueprint."""
    report = CoursewareReviewReport()
    findings: list[ReviewFinding] = []
    is_zb = level in ("zero_beginner",)
    item_lookup: dict[str, Any] = {}
    if language_items:
        for item in language_items:
            if isinstance(item, dict):
                item_lookup[item.get("target_form", "")] = item
            elif hasattr(item, "target_form"):
                item_lookup[item.target_form] = item
    known_words: set[str] = set()
    if language_items:
        for li in language_items:
            form = li.get("target_form", "") if isinstance(li, dict) else (getattr(li, "target_form", "") if hasattr(li, "target_form") else "")
            if form:
                known_words.add(form)
    known_words.update({"我", "的", "了", "是", "在", "有", "不", "和", "也", "都", "很"})

    # Track introduced items per slide
    introduced: set[str] = set(known_words)

    for idx, slide in enumerate(blueprint.slides):
        fid = f"F{idx+1:03d}"

        # ── Suitable checks ──
        # Check component labels in title
        if slide.title and any(lb in slide.title for lb in LEARNER_FACING_FORBIDDEN_LABELS):
            findings.append(ReviewFinding(
                id=fid, slide_id=slide.id, dimension="suitable", severity="blocked",
                message=f"Slide title contains forbidden label: '{slide.title}'",
                evidence=f"title={slide.title}",
                suggested_action=f"Replace slide title '{slide.title}' with a learner-safe title",
            ))
            report.blocking.append(f"S{slide.id}: title '{slide.title}' forbidden")

        # Check component titles
        for comp in slide.components:
            if comp.title and any(lb in comp.title for lb in FORBIDDEN_TASK_LABELS):
                findings.append(ReviewFinding(
                    id=fid, slide_id=slide.id, dimension="suitable", severity="blocked",
                    message=f"Component title contains task label: '{comp.title}'",
                    evidence=f"comp_type={comp.component_type}",
                    suggested_action="Remove task labels from component titles",
                ))
                report.blocking.append(f"S{slide.id}: task label '{comp.title}'")

        # Check component types for zero_beginner
        if is_zb:
            for comp in slide.components:
                if comp.component_type in FORBIDDEN_COMPONENTS_ZB:
                    findings.append(ReviewFinding(
                        id=f"{fid}b", slide_id=slide.id, dimension="suitable", severity="blocked",
                        message=f"'{comp.component_type}' is not suitable for zero_beginner",
                        evidence=f"comp_type={comp.component_type}",
                        suggested_action=f"Replace {comp.component_type} with {', '.join(ALLOWED_ACTIVITIES_ZB)}",
                    ))
                    report.blocking.append(f"S{slide.id}: {comp.component_type} not suitable for ZB")

        # Check vocabulary items on slide
        slide_words: set[str] = set()
        for comp in slide.components:
            for item in comp.data.get("items", []):
                word = str(item.get("word", ""))
                if word:
                    slide_words.add(word)

        # Check for scaffold meaning
        for comp in slide.components:
            for item in comp.data.get("items", []):
                word = str(item.get("word", ""))
                meaning = str(item.get("meaning", ""))
                if is_zb and word and not meaning.strip():
                    findings.append(ReviewFinding(
                        id=f"{fid}c", slide_id=slide.id, dimension="suitable", severity="warning",
                        message=f"'{word}' missing scaffold meaning for zero_beginner",
                        evidence=f"word={word}",
                        suggested_action=f"Add '{scaffold_lang}' gloss for '{word}'",
                    ))
                    report.warnings.append(f"S{slide.id}: '{word}' missing scaffold meaning")

        # Check usage context language
        for comp in slide.components:
            for item in comp.data.get("items", []):
                ctx = str(item.get("usage_context", ""))
                if is_zb and ctx and re.search(r"[\u4e00-\u9fff]{4,}", ctx):
                    findings.append(ReviewFinding(
                        id=f"{fid}d", slide_id=slide.id, dimension="suitable", severity="blocked",
                        message=f"Usage context uses Chinese instead of '{scaffold_lang}': '{ctx}'",
                        evidence=f"word={item.get('word','')}",
                        suggested_action=f"Use scaffold language '{scaffold_lang}' for context",
                    ))
                    report.blocking.append(f"S{slide.id}: Chinese usage context '{ctx[:30]}'")

        # ── Workable checks ──
        # Check teacher notes are present for activity slides
        if slide.components and not slide.content_blocks:
            has_notes = any(c.data.get("hint", "") for c in slide.components)
            if not has_notes:
                findings.append(ReviewFinding(
                    id=f"{fid}e", slide_id=slide.id, dimension="workable", severity="warning",
                    message="Activity slide without teacher notes or hints",
                    evidence=f"type={slide.slide_type}",
                    suggested_action="Add teacher hints or speaker notes",
                ))
                report.warnings.append(f"S{slide.id}: no teacher hints")

        # Check sentence drag for zb not workable
        if is_zb and any(c.component_type == "SentenceDragBuilder" for c in slide.components):
            findings.append(ReviewFinding(
                id=f"{fid}f", slide_id=slide.id, dimension="workable", severity="blocked",
                message="SentenceDragBuilder is not workable for zero_beginner",
                suggested_action="Replace with listen_choose or match activity",
            ))

        # ── Sustainable checks ──
        # Check for hardcoded language-specific strings
        for comp in slide.components:
            data_str = str(comp.data)
            # Check if provider_required leaked into data
            if "provider_required" in data_str:
                findings.append(ReviewFinding(
                    id=f"{fid}g", slide_id=slide.id, dimension="sustainable", severity="warning",
                    message="provider_required marker found in component data",
                    evidence=data_str[:100],
                    suggested_action="Use ScaffoldResolver instead of provider_required",
                ))
                report.warnings.append(f"S{slide.id}: provider_required in data")

        # ── Usable checks ──
        # Check slide has a clear focus
        if not slide.title and not any(c.data.get("items") for c in slide.components):
            findings.append(ReviewFinding(
                id=f"{fid}h", slide_id=slide.id, dimension="usable", severity="warning",
                message="Slide has no clear content focus",
                suggested_action="Add title or content items",
            ))
            report.warnings.append(f"S{slide.id}: no clear focus")

        introduced.update(slide_words)

    # Calculate scores
    score_suitable = max(0, 10 - len([f for f in findings if f.dimension == "suitable" and f.severity == "blocked"]))
    score_workable = max(0, 10 - len([f for f in findings if f.dimension == "workable" and f.severity in ("blocked", "warning")]))
    score_sustainable = max(0, 10 - len([f for f in findings if f.dimension == "sustainable"]))
    score_usable = max(0, 10 - len([f for f in findings if f.dimension == "usable"]))
    report.scores = {"suitable": score_suitable, "workable": score_workable, "sustainable": score_sustainable, "usable": score_usable}
    report.findings = findings

    # Derive state
    if report.blocking:
        report.state = "blocked"
    elif report.warnings:
        report.state = "warning"

    # Kernel alignment integration
    if kernel_alignment:
        if isinstance(kernel_alignment, dict):
            ka_state = kernel_alignment.get("state", "")
        else:
            ka_state = getattr(kernel_alignment, "state", "")
        if ka_state == "blocked":
            report.blocking.append("Evidence alignment check is blocked — review cannot pass")
            report.state = "blocked"

    # Summary
    dims = [f for f in findings]
    report.summary = f"Review: {len(dims)} findings ({len(report.blocking)} blocking, {len(report.warnings)} warnings) | Scores: suitable={report.scores['suitable']}/10 workable={report.scores['workable']}/10 sustainable={report.scores['sustainable']}/10 usable={report.scores['usable']}/10"

    if not report.passed:
        report.passed.append(f"Blueprint reviewed for {scaffold_lang} scaffold at {level} level")
    return report


def build_revision_plan(
    report: CoursewareReviewReport,
    blueprint: LessonBlueprint,
) -> RevisionPlan:
    """Build a revision plan from review findings."""
    plan = RevisionPlan(target_artifact="lesson_blueprint")
    for finding in report.findings:
        if finding.severity == "blocked":
            forbidden = []
            preferred = []
            if "SentenceDragBuilder" in finding.message:
                forbidden.append("SentenceDragBuilder")
                preferred.extend(["ListenAndChoose", "MatchGame"])
            if "forbidden label" in finding.message.lower():
                forbidden.append(finding.evidence.replace("title=", "") if "title=" in finding.evidence else "meta")
            plan.patches.append(RevisionPatch(
                slide_id=finding.slide_id,
                operation="replace_activity" if "SentenceDragBuilder" in finding.message else "rewrite_text",
                constraints={
                    "allowed_target_text": [],
                    "forbidden_text": forbidden,
                    "forbidden_components": forbidden,
                    "preferred_activity_types": preferred,
                    "preferred_layouts": [],
                },
                reason=finding.message,
            ))
    plan.priority = 1 if report.blocking else 2
    plan.rationale = f"Revision plan with {len(plan.patches)} patches"
    return plan


def review_rendered_artifact(
    html_text: str,
    pptx_text: str | None = None,
    level: str = "zero_beginner",
) -> RenderedArtifactReview:
    """Review final rendered HTML/PPTX for forbidden text."""
    review = RenderedArtifactReview()
    is_zb = level in ("zero_beginner",)
    forbidden_labels = LEARNER_FACING_FORBIDDEN_LABELS | {"provider_required", "Editable PPTX"}

    # Check HTML
    for lb in forbidden_labels:
        if lb in html_text:
            ctx = html_text[html_text.find(lb) - 30:html_text.find(lb) + len(lb) + 30]
            review.forbidden_text_leaks.append({"artifact": "HTML", "text": lb, "context": ctx[:80]})
            review.blocking.append(f"HTML contains '{lb}'")

    # Check teacher-only text
    teacher_patterns = ["对老师、", "Teacher answer", "答案提示", "teacher_only"]
    for pat in teacher_patterns:
        if pat in html_text:
            ctx = html_text[html_text.find(pat) - 20:html_text.find(pat) + len(pat) + 20]
            review.teacher_only_leaks.append({"artifact": "HTML", "text": pat, "context": ctx[:80]})
            review.blocking.append(f"HTML contains teacher text '{pat}'")

    # Check PPTX
    if pptx_text:
        for lb in forbidden_labels:
            if lb in pptx_text:
                review.forbidden_text_leaks.append({"artifact": "PPTX", "text": lb, "context": pptx_text[pptx_text.find(lb) - 20:pptx_text.find(lb) + len(lb) + 20][:80]})
                review.blocking.append(f"PPTX contains '{lb}'")

        for pat in teacher_patterns:
            if pat in pptx_text:
                review.teacher_only_leaks.append({"artifact": "PPTX", "text": pat, "context": pptx_text[pptx_text.find(pat) - 20:pptx_text.find(pat) + len(pat) + 20][:80]})
                review.blocking.append(f"PPTX contains teacher text '{pat}'")

    # Check answers visible
    for ans_marker in ["Answer:", "答案：", "answer"]:
        if ans_marker in (pptx_text or ""):
            review.answer_visible_on_slide.append({"artifact": "PPTX", "text": ans_marker})

    # Derive state
    if review.blocking:
        review.state = "blocked"
    elif review.warnings:
        review.state = "warning"
    if not review.passed:
        review.passed.append(f"Rendered artifact reviewed at {level} level")
    return review


# ── Revision Plan Application ──

from copy import deepcopy
from typing import Any


def apply_revision_plan(
    blueprint: LessonBlueprint,
    revision_plan: RevisionPlan,
    learner_model: Any = None,
    allowed_text_plan: Any = None,
    language_items: list | None = None,
) -> tuple[LessonBlueprint, dict]:
    """Apply revision plan patches to a blueprint, returning revised blueprint + application report."""
    revised = LessonBlueprint(**blueprint.model_dump(mode="json"))
    report = {
        "schema": "hanclassstudio.revision_application.v1",
        "applied_patches": 0,
        "failed_patches": 0,
        "details": [],
        "new_slides": [],
        "removed_slides": [],
        "activity_replacements": [],
    }
    item_lookup = {}
    if language_items:
        for li in language_items:
            if isinstance(li, dict):
                item_lookup[li.get("target_form", "")] = li
            elif hasattr(li, "target_form"):
                item_lookup[li.target_form] = li

    for patch in revision_plan.patches:
        slide = _find_slide(revised, patch.slide_id)
        if slide is None:
            report["failed_patches"] += 1
            report["details"].append({"patch": patch.operation, "slide_id": patch.slide_id, "status": "skipped", "reason": "slide not found"})
            continue

        try:
            if patch.operation == "rewrite_text":
                _apply_rewrite_text(slide, patch, item_lookup)
                report["details"].append({"patch": "rewrite_text", "slide_id": patch.slide_id, "status": "applied"})

            elif patch.operation == "replace_activity":
                _apply_replace_activity(slide, patch)
                report["details"].append({"patch": "replace_activity", "slide_id": patch.slide_id, "status": "applied", "replaced": str(patch.constraints.get("forbidden_components", [])), "with": str(patch.constraints.get("preferred_activity_types", []))})
                report["activity_replacements"].append({"slide_id": patch.slide_id, "from": patch.constraints.get("forbidden_components", []), "to": patch.constraints.get("preferred_activity_types", [])})

            elif patch.operation == "move_to_notes":
                _apply_move_to_notes(slide, patch)
                report["details"].append({"patch": "move_to_notes", "slide_id": patch.slide_id, "status": "applied"})

            elif patch.operation == "change_layout":
                slide.layout_variant = patch.constraints.get("preferred_layouts", [None])[0] if patch.constraints.get("preferred_layouts") else "basic"
                report["details"].append({"patch": "change_layout", "slide_id": patch.slide_id, "status": "applied"})

            elif patch.operation == "remove_block":
                _apply_remove_block(slide, patch)
                report["details"].append({"patch": "remove_block", "slide_id": patch.slide_id, "status": "applied"})

            elif patch.operation == "replace_component":
                _apply_replace_component(slide, patch)
                report["details"].append({"patch": "replace_component", "slide_id": patch.slide_id, "status": "applied"})

            else:
                report["failed_patches"] += 1
                report["details"].append({"patch": patch.operation, "slide_id": patch.slide_id, "status": "skipped", "reason": f"unknown operation: {patch.operation}"})
                continue

            report["applied_patches"] += 1

        except Exception as exc:
            report["failed_patches"] += 1
            report["details"].append({"patch": patch.operation, "slide_id": patch.slide_id, "status": "error", "reason": str(exc)[:100]})

    return revised, report


def _find_slide(blueprint: LessonBlueprint, slide_id: int) -> LessonSlide | None:
    """Find a slide by id in the blueprint."""
    for slide in blueprint.slides:
        if slide.id == slide_id:
            return slide
    return None


def _apply_rewrite_text(slide: LessonSlide, patch: RevisionPatch, item_lookup: dict) -> None:
    """Rewrite learner-facing titles and content blocks."""
    forbidden = patch.constraints.get("forbidden_text", [])
    allowed = patch.constraints.get("allowed_target_text", [])

    # Fix title: if it matches forbidden, replace with safe title
    if slide.title:
        for fb in forbidden:
            if fb in slide.title:
                # Replace "生词卡" or "词卡" with the first vocabulary word or safe title
                replacement = ""
                for comp in slide.components:
                    if comp.component_type == "VocabularyFlipCard":
                        items = comp.data.get("items", [])
                        if items:
                            replacement = items[0].get("word", "")
                            break
                slide.title = replacement or "练一练"

    # Fix content blocks: remove teacher_text from learner-facing blocks
    for block in slide.content_blocks:
        if block.text:
            for fb in forbidden:
                block.text = block.text.replace(fb, "").strip()
        block.scaffolding_text = ""


def _apply_replace_activity(slide: LessonSlide, patch: RevisionPatch) -> None:
    """Replace forbidden component types with allowed alternatives."""
    forbidden = set(patch.constraints.get("forbidden_components", []))
    preferred = patch.constraints.get("preferred_activity_types", [])

    new_components = []
    for comp in slide.components:
        if comp.component_type in forbidden:
            if "ListenAndChoose" in preferred:
                replacement = SlideComponent(
                    id=comp.id + "_revised",
                    component_type="ListenAndChoose",
                    title=comp.title if comp.title and not any(lb in comp.title for lb in LEARNER_FACING_FORBIDDEN_LABELS) else "",
                    data={
                        "audio_key": "revised_1",
                        "audio_text": "你好！",
                        "choices": ["你好！", "您好！", "再见！"],
                        "answer": "你好！",
                        "hint": "",
                    },
                )
                new_components.append(replacement)
            elif "MatchGame" in preferred:
                replacement = SlideComponent(
                    id=comp.id + "_revised",
                    component_type="MatchGame",
                    title="",
                    data={
                        "pairs": [{"left": "你好", "right": "nǐ hǎo"}, {"left": "您好", "right": "nín hǎo"}],
                        "hint": "",
                    },
                )
                new_components.append(replacement)
        else:
            new_components.append(comp)
    slide.components = new_components


def _apply_move_to_notes(slide: LessonSlide, patch: RevisionPatch) -> None:
    """Move answer keys and teacher text from component data to notes/comments."""
    forbidden = set(patch.constraints.get("forbidden_text", []))
    for comp in slide.components:
        data = comp.data
        keys_to_remove = []
        for key in ["hint", "answer", "success", "failure"]:
            if key in data and isinstance(data[key], str):
                for fb in forbidden:
                    if fb in data[key]:
                        keys_to_remove.append(key)
                        break
        for key in keys_to_remove:
            data.pop(key, None)


def _apply_remove_block(slide: LessonSlide, patch: RevisionPatch) -> None:
    """Remove content blocks containing forbidden text."""
    slide.content_blocks = [
        b for b in slide.content_blocks
        if not any(fb in (b.text or "") for fb in patch.constraints.get("forbidden_text", []))
    ]


def _apply_replace_component(slide: LessonSlide, patch: RevisionPatch) -> None:
    """Replace a specific component with a safer alternative."""
    forbidden = set(patch.constraints.get("forbidden_components", []))
    new_components = []
    for comp in slide.components:
        if comp.component_type in forbidden:
            new_components.append(SlideComponent(
                id=comp.id + "_safe",
                component_type="AudioButton",
                title="",
                data={"audio_key": "safe_1", "audio_text": "请听", "label": ""},
            ))
        else:
            new_components.append(comp)
    slide.components = new_components
