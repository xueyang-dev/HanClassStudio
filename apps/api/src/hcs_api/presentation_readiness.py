"""Presentation authority and readiness checks before renderer compilation."""

from __future__ import annotations

from typing import Any, Literal

from .models import (
    ActivityPlan,
    EvidenceAlignmentReport,
    EvidencePlan,
    LessonBlueprint,
    PresentationBindingPlan,
    PresentationReadinessReport,
)


LEARNER_PRESENTATION_MODES = {"html_interactive", "html_classroom", "pptx_classroom"}
TEACHER_PRESENTATION_MODES = {"speaker_notes", "teacher_observation"}
DEPRECATED_BLUEPRINT_FIELDS = ("route_hint", "objectives", "key_vocabulary", "grammar_points")
KERNEL_OWNED_KEYS = {
    "learning_goals",
    "learning_states",
    "goal_id",
    "success_criteria",
    "observable_behavior",
    "acceptable_response",
    "confidence_policy",
    "teacher_observation_notes",
    "learner_action",
    "teacher_action",
    "fallback_activity",
    "failure_action",
    "pass_criteria",
    "expected_behavior",
    "prior_knowledge_assumptions",
}


def check_presentation_readiness(
    blueprint: LessonBlueprint,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    binding_plan: PresentationBindingPlan,
    alignment_report: EvidenceAlignmentReport,
    binding_strategy: Literal["legacy_resolved", "abstract"] = "legacy_resolved",
) -> PresentationReadinessReport:
    """Compose existing gates and freeze the presentation/pedagogy boundary."""
    report = PresentationReadinessReport(binding_strategy=binding_strategy)
    evidence = {item.evidence_id: item for item in evidence_plan.evidence_specs}
    activities = {item.activity_id: item for item in activity_plan.activities}
    bound_pairs = {(item.activity_id, item.evidence_id) for item in binding_plan.bindings}
    slides = {slide.id: slide for slide in blueprint.slides}

    if alignment_report.state == "blocked":
        _block(report, "Evidence alignment is blocked; presentation cannot be ready.")
    if binding_plan.state == "blocked":
        for issue in binding_plan.blocking or ["Presentation binding quality is blocked."]:
            _invalid(report, issue)
    for issue in binding_plan.warnings:
        _warn(report, issue)

    for activity in activity_plan.activities:
        for evidence_id in activity.evidence_ids:
            if (activity.activity_id, evidence_id) not in bound_pairs:
                issue = f"Activity '{activity.activity_id}' / evidence '{evidence_id}' has no presentation binding."
                report.missing_activity_bindings.append(issue)
                _block(report, issue)

    for binding in binding_plan.bindings:
        if not binding.binding_id:
            _invalid(report, "Presentation binding is missing binding_id.")
        activity = activities.get(binding.activity_id)
        evidence_spec = evidence.get(binding.evidence_id)
        if not activity:
            _invalid(report, f"Binding '{binding.binding_id}' references unknown activity '{binding.activity_id}'.")
            continue
        if not evidence_spec:
            _invalid(report, f"Binding '{binding.binding_id}' references unknown evidence '{binding.evidence_id}'.")
            continue
        if binding_strategy == "legacy_resolved":
            slide = slides.get(binding.slide_id)
            if not slide:
                _invalid(report, f"Binding '{binding.binding_id}' references unknown slide '{binding.slide_id}'.")
                continue
            if binding.component_id and not any(item.id == binding.component_id for item in slide.components):
                _invalid(
                    report,
                    f"Binding '{binding.binding_id}' references unknown component '{binding.component_id}' on slide '{binding.slide_id}'.",
                )
                continue

        modes = set(binding.presentation_modes)
        teacher_only = (
            not activity.learner_facing
            or evidence_spec.collection_method == "teacher_observation"
            or evidence_spec.evidence_type == "teacher_observation"
        )
        if teacher_only and modes & LEARNER_PRESENTATION_MODES:
            issue = f"Teacher-only binding '{binding.binding_id}' uses learner-facing modes {sorted(modes & LEARNER_PRESENTATION_MODES)}."
            report.teacher_channel_leaks.append(issue)
            _block(report, issue)
        if teacher_only and not modes & TEACHER_PRESENTATION_MODES:
            issue = f"Teacher-only binding '{binding.binding_id}' has no teacher presentation mode."
            report.teacher_channel_leaks.append(issue)
            _block(report, issue)

    blueprint_data = blueprint.model_dump(mode="json")
    for field in DEPRECATED_BLUEPRINT_FIELDS:
        if blueprint_data.get(field):
            report.deprecated_blueprint_fields.append(field)
            _warn(report, f"Legacy blueprint field '{field}' remains a compatibility projection and is not pedagogical authority.")

    for path in _kernel_owned_paths(blueprint_data):
        issue = f"lesson_blueprint contains kernel-owned field '{path}'."
        report.authority_violations.append(issue)
        _block(report, issue)

    if binding_strategy == "legacy_resolved":
        _warn(report, "Bindings are resolved against a pre-existing legacy blueprint; binding-first compilation is not active.")

    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    report.passed.append(
        f"Presentation references: {len(binding_plan.bindings)} bindings, "
        f"{len(activity_plan.activities)} activities, {len(evidence_plan.evidence_specs)} evidence specs."
    )
    return report


def _kernel_owned_paths(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if key in KERNEL_OWNED_KEYS:
                found.append(item_path)
            found.extend(_kernel_owned_paths(item, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_kernel_owned_paths(item, f"{path}[{index}]"))
    return found


def _invalid(report: PresentationReadinessReport, issue: str) -> None:
    if issue not in report.invalid_bindings:
        report.invalid_bindings.append(issue)
    _block(report, issue)


def _block(report: PresentationReadinessReport, issue: str) -> None:
    if issue not in report.blocking:
        report.blocking.append(issue)


def _warn(report: PresentationReadinessReport, issue: str) -> None:
    if issue not in report.warnings:
        report.warnings.append(issue)
