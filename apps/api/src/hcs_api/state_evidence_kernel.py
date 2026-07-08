"""State-Evidence Kernel — teaching kernel: state plan, evidence, activity, alignment."""

from __future__ import annotations

import re
from typing import Any

from .models import (
    ActivityPlan, EvidenceAlignmentReport, EvidencePlan, EvidenceSpec,
    LearningActivity, LearningGoal, LearningState, LearningStatePlan,
    LearningTransition, LessonBlueprint, LessonProfile, TeachingCandidates,
)


# ── 1. Learning State Plan Builder ──


def build_learning_state_plan(
    profile: LessonProfile,
    candidates: TeachingCandidates,
    language_items: list | None = None,
) -> LearningStatePlan:
    """Build learning state plan from lesson profile and teaching candidates."""
    route = candidates.route_hint if candidates else "mixed_lesson"
    plan = LearningStatePlan(lesson_title=profile.lesson_title, route_hint=route)

    # Determine target vocabulary
    vocab_words = [v["word"] for v in (candidates.core_vocabulary if candidates else [])]

    # Build default state DAG for greeting_lesson
    if route == "greeting_lesson" or not vocab_words:
        _build_greeting_state_plan(plan, vocab_words)
    else:
        _build_default_state_plan(plan, vocab_words)

    return plan


def _build_greeting_state_plan(plan: LearningStatePlan, vocab: list[str]) -> None:
    items = vocab or ["你好", "您好", "你", "您"]

    # States
    plan.states = [
        LearningState(state_id="unseen_greeting", state_type="unseen", target_items=items,
                       learner_claim="Learner has not been exposed to Chinese greetings."),
        LearningState(state_id="noticed_greeting", state_type="noticed", target_items=items,
                       learner_claim="Learner has noticed the existence of Chinese greetings.",
                       prerequisites=["unseen_greeting"], design_confidence=0.9),
        LearningState(state_id="recognized_nihao", state_type="recognized", target_items=["你好"],
                       learner_claim="Learner can recognize the meaning of 你好 (hello).",
                       prerequisites=["noticed_greeting"], design_confidence=0.8),
        LearningState(state_id="recognized_ninhao", state_type="recognized", target_items=["您好"],
                       learner_claim="Learner can recognize 您好 as polite greeting.",
                       prerequisites=["noticed_greeting"], design_confidence=0.75),
        LearningState(state_id="understood_politeness", state_type="understood", target_items=["您好", "你"],
                       learner_claim="Learner understands when to use 你 vs 您好.",
                       prerequisites=["recognized_nihao", "recognized_ninhao"], design_confidence=0.7),
        LearningState(state_id="controlled_dialogue", state_type="controlled_production", target_items=["你好", "您好"],
                       learner_claim="Learner can produce appropriate greeting in controlled scenario.",
                       prerequisites=["understood_politeness"], design_confidence=0.6),
    ]

    # Goals
    plan.goals = [
        LearningGoal(goal_id="goal_recognize_nihao", goal_type="recognition", target_items=["你好"],
                      success_claim="Learner recognizes 你好 as greeting.",
                      required_state_to_reach="recognized_nihao"),
        LearningGoal(goal_id="goal_recognize_ninhao", goal_type="recognition", target_items=["您好"],
                      success_claim="Learner recognizes 您好 as polite greeting.",
                      required_state_to_reach="recognized_ninhao"),
        LearningGoal(goal_id="goal_understand_politeness", goal_type="understanding", target_items=["您", "你"],
                      success_claim="Learner understands contrast between 你 and 您好.",
                      required_state_to_reach="understood_politeness"),
        LearningGoal(goal_id="goal_produce_greeting", goal_type="production", target_items=["你好", "您好"],
                      success_claim="Learner can produce appropriate greeting.",
                      required_state_to_reach="controlled_dialogue"),
    ]

    # Transitions
    plan.transitions = [
        LearningTransition(from_state="unseen_greeting", to_state="noticed_greeting",
                            transition_intent="first_exposure", transition_policy="exposure_only"),
        LearningTransition(from_state="noticed_greeting", to_state="recognized_nihao",
                            transition_intent="vocabulary_intro", required_evidence_ids=["ev_recognize_nihao"]),
        LearningTransition(from_state="noticed_greeting", to_state="recognized_ninhao",
                            transition_intent="vocabulary_intro_polite", required_evidence_ids=["ev_recognize_ninhao"]),
        LearningTransition(from_state="recognized_nihao", to_state="understood_politeness",
                            transition_intent="politeness_contrast", required_evidence_ids=["ev_politeness_scene_choice"]),
        LearningTransition(from_state="recognized_ninhao", to_state="understood_politeness",
                            transition_intent="politeness_contrast", required_evidence_ids=["ev_politeness_scene_choice"]),
        LearningTransition(from_state="understood_politeness", to_state="controlled_dialogue",
                            transition_intent="controlled_production", required_evidence_ids=["ev_dialogue_choice"]),
    ]


