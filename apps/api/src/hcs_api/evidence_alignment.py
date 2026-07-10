"""Quality gate for the design-time State → Evidence → Activity contracts."""

from __future__ import annotations

import re
from typing import Any

from .models import ActivityPlan, EvidenceAlignmentReport, EvidencePlan, LearningActivity, LearningStatePlan


FORBIDDEN_EVIDENCE_TERMS = {
    "slide_id", "slide id", "page_number", "page number", "component_id", "component id",
    "layout", "font", "color", "coordinate", "x_position", "y_position",
}
FORBIDDEN_ACTIVITY_TERMS = FORBIDDEN_EVIDENCE_TERMS | {"visual_style", "css", "pixel"}
LOW_LEVEL_EVIDENCE = {"deterministic_choice", "listen_choose", "matching"}
MACHINE_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def check_evidence_alignment(
    state_plan: LearningStatePlan,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    learner_level: str = "zero_beginner",
) -> EvidenceAlignmentReport:
    """Return a pass/warning/blocked report without making presentation decisions."""
    report = EvidenceAlignmentReport()
    goals = {goal.goal_id: goal for goal in state_plan.goals}
    evidence = {spec.evidence_id: spec for spec in evidence_plan.evidence_specs}
    activities = {activity.activity_id: activity for activity in activity_plan.activities}

    _validate_ids(report, "Goal", [goal.goal_id for goal in state_plan.goals])
    _validate_ids(report, "Evidence", [spec.evidence_id for spec in evidence_plan.evidence_specs])
    _validate_ids(report, "Activity", [activity.activity_id for activity in activity_plan.activities])

    for transition in state_plan.transitions:
        exempt = transition.transition_policy == "exposure_only" or transition.metadata.get("allow_without_evidence")
        if not transition.required_evidence_ids and not exempt:
            _block(report, f"Transition '{transition.from_state}' -> '{transition.to_state}' lacks required evidence.")

    for goal in state_plan.goals:
        goal_evidence = [spec for spec in evidence.values() if spec.goal_id == goal.goal_id]
        if not goal_evidence:
            message = f"Goal '{goal.goal_id}' has no evidence spec."
            report.goal_orphans.append(message)
            _block(report, message)

    for spec in evidence.values():
        if not spec.goal_id:
            _block(report, f"Evidence '{spec.evidence_id}' is missing goal_id.")
        elif spec.goal_id not in goals:
            _block(report, f"Evidence '{spec.evidence_id}' references invalid goal '{spec.goal_id}'.")
        if _contains_forbidden_reference(spec.model_dump(mode="json"), FORBIDDEN_EVIDENCE_TERMS):
            message = f"Evidence '{spec.evidence_id}' contains presentation or layout details."
            report.presentation_independence.append(message)
            _block(report, message)
        collecting = [activity for activity in activities.values() if spec.evidence_id in activity.evidence_ids]
        if not collecting:
            message = f"Evidence '{spec.evidence_id}' has no learning activity."
            report.evidence_orphans.append(message)
            _block(report, message)
        for collector in spec.collector_refs:
            if collector not in activities:
                _block(report, f"Evidence '{spec.evidence_id}' references collector '{collector}' which has no matching activity.")
        if spec.collection_method == "teacher_observation" or spec.evidence_type == "teacher_observation":
            if any(activity.learner_facing for activity in collecting):
                _block(report, f"Teacher-only evidence '{spec.evidence_id}' appears in learner-facing activity output.")
            if not spec.teacher_observation_notes:
                report.teacher_observation_readiness.append(f"Teacher observation '{spec.evidence_id}' has no observation notes.")
                _warn(report, f"Teacher observation '{spec.evidence_id}' has no observation notes.")

    for activity in activities.values():
        if _contains_forbidden_reference(activity.model_dump(mode="json"), FORBIDDEN_ACTIVITY_TERMS):
            message = f"Activity '{activity.activity_id}' contains visual layout or styling details."
            report.presentation_independence.append(message)
            _block(report, message)
        if not activity.evidence_ids:
            _block(report, f"Activity '{activity.activity_id}' does not collect evidence.")
        for evidence_id in activity.evidence_ids:
            if evidence_id not in evidence:
                _block(report, f"Activity '{activity.activity_id}' collects evidence '{evidence_id}' which does not exist.")

    _check_semantic_safety(report, evidence_plan, activity_plan)
    _check_production_evidence(report, state_plan, evidence_plan, learner_level)
    _check_beginner_sequence(report, state_plan, learner_level)
    _check_communicative_evidence(report, state_plan, evidence_plan)

    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    report.passed.append(
        f"Evidence alignment: {len(goals)} goals, {len(evidence)} evidence specs, {len(activities)} activities."
    )
    return report


