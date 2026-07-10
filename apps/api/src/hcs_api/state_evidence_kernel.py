"""Backward-compatible entry points for the split State-Evidence Kernel modules."""

from __future__ import annotations

from .activity_planner import build_activity_plan
from .evidence import build_evidence_plan
from .evidence_alignment import check_evidence_alignment
from .learning_kernel import build_learning_state_plan
from .models import ActivityPlan, EvidenceAlignmentReport, EvidencePlan, LearningStatePlan, LessonProfile, TeachingCandidates

__all__ = [
    "build_activity_plan",
    "build_evidence_plan",
    "build_full_kernel",
    "build_learning_state_plan",
    "check_evidence_alignment",
]


def build_full_kernel(
    profile: LessonProfile,
    candidates: TeachingCandidates,
    language_items: list | None = None,
    learner_level: str = "zero_beginner",
    scaffold_lang: str = "English",
) -> tuple[LearningStatePlan, EvidencePlan, ActivityPlan, EvidenceAlignmentReport]:
    """Build State → Evidence → Activity → quality report without reading presentation artifacts."""
    state_plan = build_learning_state_plan(profile, candidates, language_items)
    evidence_plan = build_evidence_plan(state_plan, learner_level, scaffold_lang)
    activity_plan = build_activity_plan(evidence_plan, learner_level, scaffold_lang)
    return state_plan, evidence_plan, activity_plan, check_evidence_alignment(state_plan, evidence_plan, activity_plan, learner_level)