def _build_default_state_plan(plan: LearningStatePlan, vocab: list[str]) -> None:
    """Generic state plan for non-greeting lessons."""
    items = vocab[:4]
    plan.states = [
        LearningState(state_id="unseen", state_type="unseen", target_items=items),
        LearningState(state_id="noticed", state_type="noticed", target_items=items, prerequisites=["unseen"]),
        LearningState(state_id="recognized", state_type="recognized", target_items=items, prerequisites=["noticed"]),
    ]
    plan.goals = [LearningGoal(goal_id="goal_recognize", goal_type="recognition", target_items=items,
                                success_claim=f"Recognize core vocabulary: {items}",
                                required_state_to_reach="recognized")]
    plan.transitions = [
        LearningTransition(from_state="unseen", to_state="noticed", transition_intent="first_exposure"),
        LearningTransition(from_state="noticed", to_state="recognized", transition_intent="vocabulary_intro"),
    ]


# ── 2. Evidence Plan Builder ──


def build_evidence_plan(
    state_plan: LearningStatePlan,
    learner_level: str = "zero_beginner",
    scaffold_lang: str = "English",
) -> EvidencePlan:
    """Build evidence specs from state plan transitions."""
    plan = EvidencePlan()
    is_zb = learner_level in ("zero_beginner",)
    seen_evidence: set[str] = set()

    for transition in state_plan.transitions:
        if transition.transition_intent == "first_exposure":
            continue

        target_items = _items_for_transition(state_plan, transition)

        # Skip if we've already generated this evidence
        if transition.required_evidence_ids:
            ev_id = transition.required_evidence_ids[0]
            if ev_id in seen_evidence:
                continue
            seen_evidence.add(ev_id)

        if transition.transition_intent in ("vocabulary_intro", "vocabulary_intro_polite"):
            ev = EvidenceSpec(
                evidence_id=f"ev_{transition.to_state}",
                state_from=transition.from_state, state_to=transition.to_state,
                learning_claim=f"Learner recognizes target vocabulary: {target_items}",
                target_items=target_items,
                evidence_type="deterministic_choice" if is_zb else "constrained_production",
                assessment_mode="deterministic",
                collector_refs=[f"act_{transition.to_state}_recognition"],
                expected_behavior={"select": target_items[0]} if target_items else {},
                pass_criteria={"min_correct": 1, "attempts_allowed": 2},
            )
            if transition.required_evidence_ids:
                ev.evidence_id = transition.required_evidence_ids[0]
            plan.evidence_specs.append(ev)

        elif transition.transition_intent == "politeness_contrast":
            plan.evidence_specs.append(EvidenceSpec(
                evidence_id=transition.required_evidence_ids[0] if transition.required_evidence_ids else "ev_politeness_scene_choice",
                state_from=transition.from_state or "", state_to=transition.to_state,
                learning_claim="Learner chooses correct greeting for teacher vs friend scenario.",
                target_items=["您好", "你好"],
                evidence_type="deterministic_choice", assessment_mode="deterministic",
                collector_refs=["act_politeness_scene_choice"],
                expected_behavior={"select": "您好", "reject": ["你好"]},
                pass_criteria={"min_correct": 1, "attempts_allowed": 2},
                failure_action={"remediation_type": "rescaffold", "recommended_activity": "act_scene_contrast", "return_to_state": transition.from_state or ""},
            ))

        elif transition.transition_intent == "controlled_production":
            plan.evidence_specs.append(EvidenceSpec(
                evidence_id=transition.required_evidence_ids[0] if transition.required_evidence_ids else "ev_dialogue_choice",
                state_from=transition.from_state or "", state_to=transition.to_state,
                learning_claim="Learner produces correct greeting in dialogue.",
                target_items=["你好", "您好"],
                evidence_type="listen_choose" if is_zb else "constrained_production",
                assessment_mode="deterministic",
                collector_refs=["act_dialogue_choice"],
                expected_behavior={"correct_responses": ["你好！", "您好！"]},
                pass_criteria={"min_correct": 1, "attempts_allowed": 3},
                failure_action={"remediation_type": "rescaffold", "recommended_activity": "act_dialogue_practice", "return_to_state": "understood_politeness"},
            ))

        else:
            # Default evidence for unknown transition intents
            plan.evidence_specs.append(EvidenceSpec(
                evidence_id=f"ev_{transition.to_state}",
                state_from=transition.from_state or "", state_to=transition.to_state,
                learning_claim=f"Evidence for transition: {transition.transition_intent}",
                target_items=target_items,
                evidence_type="teacher_observation",
                assessment_mode="teacher",
                collector_refs=[f"act_{transition.to_state}_observation"],
            ))

    return plan


