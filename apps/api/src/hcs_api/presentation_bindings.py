"""Presentation bindings: kernel activities/evidence -> presentation targets."""

from __future__ import annotations

import re
from typing import Any

from .models import (
    ActivityPlan,
    EvidencePlan,
    EvidenceSpec,
    LearningActivity,
    LearningStatePlan,
    LessonBlueprint,
    LessonSlide,
    PresentationBinding,
    PresentationBindingPlan,
    SlideComponent,
)


UNSUITABLE_ZB_COMPONENTS = {"SentenceDragBuilder", "open_response", "role_play_scene", "OpenResponse", "RolePlayScene"}

ACTIVITY_COMPONENT_HINTS = {
    "scene_choice": {"ListenAndChoose", "ChoicePrompt", "VocabularyFlipCard", "GrammarContrast"},
    "multiple_choice": {"ListenAndChoose", "ChoicePrompt", "QuizCard"},
    "match_pairs": {"MatchGame", "MatchPairs"},
    "listen_choose": {"ListenAndChoose", "DialoguePractice", "VocabularyFlipCard"},
    "drag_sentence": {"SentenceDragBuilder"},
    "role_play_scene": {"RolePlayScene"},
    "open_response": {"OpenResponse"},
    "teacher_observation": {"TeacherObservation"},
}

SLIDE_INTENT_HINTS = {
    "VocabularySlide": ("vocabulary", "recognize"),
    "GrammarPatternSlide": ("politeness", "understand"),
    "DialogueSlide": ("dialogue", "production"),
    "PracticeSlide": ("choice", "practice", "production"),
    "SummarySlide": ("production", "review"),
}


def build_activity_bindings(
    blueprint: LessonBlueprint,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    state_plan: LearningStatePlan,
    learner_level: str = "zero_beginner",
) -> PresentationBindingPlan:
    plan = PresentationBindingPlan()
    evidence_by_id = {ev.evidence_id: ev for ev in evidence_plan.evidence_specs}
    used_targets: set[tuple[int, str, str]] = set()

    for activity in activity_plan.activities:
        for evidence_id in activity.collects_evidence:
            evidence = evidence_by_id.get(evidence_id)
            if not evidence:
                plan.blocking.append(f"Activity '{activity.activity_id}' collects missing evidence '{evidence_id}'")
                continue
            binding = _best_binding_for_activity(blueprint, state_plan, activity, evidence, learner_level, used_targets)
            if binding:
                plan.bindings.append(binding)
                used_targets.update(_target_keys(binding))
                if binding.binding_confidence < 0.5:
                    plan.warnings.append(
                        f"Low-confidence binding '{binding.binding_id}' ({binding.binding_confidence:.1f}): {binding.binding_reason}"
                    )
            else:
                plan.blocking.append(f"No presentation binding found for activity '{activity.activity_id}' / evidence '{evidence_id}'")

    return check_activity_bindings(blueprint, evidence_plan, activity_plan, state_plan, plan, learner_level)


def check_activity_bindings(
    blueprint: LessonBlueprint,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    state_plan: LearningStatePlan,
    binding_plan: PresentationBindingPlan,
    learner_level: str = "zero_beginner",
) -> PresentationBindingPlan:
    report = PresentationBindingPlan(bindings=list(binding_plan.bindings), warnings=list(binding_plan.warnings), blocking=list(binding_plan.blocking))
    evidence_ids = {ev.evidence_id for ev in evidence_plan.evidence_specs}
    activity_ids = {act.activity_id for act in activity_plan.activities}
    activities = {act.activity_id: act for act in activity_plan.activities}
    evidence = {ev.evidence_id: ev for ev in evidence_plan.evidence_specs}
    slides = {slide.id: slide for slide in blueprint.slides}
    bound_evidence = {binding.evidence_id for binding in report.bindings}
    bindings_by_target: dict[tuple[int, str, str], list[PresentationBinding]] = {}

    for binding in report.bindings:
        for key in _target_keys(binding):
            bindings_by_target.setdefault(key, []).append(binding)

    for (slide_id, component_id, mode), bindings in bindings_by_target.items():
        if len(bindings) > 1:
            evs = ", ".join(sorted({b.evidence_id for b in bindings}))
            report.blocking.append(
                f"Duplicate presentation target binding: slide_id={slide_id} component_id={component_id} mode={mode} "
                f"has evidence [{evs}]. Each presentation target may have only one primary binding in v0.2.2-alpha."
            )

    for ev_id in evidence_ids:
        if ev_id not in bound_evidence:
            report.blocking.append(f"Evidence '{ev_id}' has no presentation binding")

    for binding in report.bindings:
        if binding.activity_id not in activity_ids:
            report.blocking.append(f"Binding '{binding.binding_id}' references unknown activity '{binding.activity_id}'")
        if binding.evidence_id not in evidence_ids:
            report.blocking.append(f"Binding '{binding.binding_id}' references unknown evidence '{binding.evidence_id}'")
        slide = slides.get(binding.slide_id)
        if not slide:
            report.blocking.append(f"Binding '{binding.binding_id}' references unknown slide '{binding.slide_id}'")
            continue
        component = None
        if binding.component_id:
            component = next((c for c in slide.components if c.id == binding.component_id), None)
            if not component:
                report.blocking.append(
                    f"Binding '{binding.binding_id}' references unknown component '{binding.component_id}' on slide '{binding.slide_id}'"
                )
        activity = activities.get(binding.activity_id)
        if _is_zero_beginner(learner_level):
            component_type = component.component_type if component else ""
            activity_type = activity.activity_type if activity else ""
            if component_type in UNSUITABLE_ZB_COMPONENTS or activity_type in {"open_response", "role_play_scene", "drag_sentence"}:
                report.blocking.append(f"Binding '{binding.binding_id}' points zero_beginner evidence to unsuitable activity/component")
        ev = evidence.get(binding.evidence_id)
        if ev and ev.evidence_type == "teacher_observation":
            modes = set(binding.presentation_modes)
            if not ({"speaker_notes", "teacher_observation"} & modes):
                report.blocking.append(f"Teacher observation binding '{binding.binding_id}' lacks speaker_notes or teacher_observation mode")
        if binding.binding_confidence < 0.5:
            msg = f"Binding '{binding.binding_id}' is low confidence ({binding.binding_confidence:.1f})"
            if msg not in report.warnings:
                report.warnings.append(msg)

    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    return report


