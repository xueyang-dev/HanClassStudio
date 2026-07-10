"""Focused tests for the design-time State-Evidence Kernel quality gate."""

import pytest

from hcs_api.evidence_alignment import check_evidence_alignment
from pydantic import ValidationError
from hcs_api.models import (
    ActivityPlan,
    EvidencePlan,
    EvidenceSpec,
    LearningActivity,
    LearningGoal,
    LearningStatePlan,
)


def _plans(*, goal: LearningGoal | None = None, evidence: EvidenceSpec | None = None, activity: LearningActivity | None = None):
    goal = goal or LearningGoal(id="goal_1", description="Recognize 你好", skill_focus="recognition", target_language=["你好"])
    evidence = evidence or EvidenceSpec(id="ev_1", goal_id=goal.id, observable_behavior="Select 你好", collector_refs=["act_1"])
    activity = activity or LearningActivity(id="act_1", evidence_ids=[evidence.id], activity_type="scene_choice")
    return LearningStatePlan(learning_goals=[goal]), EvidencePlan(evidence_specs=[evidence]), ActivityPlan(activities=[activity])


def test_every_goal_has_evidence() -> None:
    state, evidence, activity = _plans()
    evidence.evidence_specs = []
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "blocked"
    assert report.goal_orphans


def test_every_evidence_has_valid_goal() -> None:
    state, evidence, activity = _plans(evidence=EvidenceSpec(id="ev_1", goal_id="missing", collector_refs=["act_1"]))
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "blocked"
    assert "invalid goal" in " ".join(report.blocking)


def test_every_evidence_is_collected_by_activity() -> None:
    state, evidence, activity = _plans()
    activity.activities = []
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "blocked"
    assert report.evidence_orphans


def test_every_activity_has_valid_evidence() -> None:
    state, evidence, activity = _plans(activity=LearningActivity(id="act_1", evidence_ids=["missing"], activity_type="scene_choice"))
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "blocked"
    assert "does not exist" in " ".join(report.blocking)


def test_kernel_ids_must_be_machine_readable_and_unique() -> None:
    with pytest.raises(ValidationError):
        LearningGoal(id="goal-one", description="Recognize 你好")

    state, evidence, activity = _plans()
    state.learning_goals.append(LearningGoal(id="goal_1", description="Recognize 您好"))
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "blocked"
    assert "Duplicate goal id" in " ".join(report.blocking)


def test_evidence_spec_rejects_slide_or_layout_references() -> None:
    state, evidence, activity = _plans(evidence=EvidenceSpec(id="ev_1", goal_id="goal_1", collector_refs=["act_1"], expected_behavior={"slide_id": 3}))
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "blocked"
    assert report.presentation_independence


def test_activity_rejects_visual_layout_details() -> None:
    state, evidence, activity = _plans(activity=LearningActivity(id="act_1", evidence_ids=["ev_1"], activity_type="scene_choice", classroom_notes="Use a blue font."))
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "blocked"
    assert report.presentation_independence


def test_semantic_evidence_requires_teacher_override_or_fallback() -> None:
    semantic = EvidenceSpec(id="ev_1", goal_id="goal_1", evidence_type="semantic_judgment", collector_refs=["act_1"], confidence_policy={"teacher_override": False})
    state, evidence, activity = _plans(evidence=semantic, activity=LearningActivity(id="act_1", evidence_ids=["ev_1"], activity_type="open_response"))
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "warning"
    assert report.semantic_safety


def test_beginner_lesson_warns_on_production_before_recognition() -> None:
    goal = LearningGoal(id="goal_1", description="Say 你好", skill_focus="production", target_language=["你好"])
    state, evidence, activity = _plans(goal=goal, evidence=EvidenceSpec(id="ev_1", goal_id="goal_1", evidence_type="constrained_production", collector_refs=["act_1"]))
    report = check_evidence_alignment(state, evidence, activity, "beginner")
    assert report.state == "warning"
    assert "before recognition" in " ".join(report.warnings)


def test_communicative_goal_warns_if_only_multiple_choice() -> None:
    goal = LearningGoal(id="goal_1", description="Greet a teacher", skill_focus="communicative", target_language=["您好"])
    state, evidence, activity = _plans(goal=goal, evidence=EvidenceSpec(id="ev_1", goal_id="goal_1", evidence_type="deterministic_choice", collector_refs=["act_1"]))
    report = check_evidence_alignment(state, evidence, activity)
    assert report.state == "warning"
    assert "Communicative goal" in " ".join(report.warnings)


def test_evidence_alignment_report_generates_pass_warning_blocked() -> None:
    state, evidence, activity = _plans()
    assert check_evidence_alignment(state, evidence, activity).state == "pass"

    warning_goal = LearningGoal(id="goal_2", description="Greet a teacher", skill_focus="communicative")
    warning_state, warning_evidence, warning_activity = _plans(
        goal=warning_goal,
        evidence=EvidenceSpec(id="ev_2", goal_id="goal_2", evidence_type="deterministic_choice", collector_refs=["act_2"]),
        activity=LearningActivity(id="act_2", evidence_ids=["ev_2"], activity_type="scene_choice"),
    )
    assert check_evidence_alignment(warning_state, warning_evidence, warning_activity).state == "warning"

    blocked_state, blocked_evidence, blocked_activity = _plans()
    blocked_activity.activities = []
    assert check_evidence_alignment(blocked_state, blocked_evidence, blocked_activity).state == "blocked"
