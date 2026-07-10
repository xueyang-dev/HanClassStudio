"""Shadow-only binding-first presentation compiler.

This module reads the State-Evidence kernel artifacts only.  It intentionally
does not import or read the legacy lesson blueprint or renderer contracts.
"""

from __future__ import annotations

from .models import (
    AbstractPresentationBinding,
    AbstractPresentationBindingPlan,
    ActivityPlan,
    CanonicalPresentationBlueprint,
    EvidenceAlignmentReport,
    EvidencePlan,
    LearningActivity,
    LearningStatePlan,
    PresentationShadowReport,
    PresentationTrace,
    PresentationUnit,
)


KERNEL_SOURCE_ARTIFACTS = [
    "learning/learning_state_plan.json",
    "learning/evidence_plan.json",
    "learning/activity_plan.json",
    "quality/evidence_alignment_report.json",
]
ABSTRACT_BINDING_PATH = "presentation/abstract_activity_bindings.json"
CANONICAL_BLUEPRINT_PATH = "presentation/presentation_blueprint.json"
SHADOW_REPORT_PATH = "quality/presentation_shadow_report.json"


def compile_shadow_presentation(
    state_plan: LearningStatePlan,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    alignment_report: EvidenceAlignmentReport,
) -> tuple[AbstractPresentationBindingPlan, CanonicalPresentationBlueprint | None, PresentationShadowReport]:
    """Compile kernel artifacts into a non-production presentation projection."""
    bindings = build_abstract_presentation_bindings(evidence_plan, activity_plan, alignment_report)
    if bindings.state == "blocked":
        return bindings, None, PresentationShadowReport(
            state="blocked",
            generated_artifacts=[ABSTRACT_BINDING_PATH, SHADOW_REPORT_PATH],
            warnings=list(bindings.warnings),
            blocking=list(bindings.blocking),
            compatibility_contract_valid=False,
        )

    blueprint = build_canonical_presentation_blueprint(state_plan, evidence_plan, activity_plan, bindings)
    return bindings, blueprint, PresentationShadowReport(
        state="warning" if bindings.warnings else "pass",
        generated_artifacts=[ABSTRACT_BINDING_PATH, CANONICAL_BLUEPRINT_PATH, SHADOW_REPORT_PATH],
        warnings=list(bindings.warnings),
        compatibility_contract_valid=False,
    )


def build_abstract_presentation_bindings(
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    alignment_report: EvidenceAlignmentReport,
) -> AbstractPresentationBindingPlan:
    """Project planned activities to abstract, renderer-independent bindings."""
    plan = AbstractPresentationBindingPlan(
        state="blocked" if alignment_report.state == "blocked" else "warning" if alignment_report.warnings else "pass",
        warnings=list(alignment_report.warnings),
        blocking=list(alignment_report.blocking),
        source_artifacts=list(KERNEL_SOURCE_ARTIFACTS),
    )
    if alignment_report.state == "blocked":
        return plan

    evidence_by_id = {spec.evidence_id: spec for spec in evidence_plan.evidence_specs}
    for activity in sorted(activity_plan.activities, key=lambda item: item.activity_id):
        evidence = [evidence_by_id.get(evidence_id) for evidence_id in activity.evidence_ids]
        missing = [evidence_id for evidence_id, spec in zip(activity.evidence_ids, evidence) if spec is None]
        if missing:
            plan.blocking.append(
                f"Activity '{activity.activity_id}' cannot be compiled because evidence is missing: {', '.join(missing)}."
            )
            continue
        plan.bindings.append(_binding_for_activity(activity, [spec for spec in evidence if spec is not None], alignment_report.warnings))

    if plan.blocking:
        plan.state = "blocked"
    elif plan.warnings:
        plan.state = "warning"
    return plan