def _best_binding_for_activity(
    blueprint: LessonBlueprint,
    state_plan: LearningStatePlan,
    activity: LearningActivity,
    evidence: EvidenceSpec,
    learner_level: str,
    used_targets: set[tuple[int, str, str]] | None = None,
) -> PresentationBinding | None:
    explicit_cover_allowed = False
    candidates: list[tuple[float, str, LessonSlide, SlideComponent | None]] = []
    intent = _transition_intent_for_evidence(state_plan, evidence.evidence_id)

    for slide in blueprint.slides:
        if slide.slide_type in ("CoverSlide", "ObjectiveSlide") and not explicit_cover_allowed:
            explicit = any(_component_activity_id(c) == activity.activity_id for c in slide.components)
            if not explicit:
                continue
        slide_text = _slide_text(slide)
        target_match = any(item and item in slide_text for item in evidence.target_items)
        slide_intent = _slide_intent_matches(slide, intent)
        purpose_score = _purpose_score(slide, intent, evidence)

        for component in slide.components:
            score, reason = _score_component(component, activity, evidence, target_match)
            if score:
                candidates.append((score + purpose_score, reason, slide, component))

        if not slide.components:
            if target_match:
                candidates.append((0.6 + purpose_score, "matched_by_target_items", slide, None))
            elif slide_intent:
                candidates.append((0.4 + purpose_score, "matched_by_slide_intent", slide, None))
        elif target_match:
            candidates.append((0.6 + purpose_score, "matched_by_target_items", slide, _preferred_component(slide, activity, evidence)))
        elif slide_intent:
            candidates.append((0.4 + purpose_score, "matched_by_slide_intent", slide, _preferred_component(slide, activity, evidence)))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[2].id, item[3].id if item[3] else ""))
    confidence = 0.0
    reason = ""
    slide = None
    component = None
    for cand_confidence, cand_reason, cand_slide, cand_component in candidates:
        provisional = PresentationBinding(
            activity_id=activity.activity_id,
            evidence_id=evidence.evidence_id,
            slide_id=cand_slide.id,
            component_id=cand_component.id if cand_component else None,
            presentation_modes=_presentation_modes(activity, evidence),
        )
        if used_targets and any(key in used_targets for key in _target_keys(provisional)):
            continue
        confidence, reason, slide, component = cand_confidence, cand_reason, cand_slide, cand_component
        break
    if slide is None:
        return None
    if _is_zero_beginner(learner_level) and component and component.component_type in UNSUITABLE_ZB_COMPONENTS:
        confidence = 0.0
        reason = "blocked_zero_beginner_unsuitable_component"
    return PresentationBinding(
        binding_id=_binding_id(activity.activity_id, evidence.evidence_id, slide.id, component.id if component else "slide"),
        activity_id=activity.activity_id,
        evidence_id=evidence.evidence_id,
        slide_id=slide.id,
        component_id=component.id if component else None,
        presentation_modes=_presentation_modes(activity, evidence),
        binding_confidence=confidence,
        binding_reason=reason,
        teacher_note_policy="include_evidence_claim_pass_fail",
    )


