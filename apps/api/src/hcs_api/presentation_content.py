"""Shadow-only component-neutral content planning for approved presentation units."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    AbstractPresentationBindingPlan,
    AcceptedResponse,
    ActivityPlan,
    AssetManifest,
    AssetReference,
    CanonicalPresentationBlueprint,
    ChoiceOption,
    EvidencePlan,
    LanguageItem,
    LearningStatePlan,
    MatchingPair,
    PresentationContentItem,
    PresentationContentPlan,
    PresentationContentReport,
)


CONTENT_PLAN_PATH = "presentation/presentation_content_plan.json"
CONTENT_REPORT_PATH = "quality/presentation_content_report.json"
CONTENT_SOURCE_ARTIFACTS = [
    "learning/learning_state_plan.json",
    "learning/evidence_plan.json",
    "learning/activity_plan.json",
    "analysis/language_items.json",
]
TEACHER_MARKERS = ("teacher-only", "teacher only", "private", "rubric", "observation notes")


def build_presentation_content_plan(
    state_plan: LearningStatePlan,
    evidence_plan: EvidencePlan,
    activity_plan: ActivityPlan,
    binding_plan: AbstractPresentationBindingPlan,
    canonical_blueprint: CanonicalPresentationBlueprint | None = None,
    language_items: list[LanguageItem] | None = None,
    asset_manifest: AssetManifest | None = None,
) -> tuple[PresentationContentPlan, PresentationContentReport]:
    """Project approved artifacts into content; no mode or pedagogy is selected here."""
    language_items = language_items or []
    assets = asset_manifest or AssetManifest()
    evidence_by_id = {item.evidence_id: item for item in evidence_plan.evidence_specs}
    activity_by_id = {item.activity_id: item for item in activity_plan.activities}
    binding_by_id = {item.id: item for item in binding_plan.bindings}
    items: list[PresentationContentItem] = []

    units = canonical_blueprint.presentation_units if canonical_blueprint else _units_from_bindings(binding_plan)
    for unit in units:
        item = _content_for_unit(unit, evidence_by_id, activity_by_id, binding_by_id, language_items, assets)
        items.append(item)

    plan = PresentationContentPlan(
        lesson_title=state_plan.lesson_title,
        content_items=items,
        warnings=[],
        source_artifacts=list(CONTENT_SOURCE_ARTIFACTS) + (["assets/data/asset_manifest.json"] if asset_manifest else []),
        trace=[item.trace for item in items],
    )
    report = evaluate_presentation_content_plan(plan)
    plan.warnings = list(report.warnings)
    return plan, report


def evaluate_presentation_content_plan(plan: PresentationContentPlan) -> PresentationContentReport:
    """Evaluate an initial or reconciled plan without regenerating learner content."""
    report = PresentationContentReport(source_artifacts_checked=list(plan.source_artifacts))
    for item in plan.content_items:
        _record_item(report, item)
    report.items_count = len(plan.content_items)
    report.complete_items_count = sum(content_item_is_complete(item) for item in plan.content_items)
    report.incomplete_items_count = report.items_count - report.complete_items_count
    expected = {item.presentation_unit_id for item in plan.content_items}
    traced = {item.presentation_unit_id for item in plan.content_items if item.trace.presentation_unit_id == item.presentation_unit_id}
    report.trace_coverage = len(expected & traced) / len(expected) if expected else 1.0
    if report.trace_coverage != 1.0:
        _block(report, "Presentation content items do not cover every canonical presentation unit.")
    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    report.notes.append("Content is projected from approved artifacts; no audio, answer, distractor, or pair is fabricated.")
    return report


def content_item_is_complete(item: PresentationContentItem) -> bool:
    """Evaluate required payload presence without mutating planned learner content."""
    if item.presentation_mode == "teacher_observation":
        return True
    if item.presentation_mode == "listening_choice":
        return bool(item.prompt and len(item.options) >= 2 and item.accepted_responses and any(
            ref.availability == "available" for ref in item.audio_asset_refs
        ))
    if item.presentation_mode == "matching_response":
        return len(item.matching_pairs) >= 2 and _unambiguous_pairs(item.matching_pairs)
    return item.complete


@dataclass(frozen=True)
class _ContentUnit:
    presentation_unit_id: str
    binding_id: str
    activity_id: str
    evidence_ids: list[str]
    presentation_mode: str
    teacher_channel_reference: str | None
    trace: object


def _units_from_bindings(binding_plan: AbstractPresentationBindingPlan) -> list[_ContentUnit]:
    return [
        _ContentUnit(
            presentation_unit_id=binding.presentation_unit_id,
            binding_id=binding.id,
            activity_id=binding.activity_id,
            evidence_ids=list(binding.evidence_ids),
            presentation_mode=binding.presentation_mode,
            teacher_channel_reference=f"teacher:{binding.id}" if binding.teacher_only else None,
            trace=binding.trace,
        )
        for binding in binding_plan.bindings
    ]


def attach_content_references(
    canonical_blueprint: CanonicalPresentationBlueprint,
    content_plan: PresentationContentPlan,
) -> CanonicalPresentationBlueprint:
    """Attach references only; the content contract remains the content authority."""
    by_unit = {item.presentation_unit_id: item.id for item in content_plan.content_items}
    return canonical_blueprint.model_copy(
        update={
            "presentation_units": [
                unit.model_copy(update={"content_item_id": by_unit.get(unit.presentation_unit_id)})
                for unit in canonical_blueprint.presentation_units
            ]
        }
    )


def _content_for_unit(unit, evidence_by_id, activity_by_id, binding_by_id, language_items, assets) -> PresentationContentItem:
    warnings: list[str] = []
    evidence = [evidence_by_id.get(evidence_id) for evidence_id in unit.evidence_ids]
    missing_evidence = [evidence_id for evidence_id, spec in zip(unit.evidence_ids, evidence) if spec is None]
    activity = activity_by_id.get(unit.activity_id)
    binding = binding_by_id.get(unit.binding_id)
    teacher_only = unit.presentation_mode == "teacher_observation" or bool(unit.teacher_channel_reference)
    item = PresentationContentItem(
        id=f"content_{unit.presentation_unit_id}",
        presentation_unit_id=unit.presentation_unit_id,
        activity_id=unit.activity_id,
        evidence_ids=list(unit.evidence_ids),
        presentation_mode=unit.presentation_mode,
        display_items=[] if teacher_only else _display_items(evidence, language_items),
        language_items=[] if teacher_only else [item.id for item in language_items if item.target_form in _target_items(evidence)],
        provenance=[
            "canonical_presentation_unit",
            "learning/evidence_plan.json",
            "learning/activity_plan.json",
            "analysis/language_items.json",
        ],
        warnings=warnings,
        teacher_channel_reference=unit.teacher_channel_reference,
        trace=unit.trace,
    )
    if missing_evidence or activity is None or binding is None:
        warnings.append("Required approved reference is missing; content item is incomplete.")
        return item
    if unit.presentation_mode != binding.presentation_mode:
        warnings.append("Canonical unit and abstract binding presentation modes differ; content item is incomplete.")
        return item
    if teacher_only:
        item.complete = True
        item.provenance.append("teacher_channel_reference_only")
        return item

    item.prompt = _learner_safe_text(activity.learner_action) or _learner_safe_text(_first_observable_behavior(evidence))
    item.learner_instructions = _instructions_for_mode(unit.presentation_mode, activity, item.display_items)
    item.learner_safe_hint = _safe_hint(item.display_items, language_items)
    item.fallback_content = _fallback_content(activity.fallback_activity)
    accepted = _accepted_responses(evidence)
    item.accepted_responses = accepted

    if unit.presentation_mode in {"choice_response", "listening_choice"}:
        item.options = _choice_options(accepted, evidence, language_items, unit.presentation_unit_id)
        if unit.presentation_mode == "listening_choice":
            item.audio_asset_refs = _audio_refs(item.display_items, accepted, assets, item.id)
        item.complete = bool(item.prompt and len(item.options) >= 2 and accepted)
        if unit.presentation_mode == "listening_choice":
            item.complete = item.complete and any(ref.availability == "available" for ref in item.audio_asset_refs)
    elif unit.presentation_mode == "matching_response":
        item.matching_pairs = _matching_pairs(language_items, unit.presentation_unit_id)
        item.complete = len(item.matching_pairs) >= 2 and _unambiguous_pairs(item.matching_pairs)
    elif unit.presentation_mode == "guided_response":
        item.complete = bool(item.prompt and item.learner_instructions and (accepted or item.learner_safe_hint or item.display_items))
    elif unit.presentation_mode == "role_play_response":
        item.prompt = item.prompt or "Practice the approved role-play prompt with a partner."
        item.learner_instructions = _role_play_instructions(activity, item.display_items)
        item.complete = bool(item.prompt and item.learner_instructions and item.display_items)
    return item


def _record_item(report: PresentationContentReport, item: PresentationContentItem) -> None:
    mode = item.presentation_mode
    if mode == "choice_response":
        report.choice_items_count += 1
    elif mode == "matching_response":
        report.matching_items_count += 1
    elif mode == "listening_choice":
        report.listening_items_count += 1
    elif mode == "teacher_observation":
        report.teacher_only_items.append(item.presentation_unit_id)
        if any((item.prompt, item.learner_instructions, item.display_items, item.options, item.matching_pairs)):
            _block(report, f"Teacher-only unit '{item.presentation_unit_id}' has learner-facing content.")
    if mode in {"choice_response", "listening_choice"}:
        if len(item.options) < 2:
            report.missing_options.append(item.presentation_unit_id)
            _block(report, f"{mode} item '{item.presentation_unit_id}' needs at least two learner-safe options.")
        if not item.accepted_responses:
            report.missing_accepted_responses.append(item.presentation_unit_id)
            _block(report, f"{mode} item '{item.presentation_unit_id}' has no accepted-response projection.")
    if mode == "listening_choice" and not any(ref.availability == "available" for ref in item.audio_asset_refs):
        report.missing_audio_assets.append(item.presentation_unit_id)
        _block(report, f"listening_choice item '{item.presentation_unit_id}' has no available audio asset reference.")
    if mode == "matching_response" and (len(item.matching_pairs) < 2 or not _unambiguous_pairs(item.matching_pairs)):
        report.missing_matching_pairs.append(item.presentation_unit_id)
        _block(report, f"matching_response item '{item.presentation_unit_id}' needs two unambiguous matching pairs.")
    if mode in {"guided_response", "role_play_response"} and not item.complete:
        _warn(report, f"{mode} item '{item.presentation_unit_id}' is structurally minimal or incomplete.")
    for warning in item.warnings:
        _warn(report, f"{item.presentation_unit_id}: {warning}")


def _target_items(evidence: list) -> list[str]:
    return list(dict.fromkeys(value for spec in evidence if spec for value in spec.target_items if value))


def _display_items(evidence: list, language_items: list[LanguageItem]) -> list[str]:
    targets = _target_items(evidence)
    return list(dict.fromkeys(targets + [item.target_form for item in language_items if item.target_form in targets]))


def _first_observable_behavior(evidence: list) -> str:
    return next((spec.observable_behavior for spec in evidence if spec and spec.observable_behavior), "")


def _accepted_responses(evidence: list) -> list[AcceptedResponse]:
    values: list[tuple[str, str]] = []
    for spec in evidence:
        if not spec:
            continue
        policy = spec.acceptable_response
        explicit = policy.get("accepted_values") or policy.get("accepted_value") or policy.get("correct_answer") or policy.get("answer")
        if isinstance(explicit, str):
            values.append((explicit, "evidence.acceptable_response"))
        elif isinstance(explicit, list):
            values.extend((str(value), "evidence.acceptable_response") for value in explicit if value)
        elif len(spec.target_items) == 1:
            values.append((spec.target_items[0], "evidence.target_items"))
    return [
        AcceptedResponse(
            value=value,
            normalized_value=value.strip(),
            response_type="target_language",
            acceptance_mode="deterministic",
            alternatives=[],
            provenance=[provenance],
        )
        for value, provenance in dict.fromkeys(values)
    ]


def _choice_options(accepted, evidence, language_items, unit_id: str) -> list[ChoiceOption]:
    accepted_values = {item.normalized_value for item in accepted}
    candidates = list(accepted_values) + _target_items(evidence) + [item.target_form for item in language_items if item.target_form]
    values = list(dict.fromkeys(value for value in candidates if value))
    return [
        ChoiceOption(
            id=f"option_{unit_id}_{index}",
            text=value,
            value=value,
            is_accepted=value.strip() in accepted_values,
            provenance=["evidence.acceptable_response" if value.strip() in accepted_values else "analysis/language_items.json"],
        )
        for index, value in enumerate(values[:4], start=1)
    ]


def _matching_pairs(language_items: list[LanguageItem], unit_id: str) -> list[MatchingPair]:
    pairs = [
        MatchingPair(
            id=f"pair_{unit_id}_{index}",
            left=item.target_form,
            right=item.scaffold_meaning,
            provenance=["analysis/language_items.json", item.id],
        )
        for index, item in enumerate(language_items, start=1)
        if item.target_form and item.scaffold_meaning
    ]
    return pairs[:4]


def _unambiguous_pairs(pairs: list[MatchingPair]) -> bool:
    return len({pair.id for pair in pairs}) == len(pairs) and len({pair.left for pair in pairs}) == len(pairs) and len({pair.right for pair in pairs}) == len(pairs)


def _audio_refs(display_items, accepted, assets: AssetManifest, item_id: str) -> list[AssetReference]:
    target_values = set(display_items) | {item.normalized_value for item in accepted}
    matches = [asset for asset in assets.audio if asset.text in target_values and asset.path]
    if matches:
        return [
            AssetReference(
                asset_id=asset.id,
                asset_type="audio",
                path_or_key=asset.path,
                availability="available",
                provenance=["assets/data/asset_manifest.json", asset.id],
            )
            for asset in matches
        ]
    planned = [asset for asset in assets.audio if asset.text in target_values]
    if planned:
        return [
            AssetReference(
                asset_id=asset.id,
                asset_type="audio",
                path_or_key="",
                availability="planned",
                provenance=["assets/data/asset_manifest.json", asset.id],
            )
            for asset in planned
        ]
    return [
        AssetReference(
            asset_id="",
            asset_type="audio",
            path_or_key="",
            availability="missing",
            provenance=["assets/data/asset_manifest.json"],
        )
    ]


def _instructions_for_mode(mode: str, activity, display_items: list[str]) -> list[str]:
    action = _learner_safe_text(activity.learner_action)
    if mode in {"choice_response", "listening_choice"}:
        return [action or "Choose the approved response."]
    if mode == "guided_response":
        return [action or "Respond using the approved target language."]
    if mode == "matching_response":
        return [action or "Match each approved language item with its meaning."]
    return []


def _role_play_instructions(activity, display_items: list[str]) -> list[str]:
    instructions = ["Work with a partner.", "Use the approved target-language items shown."]
    action = _learner_safe_text(activity.learner_action)
    if action:
        instructions.insert(0, action)
    return instructions if display_items else []


def _safe_hint(display_items: list[str], language_items: list[LanguageItem]) -> str:
    by_target = {item.target_form: item for item in language_items}
    for value in display_items:
        if value in by_target and by_target[value].scaffold_meaning:
            return by_target[value].scaffold_meaning
    return ""


def _fallback_content(fallback: str) -> list[str]:
    safe = _learner_safe_text(fallback)
    return [safe] if safe else []


def _learner_safe_text(value: str) -> str:
    normalized = (value or "").strip()
    return "" if any(marker in normalized.lower() for marker in TEACHER_MARKERS) else normalized


def _block(report: PresentationContentReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: PresentationContentReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
