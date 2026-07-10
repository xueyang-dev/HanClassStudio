"""Evidence planning: learning goals become observable evidence contracts."""

from __future__ import annotations

from .models import EvidencePlan, EvidenceSpec, LearningGoal, LearningStatePlan


def build_evidence_plan(
    state_plan: LearningStatePlan,
    learner_level: str = "zero_beginner",
    scaffold_lang: str = "English",
) -> EvidencePlan:
    """Derive one evidence contract per goal; activities are deliberately not considered here."""
    return EvidencePlan(evidence_specs=[_evidence_for_goal(goal, state_plan, learner_level) for goal in state_plan.goals])


def _evidence_for_goal(goal: LearningGoal, state_plan: LearningStatePlan, learner_level: str) -> EvidenceSpec:
    evidence_id = f"ev_{goal.goal_id.removeprefix('goal_')}"
    is_beginner = _is_beginner(learner_level)
    if goal.goal_type == "recognition":
        evidence_type, method, mode = "deterministic_choice", "learner_response", "deterministic"
    elif goal.goal_type == "understanding":
        evidence_type, method, mode = "deterministic_choice", "scenario_choice", "deterministic"
    elif goal.goal_type == "production":
        # A zero-beginner lesson may collect preparatory listening evidence; alignment reports this limitation.
        evidence_type, method, mode = ("listen_choose", "learner_response", "deterministic") if is_beginner else ("constrained_production", "spoken_or_written_response", "teacher")
    elif goal.goal_type == "communicative":
        evidence_type, method, mode = "semantic_judgment", "teacher_observation", "teacher"
    else:
        evidence_type, method, mode = "teacher_observation", "teacher_observation", "teacher"

    state_from = next(
        (transition.from_state for transition in state_plan.transitions if transition.to_state == goal.required_state_to_reach),
        "",
    )
    return EvidenceSpec(
        id=evidence_id,
        goal_id=goal.goal_id,
        evidence_type=evidence_type,
        observable_behavior=goal.expected_behavior or goal.description,
        collection_method=method,
        acceptable_response={"min_correct": 1, "attempts_allowed": 2},
        teacher_observation_notes="Observe the learner's response and re-model if needed." if method == "teacher_observation" else "",
        confidence_level="high" if mode == "deterministic" else "teacher_review",
        limitations=["Preparatory recognition evidence only; confirm production later."] if goal.goal_type == "production" and is_beginner else [],
        state_from=state_from,
        state_to=goal.required_state_to_reach,
        target_items=goal.target_items,
        assessment_mode=mode,
        collector_refs=[f"act_{evidence_id.removeprefix('ev_')}"] ,
        expected_behavior={"target_language": goal.target_items},
        confidence_policy={"deterministic": mode == "deterministic", "ai_required": False, "teacher_override": mode != "deterministic"},
        failure_action={"remediation_type": "rescaffold", "return_to_state": state_from} if goal.goal_type != "recognition" else {},
    )


def _is_beginner(level: str) -> bool:
    normalized = (level or "").lower()
    return "beginner" in normalized or normalized in {"zb", "a1"}