def _check_semantic_safety(report: EvidenceAlignmentReport, evidence_plan: EvidencePlan, activity_plan: ActivityPlan) -> None:
    for spec in evidence_plan.evidence_specs:
        spec_activities = [activity for activity in activity_plan.activities if spec.evidence_id in activity.evidence_ids]
        open_ended = spec.collection_method in {"open_response", "open_ended"} or any(
            activity.activity_type == "open_response" for activity in spec_activities
        )
        if spec.evidence_type not in {"semantic_judgment", "role_play"} and not open_ended:
            continue
        has_override = bool(spec.confidence_policy.get("teacher_override"))
        has_fallback = bool(spec.failure_action) or any(activity.fallback_activity for activity in spec_activities)
        if not has_override and not has_fallback:
            message = f"Semantic evidence '{spec.evidence_id}' lacks teacher override or fallback notes."
            report.semantic_safety.append(message)
            _warn(report, message)


def _check_beginner_sequence(report: EvidenceAlignmentReport, state_plan: LearningStatePlan, learner_level: str) -> None:
    if not _is_beginner(learner_level):
        return
    has_recognition = any(goal.goal_type == "recognition" for goal in state_plan.goals)
    for goal in state_plan.goals:
        if goal.goal_type not in {"production", "communicative", "transfer"} or getattr(goal, "justification", ""):
            continue
        if not has_recognition:
            _warn(report, f"Beginner lesson requires production goal '{goal.goal_id}' before recognition is established.")


def _check_production_evidence(
    report: EvidenceAlignmentReport,
    state_plan: LearningStatePlan,
    evidence_plan: EvidencePlan,
    learner_level: str,
) -> None:
    for goal in state_plan.goals:
        if goal.goal_type not in {"production", "transfer"}:
            continue
        goal_evidence = [spec for spec in evidence_plan.evidence_specs if spec.goal_id == goal.goal_id]
        if goal_evidence and all(spec.evidence_type in LOW_LEVEL_EVIDENCE for spec in goal_evidence):
            message = f"production goal '{goal.goal_id}' is satisfied only by low-level evidence."
            recognition_exists = any(candidate.goal_type == "recognition" for candidate in state_plan.goals)
            if _is_zero_beginner(learner_level) or recognition_exists:
                _warn(report, message)
            else:
                _block(report, message)


def _check_communicative_evidence(report: EvidenceAlignmentReport, state_plan: LearningStatePlan, evidence_plan: EvidencePlan) -> None:
    for goal in state_plan.goals:
        if goal.goal_type != "communicative" or getattr(goal, "justification", ""):
            continue
        goal_evidence = [spec for spec in evidence_plan.evidence_specs if spec.goal_id == goal.goal_id]
        if goal_evidence and all(spec.evidence_type in LOW_LEVEL_EVIDENCE for spec in goal_evidence):
            _warn(report, f"Communicative goal '{goal.goal_id}' is satisfied only by multiple-choice-style evidence.")


def _contains_forbidden_reference(value: Any, forbidden_terms: set[str]) -> bool:
    for text in _walk_text(value):
        normalized = re.sub(r"[_-]+", " ", text.lower())
        if any(term in normalized or term.replace("_", " ") in normalized for term in forbidden_terms):
            return True
    return False


def _walk_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value] + [text for item in value.values() for text in _walk_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _walk_text(item)]
    return [str(value)]


def _is_beginner(level: str) -> bool:
    normalized = (level or "").lower()
    return "beginner" in normalized or normalized in {"zb", "a1"}


def _is_zero_beginner(level: str) -> bool:
    normalized = (level or "").lower()
    return "zero" in normalized or normalized == "zb"


def _validate_ids(report: EvidenceAlignmentReport, label: str, ids: list[str]) -> None:
    seen: set[str] = set()
    for value in ids:
        if not MACHINE_ID.fullmatch(value):
            _block(report, f"{label} id '{value}' must be a non-empty snake_case machine identifier.")
        if value in seen:
            _block(report, f"Duplicate {label.lower()} id '{value}'.")
        seen.add(value)


def _block(report: EvidenceAlignmentReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: EvidenceAlignmentReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