def build_canonical_presentation_blueprint(
    state_plan: LearningStatePlan,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    bindings: AbstractPresentationBindingPlan,
) -> CanonicalPresentationBlueprint:
    """Create learner-safe presentation units from already planned activity bindings."""
    evidence_by_id = {spec.evidence_id: spec for spec in evidence_plan.evidence_specs}
    activities = {activity.activity_id: activity for activity in activity_plan.activities}
    units: list[PresentationUnit] = []
    for binding in bindings.bindings:
        activity = activities[binding.activity_id]
        evidence = [evidence_by_id[evidence_id] for evidence_id in binding.evidence_ids]
        learner_content = [] if binding.teacher_only else _target_items(evidence)
        units.append(
            PresentationUnit(
                presentation_unit_id=binding.presentation_unit_id,
                binding_id=binding.id,
                activity_id=binding.activity_id,
                evidence_ids=list(binding.evidence_ids),
                unit_role=_unit_role(activity, binding.teacher_only),
                learner_channel=list(binding.learner_channel),
                teacher_channel=list(binding.teacher_channel),
                presentation_mode=binding.presentation_mode,
                learner_facing_content=learner_content,
                interaction_requirements=list(binding.interaction_requirements),
                fallback_mode=binding.fallback_mode,
                media_requirements=_media_requirements(evidence),
                teacher_channel_reference=f"teacher:{binding.id}" if binding.teacher_only else None,
                render_ready=binding.render_ready,
                warnings=list(binding.warnings),
                trace=binding.trace,
            )
        )
    return CanonicalPresentationBlueprint(
        lesson_title=state_plan.lesson_title,
        presentation_units=units,
        warnings=list(bindings.warnings),
        source_artifacts=list(KERNEL_SOURCE_ARTIFACTS),
        compatibility_notes=[
            "Shadow-only v2 artifact; production renderers continue to use the legacy presentation contract.",
            "Teacher-only content is referenced by channel and is not included in learner_facing_content.",
        ],
    )


def _binding_for_activity(activity: LearningActivity, evidence: list, inherited_warnings: list[str]) -> AbstractPresentationBinding:
    teacher_only = not activity.learner_facing or any(_teacher_only(spec) for spec in evidence)
    unit_id = f"unit_{activity.activity_id}"
    binding_id = f"abind_{activity.activity_id}"
    mode = _presentation_mode(activity, evidence, teacher_only)
    learner_channel = [] if teacher_only else ["learner_display", "learner_interaction"]
    teacher_channel = ["teacher_observation", "diagnostic_export"] if teacher_only else ["speaker_notes"]
    return AbstractPresentationBinding(
        id=binding_id,
        presentation_unit_id=unit_id,
        activity_id=activity.activity_id,
        evidence_ids=list(activity.evidence_ids),
        learner_channel=learner_channel,
        teacher_channel=teacher_channel,
        presentation_mode=mode,
        interaction_requirements=[
            f"activity_type:{activity.activity_type or 'guided_response'}",
            f"interaction_mode:{activity.interaction_mode}",
            f"input_type:{activity.input_type}",
            f"output_type:{activity.output_type}",
        ],
        fallback_mode="scaffold_and_retry" if activity.fallback_activity else "none",
        render_ready=not teacher_only,
        teacher_only=teacher_only,
        warnings=list(inherited_warnings),
        trace=PresentationTrace(
            presentation_unit_id=unit_id,
            binding_id=binding_id,
            activity_id=activity.activity_id,
            evidence_ids=list(activity.evidence_ids),
        ),
    )


def _presentation_mode(activity: LearningActivity, evidence: list, teacher_only: bool) -> str:
    if teacher_only:
        return "teacher_observation"
    evidence_types = {item.evidence_type for item in evidence}
    if "listen_choose" in evidence_types:
        return "listening_choice"
    if "matching" in evidence_types:
        return "matching_response"
    if "role_play" in evidence_types or activity.activity_type == "role_play":
        return "role_play_response"
    if "constrained_production" in evidence_types or activity.output_type == "response":
        return "guided_response"
    return "choice_response"


def _unit_role(activity: LearningActivity, teacher_only: bool) -> str:
    if teacher_only:
        return "teacher_observation"
    return "learner_interaction" if activity.learner_facing else "teacher_support"


def _teacher_only(evidence) -> bool:
    return evidence.collection_method == "teacher_observation" or evidence.evidence_type == "teacher_observation"


def _target_items(evidence: list) -> list[str]:
    return list(dict.fromkeys(item for spec in evidence for item in spec.target_items if item))


def _media_requirements(evidence: list) -> list[str]:
    return ["audio"] if any(spec.evidence_type == "listen_choose" for spec in evidence) else []
