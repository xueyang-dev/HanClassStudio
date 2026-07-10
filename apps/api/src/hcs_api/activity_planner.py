"""Activity planning: evidence contracts select classroom interactions."""

from __future__ import annotations

from .models import ActivityPlan, EvidencePlan, EvidenceSpec, LearningActivity


def build_activity_plan(
    evidence_plan: EvidencePlan,
    learner_level: str = "zero_beginner",
    scaffold_lang: str = "English",
) -> ActivityPlan:
    """Create one evidence-collecting activity per evidence spec, with no layout decisions."""
    return ActivityPlan(activities=[_activity_for_evidence(evidence, learner_level) for evidence in evidence_plan.evidence_specs])


def _activity_for_evidence(evidence: EvidenceSpec, learner_level: str) -> LearningActivity:
    teacher_only = evidence.collection_method == "teacher_observation" or evidence.evidence_type == "teacher_observation"
    activity_type = {
        "deterministic_choice": "scene_choice",
        "listen_choose": "listen_choose",
        "constrained_production": "controlled_response",
        "semantic_judgment": "teacher_observation",
        "teacher_observation": "teacher_observation",
        "matching": "match_pairs",
        "role_play": "role_play",
    }.get(evidence.evidence_type, "guided_response")
    return LearningActivity(
        id=evidence.collector_refs[0] if evidence.collector_refs else f"act_{evidence.evidence_id}",
        evidence_ids=[evidence.evidence_id],
        activity_type=activity_type,
        learner_action="Respond to the prompt using the target language." if not teacher_only else "",
        teacher_action="Observe, record evidence, and re-model when needed.",
        interaction_mode="teacher_led" if teacher_only else "individual",
        input_type="teacher_prompt" if teacher_only else "prompt",
        output_type="teacher_notes" if teacher_only else "selection" if evidence.assessment_mode == "deterministic" else "response",
        fallback_activity="Teacher models the contrast and repeats the prompt.",
        classroom_notes="Keep the task oral and scaffolded for beginners.",
        learner_facing=not teacher_only,
        allowed_presentation_modes=["teacher_observation"] if teacher_only else ["html_interactive", "pptx_classroom", "teacher_observation"],
        learner_level_fit=[learner_level],
        scaffolding_level="high" if _is_beginner(learner_level) else "medium",
    )


def _is_beginner(level: str) -> bool:
    return "beginner" in (level or "").lower() or (level or "").lower() in {"zb", "a1"}
