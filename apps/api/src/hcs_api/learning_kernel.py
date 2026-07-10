"""Design-time learning state planning for the State-Evidence Kernel."""

from __future__ import annotations

from .models import LearningGoal, LearningState, LearningStatePlan, LearningTransition, LessonProfile, TeachingCandidates


def build_learning_state_plan(
    profile: LessonProfile,
    candidates: TeachingCandidates,
    language_items: list | None = None,
) -> LearningStatePlan:
    """Create source-derived states and goals; no blueprint or renderer data is read."""
    vocabulary = [item["word"] for item in candidates.core_vocabulary if item.get("word")]
    route = candidates.route_hint or "mixed_lesson"
    plan = LearningStatePlan(
        lesson_title=profile.lesson_title,
        route_hint=route,
        learner_level=profile.learner_level,
        language_background=profile.scaffolding_language,
        topic_domain=profile.lesson_type,
        prior_knowledge_assumptions=["Learners can follow teacher modeling with scaffold support."],
        constraints=[f"Use {profile.scaffolding_language} only as support; Chinese remains the target language."],
        risks=["Do not require open production before recognition is established."],
    )
    if route == "greeting_lesson" or not vocabulary:
        _build_greeting_plan(plan, vocabulary or ["你好", "您好", "你", "您"])
    else:
        _build_recognition_plan(plan, vocabulary[:4])
    return plan


def _goal(
    goal_id: str,
    description: str,
    skill_focus: str,
    target_language: list[str],
    target_state: str,
) -> LearningGoal:
    return LearningGoal(
        id=goal_id,
        description=description,
        skill_focus=skill_focus,
        target_language=target_language,
        expected_behavior=description,
        difficulty="beginner",
        success_criteria=["The learner demonstrates the observable behavior with the target language."],
        required_state_to_reach=target_state,
    )


def _build_greeting_plan(plan: LearningStatePlan, vocabulary: list[str]) -> None:
    plan.states = [
        LearningState(state_id="unseen_greeting", state_type="unseen", target_items=vocabulary),
        LearningState(state_id="noticed_greeting", state_type="noticed", target_items=vocabulary, prerequisites=["unseen_greeting"]),
        LearningState(state_id="recognized_nihao", state_type="recognized", target_items=["你好"], prerequisites=["noticed_greeting"]),
        LearningState(state_id="recognized_ninhao", state_type="recognized", target_items=["您好"], prerequisites=["noticed_greeting"]),
        LearningState(state_id="understood_politeness", state_type="understood", target_items=["你好", "您好"], prerequisites=["recognized_nihao", "recognized_ninhao"]),
        LearningState(state_id="controlled_dialogue", state_type="controlled_production", target_items=["你好", "您好"], prerequisites=["understood_politeness"]),
    ]
    plan.learning_goals = [
        _goal("goal_recognize_nihao", "Recognize 你好 as a greeting.", "recognition", ["你好"], "recognized_nihao"),
        _goal("goal_recognize_ninhao", "Recognize 您好 as a polite greeting.", "recognition", ["您好"], "recognized_ninhao"),
        _goal("goal_understand_politeness", "Choose an appropriate greeting for a social relationship.", "understanding", ["你好", "您好"], "understood_politeness"),
        _goal("goal_produce_greeting", "Produce an appropriate greeting in a controlled dialogue.", "production", ["你好", "您好"], "controlled_dialogue"),
    ]
    plan.transitions = [
        LearningTransition(from_state="unseen_greeting", to_state="noticed_greeting", transition_intent="first_exposure", transition_policy="exposure_only"),
        LearningTransition(from_state="noticed_greeting", to_state="recognized_nihao", transition_intent="recognition", required_evidence_ids=["ev_recognize_nihao"]),
        LearningTransition(from_state="noticed_greeting", to_state="recognized_ninhao", transition_intent="recognition", required_evidence_ids=["ev_recognize_ninhao"]),
        LearningTransition(from_state="recognized_nihao", to_state="understood_politeness", transition_intent="understanding", required_evidence_ids=["ev_understand_politeness"]),
        LearningTransition(from_state="understood_politeness", to_state="controlled_dialogue", transition_intent="controlled_production", required_evidence_ids=["ev_produce_greeting"]),
    ]


def _build_recognition_plan(plan: LearningStatePlan, vocabulary: list[str]) -> None:
    plan.states = [
        LearningState(state_id="unseen", state_type="unseen", target_items=vocabulary),
        LearningState(state_id="noticed", state_type="noticed", target_items=vocabulary, prerequisites=["unseen"]),
        LearningState(state_id="recognized", state_type="recognized", target_items=vocabulary, prerequisites=["noticed"]),
    ]
    plan.learning_goals = [_goal("goal_recognize", "Recognize the core vocabulary.", "recognition", vocabulary, "recognized")]
    plan.transitions = [
        LearningTransition(from_state="unseen", to_state="noticed", transition_intent="first_exposure", transition_policy="exposure_only"),
        LearningTransition(from_state="noticed", to_state="recognized", transition_intent="recognition", required_evidence_ids=["ev_recognize"]),
    ]