def _items_for_transition(state_plan: LearningStatePlan, transition: LearningTransition) -> list[str]:
    """Get target items for a given transition."""
    for s in state_plan.states:
        if s.state_id == transition.to_state:
            return s.target_items
    return []


# ── 3. Activity Plan Builder ──


def build_activity_plan(
    evidence_plan: EvidencePlan,
    learner_level: str = "zero_beginner",
    scaffold_lang: str = "English",
) -> ActivityPlan:
    """Build learning activities from evidence specs."""
    plan = ActivityPlan()
    is_zb = learner_level in ("zero_beginner",)

    for ev in evidence_plan.evidence_specs:
        for collector_ref in ev.collector_refs:
            act_type = _evidence_to_activity_type(ev.evidence_type, is_zb)
            plan.activities.append(LearningActivity(
                activity_id=collector_ref,
                activity_type=act_type,
                collects_evidence=[ev.evidence_id],
                allowed_presentation_modes=["html_interactive", "pptx_classroom", "teacher_observation"],
                learner_level_fit=[learner_level],
                scaffolding_level="high" if is_zb else "medium",
            ))

    return plan


def _evidence_to_activity_type(evidence_type: str, is_zb: bool) -> str:
    mapping = {
        "deterministic_choice": "scene_choice" if is_zb else "multiple_choice",
        "matching": "match_pairs",
        "listen_choose": "listen_choose",
        "constrained_production": "drag_sentence" if not is_zb else "listen_choose",
        "role_play": "role_play_scene",
        "semantic_judgment": "open_response",
        "teacher_observation": "teacher_observation",
    }
    return mapping.get(evidence_type, "scene_choice")


# ── 4. Evidence Alignment Checker ──