def _score_component(component: SlideComponent, activity: LearningActivity, evidence: EvidenceSpec, target_match: bool) -> tuple[float, str]:
    explicit = _component_activity_id(component)
    if explicit == activity.activity_id:
        return 1.0, "matched_by_component_activity_id"
    if component.id == activity.activity_id or activity.activity_id in component.id or _keyword_overlap(component.id, activity.activity_id):
        return 0.9, "matched_by_component_id"
    type_match = component.component_type in ACTIVITY_COMPONENT_HINTS.get(activity.activity_type, set())
    if type_match and target_match:
        return 0.8, "matched_by_component_type"
    if type_match:
        return 0.55, "matched_by_component_type"
    if target_match:
        return 0.6, "matched_by_target_items"
    return 0.0, ""


def _purpose_score(slide: LessonSlide, intent: str, evidence: EvidenceSpec) -> float:
    intent_text = f"{intent} {evidence.evidence_id} {evidence.learning_claim}".lower()
    if "recognize" in intent_text or "recognition" in intent_text or "vocabulary" in intent_text:
        return 0.25 if slide.slide_type == "VocabularySlide" else 0.0
    if "polite" in intent_text or "politeness" in intent_text or "contrast" in intent_text:
        return 0.35 if slide.slide_type == "GrammarPatternSlide" else 0.0
    if "dialogue" in intent_text or "production" in intent_text:
        if slide.slide_type == "DialogueSlide":
            return 0.35
        if slide.slide_type == "PracticeSlide":
            return 0.25
        if slide.slide_type == "SummarySlide":
            return 0.2
    return 0.0


def _preferred_component(slide: LessonSlide, activity: LearningActivity, evidence: EvidenceSpec) -> SlideComponent | None:
    for component in slide.components:
        if component.component_type in ACTIVITY_COMPONENT_HINTS.get(activity.activity_type, set()):
            return component
    return slide.components[0] if slide.components else None


def _component_activity_id(component: SlideComponent) -> str:
    value = component.data.get("activity_id", "")
    return str(value) if value else ""


def _presentation_modes(activity: LearningActivity, evidence: EvidenceSpec) -> list[str]:
    modes = set(activity.allowed_presentation_modes or [])
    if "html_interactive" in modes:
        modes.add("html_classroom")
    if "pptx_classroom" in modes:
        modes.add("speaker_notes")
    if evidence.evidence_type == "teacher_observation":
        modes.update({"speaker_notes", "teacher_observation"})
    return sorted(modes)


def _target_keys(binding: PresentationBinding) -> list[tuple[int, str, str]]:
    component_id = binding.component_id or "__slide__"
    modes = set(binding.presentation_modes)
    keys = []
    if {"html_classroom", "html_interactive"} & modes:
        keys.append((binding.slide_id, component_id, "html"))
    if {"pptx_classroom", "speaker_notes"} & modes:
        keys.append((binding.slide_id, component_id, "pptx"))
    if "teacher_observation" in modes:
        keys.append((binding.slide_id, component_id, "teacher"))
    return keys


def _transition_intent_for_evidence(state_plan: LearningStatePlan, evidence_id: str) -> str:
    for transition in state_plan.transitions:
        if evidence_id in transition.required_evidence_ids or evidence_id in transition.optional_evidence_ids:
            return transition.transition_intent
    return ""


def _slide_intent_matches(slide: LessonSlide, intent: str) -> bool:
    haystack = " ".join((intent, slide.slide_type, slide.layout_variant)).lower()
    return any(hint in haystack for hint in SLIDE_INTENT_HINTS.get(slide.slide_type, ()))


def _slide_text(slide: LessonSlide) -> str:
    chunks: list[str] = [slide.title, slide.slide_type, slide.layout_variant]
    chunks.extend(block.text for block in slide.content_blocks)
    for component in slide.components:
        chunks.extend([component.id, component.component_type, component.title])
        chunks.append(_flatten(component.data))
    return " ".join(chunk for chunk in chunks if chunk)


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def _keyword_overlap(left: str, right: str) -> bool:
    left_parts = {part for part in re.split(r"[_\W]+", left.lower()) if part}
    right_parts = {part for part in re.split(r"[_\W]+", right.lower()) if part}
    return bool(left_parts & right_parts)


def _binding_id(activity_id: str, evidence_id: str, slide_id: int, component_id: str) -> str:
    raw = f"bind_{activity_id}_{evidence_id}_s{slide_id}_{component_id}"
    return re.sub(r"[^A-Za-z0-9_]+", "_", raw)


def _is_zero_beginner(level: str) -> bool:
    return "zero" in (level or "").lower() or (level or "").lower() == "zb"