def check_evidence_alignment(
    state_plan: LearningStatePlan,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    learner_level: str = "zero_beginner",
) -> EvidenceAlignmentReport:
    """Check Goal-Evidence-Activity alignment per white paper quality gates + enforcement rules."""
    report = EvidenceAlignmentReport()
    evidence_ids = {e.evidence_id for e in evidence_plan.evidence_specs}
    activity_ids = {a.activity_id for a in activity_plan.activities}

    # Build collector -> evidence reverse map
    collector_to_evidence: dict[str, set[str]] = {}
    for a in activity_plan.activities:
        collector_to_evidence[a.activity_id] = set(a.collects_evidence)

    # ── 0. Transition without required evidence ──
    for t in state_plan.transitions:
        if not t.required_evidence_ids:
            is_exposure = t.transition_intent == "first_exposure"
            allow_no_evidence = t.metadata.get("allow_without_evidence", False) or t.transition_policy == "exposure_only"
            if is_exposure and allow_no_evidence:
                continue  # first_exposure + exposure_only = intentional no-evidence transition
            if not is_exposure and not allow_no_evidence:
                msg = f"Transition '{t.from_state}' -> '{t.to_state}' ({t.transition_intent}) lacks required evidence. Use transition_policy=exposure_only or metadata.allow_without_evidence=true if intentional."
                report.blocking.append(msg)

    # ── 1. Production / communicative evidence check ──
    production_goals = [g for g in state_plan.goals if g.goal_type in ("production", "transfer")]
    for goal in production_goals:
        goal_satisfied_by: list[str] = []
        for t in state_plan.transitions:
            if t.to_state == goal.required_state_to_reach:
                for ev_id in t.required_evidence_ids:
                    for ev in evidence_plan.evidence_specs:
                        if ev.evidence_id == ev_id:
                            goal_satisfied_by.append(ev.evidence_type)
        only_low_level = all(et in ("deterministic_choice", "listen_choose", "matching") for et in goal_satisfied_by)
        if only_low_level:
            if learner_level in ("zero_beginner",):
                # Zero_beginner: downgrade acceptable via teacher_observation warning
                msg = f"Production goal '{goal.goal_id}' satisfied only by low-level evidence: {goal_satisfied_by}. Recommend teacher_observation or downgrade goal type."
                report.warnings.append(msg)
            else:
                msg = f"Production goal '{goal.goal_id}' satisfied only by low-level evidence: {goal_satisfied_by}. Needs constrained_production, teacher_observation, or role_play."
                report.blocking.append(msg)

    # ── 2. Collector consistency check ──
    for ev in evidence_plan.evidence_specs:
        for ref in ev.collector_refs:
            if ref not in activity_ids:
                msg = f"Evidence '{ev.evidence_id}' references collector '{ref}' which has no matching activity"
                report.blocking.append(msg)
    for act in activity_plan.activities:
        for ev_id in act.collects_evidence:
            if ev_id not in evidence_ids:
                msg = f"Activity '{act.activity_id}' collects evidence '{ev_id}' which does not exist"
                report.blocking.append(msg)

    # ── 3. Expanded Presentation Independence Check ──
    FORBIDDEN_PRESENTATION_KEYS = [
        "slide_id", "slide_ref", "page", "page_number",
        "pptx_layout", "html_component_id", "component_id", "layout_variant",
    ]
    for artifact_name, artifact_obj in [
        ("learning_state_plan", state_plan),
        ("evidence_plan", evidence_plan),
        ("activity_plan", activity_plan),
    ]:
        text = str(artifact_obj.model_dump(mode="json"))
        for key in FORBIDDEN_PRESENTATION_KEYS:
            if key in text:
                msg = f"{artifact_name} contains presentation reference '{key}'"
                report.presentation_independence.append(msg)
                report.blocking.append(msg)

    # ── 4. Original checks (Goal Orphan, Evidence Orphan, etc.) ──
    for goal in state_plan.goals:
        found = False
        for ev in evidence_plan.evidence_specs:
            for t in state_plan.transitions:
                if t.to_state == goal.required_state_to_reach and ev.evidence_id in t.required_evidence_ids:
                    found = True
                    break
        if not found:
            msg = f"Goal '{goal.goal_id}' ({goal.success_claim[:60]}) has no evidence spec"
            report.goal_orphans.append(msg)
            report.blocking.append(msg)

    for ev in evidence_plan.evidence_specs:
        collectors = [a for a in activity_plan.activities if ev.evidence_id in a.collects_evidence]
        if not collectors:
            msg = f"Evidence '{ev.evidence_id}' has no learning activity"
            report.evidence_orphans.append(msg)
            report.blocking.append(msg)

    for act in activity_plan.activities:
        if learner_level in ("zero_beginner",):
            unsuitable = {"open_response", "role_play_scene", "drag_sentence"}
            if act.activity_type in unsuitable:
                msg = f"Activity '{act.activity_id}' type '{act.activity_type}' not suitable for {learner_level}"
                report.activity_suitability.append(msg)
                report.blocking.append(msg)

    for ev in evidence_plan.evidence_specs:
        if ev.evidence_type == "teacher_observation" and not ev.failure_action:
            report.teacher_observation_readiness.append(f"Teacher observation '{ev.evidence_id}' has no remediation notes")
            report.warnings.append(f"Teacher observation '{ev.evidence_id}' has no remediation notes")

    for ev in evidence_plan.evidence_specs:
        if ev.evidence_type == "semantic_judgment":
            cp = ev.confidence_policy
            if not cp.get("teacher_override") and not cp.get("deterministic"):
                report.semantic_safety.append(f"Semantic evidence '{ev.evidence_id}' lacks fallback or teacher override")
                report.warnings.append(f"Semantic evidence '{ev.evidence_id}' lacks fallback")

    # Derive state
    if report.blocking:
        report.state = "blocked"
    elif report.warnings:
        report.state = "warning"
    else:
        report.state = "pass"
    if not report.passed:
        report.passed.append(f"Evidence alignment: {len(evidence_plan.evidence_specs)} specs, {len(activity_plan.activities)} activities, {len(report.blocking)} blocking")
    return report


# ── 5. Integration Helper ──


def build_full_kernel(
    profile: LessonProfile,
    candidates: TeachingCandidates,
    language_items: list | None = None,
    learner_level: str = "zero_beginner",
    scaffold_lang: str = "Arabic",
) -> tuple[LearningStatePlan, EvidencePlan, ActivityPlan, EvidenceAlignmentReport]:
    """Build full State-Evidence Kernel: plan → evidence → activity → alignment check."""
    state_plan = build_learning_state_plan(profile, candidates, language_items)
    evidence_plan = build_evidence_plan(state_plan, learner_level, scaffold_lang)
    activity_plan = build_activity_plan(evidence_plan, learner_level, scaffold_lang)
    alignment = check_evidence_alignment(state_plan, evidence_plan, activity_plan, learner_level)
    return state_plan, evidence_plan, activity_plan, alignment
