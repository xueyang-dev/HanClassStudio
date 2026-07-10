"""Opt-in capability assessment for the v2-to-legacy compatibility adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .blueprint_compatibility import adapt_canonical_presentation_blueprint
from .components import load_component_registry
from .presentation_content import content_item_is_complete
from .models import (
    AbstractPresentationBindingPlan,
    CanonicalPresentationBlueprint,
    LessonBlueprint,
    PresentationAdapterAssessmentReport,
    PresentationAdapterMappingPlan,
    PresentationContentPlan,
    PresentationModeCapability,
    PresentationShadowReport,
)
from .storage import read_json, write_json


CANONICAL_BLUEPRINT_PATH = "presentation/presentation_blueprint.json"
ABSTRACT_BINDING_PATH = "presentation/abstract_activity_bindings.json"
SHADOW_REPORT_PATH = "quality/presentation_shadow_report.json"
SHADOW_LEGACY_BLUEPRINT_PATH = "presentation/legacy_blueprint_from_v2.shadow.json"
CONTENT_PLAN_PATH = "presentation/presentation_content_plan.json"
RECONCILED_CONTENT_PLAN_PATH = "presentation/presentation_content_plan.reconciled.json"
MAPPING_PLAN_PATH = "presentation/legacy_component_mapping.shadow.json"
ASSESSMENT_REPORT_PATH = "quality/presentation_adapter_assessment_report.json"
RENDERER_COMPONENT_TYPES = {
    "AudioButton",
    "VocabularyFlipCard",
    "SentenceDragBuilder",
    "ListenAndChoose",
    "MatchGame",
    "CharacterFormation",
}
TEACHER_TEXT_MARKERS = ("teacher-only", "teacher only", "private rubric", "teacher observation notes")


def run_presentation_adapter_assessment(
    project_id: str,
    adapter: Callable[[CanonicalPresentationBlueprint], LessonBlueprint | dict[str, Any]] = adapt_canonical_presentation_blueprint,
) -> PresentationAdapterAssessmentReport:
    """Assess render-input capability only; production inputs and renderers are never used."""
    report = PresentationAdapterAssessmentReport()
    canonical = _load(project_id, CANONICAL_BLUEPRINT_PATH, CanonicalPresentationBlueprint, report, "canonical presentation blueprint")
    bindings = _load(project_id, ABSTRACT_BINDING_PATH, AbstractPresentationBindingPlan, report, "abstract presentation bindings")
    shadow = _load(project_id, SHADOW_REPORT_PATH, PresentationShadowReport, report, "presentation shadow report")
    content_plan = _load_optional(project_id, RECONCILED_CONTENT_PLAN_PATH, PresentationContentPlan, report, "reconciled presentation content plan")
    content_plan = content_plan or _load_optional(project_id, CONTENT_PLAN_PATH, PresentationContentPlan, report, "presentation content plan")
    if shadow and shadow.state == "blocked":
        _block(report, "V2 presentation shadow report is blocked.")
    if not all((canonical, bindings, shadow)):
        return _write(project_id, report)

    try:
        adapted = LessonBlueprint.model_validate(_as_payload(_adapt(adapter, canonical, content_plan)))
    except Exception as exc:
        _block(report, f"Compatibility adapter cannot produce a LessonBlueprint-compatible input: {exc}")
        return _write(project_id, report)

    registry = load_component_registry()
    capabilities = _capabilities(canonical, registry, content_plan)
    plan = PresentationAdapterMappingPlan(capabilities=capabilities)
    write_json(project_id, MAPPING_PLAN_PATH, plan.model_dump(mode="json", by_alias=True))
    report.assessed_units_count = len(canonical.presentation_units)
    for capability in capabilities:
        count = len(capability.presentation_unit_ids)
        _increment(report, capability.mapping_quality, count)
        _assess_capability(report, capability, canonical, content_plan)

    _check_trace_coverage(report, canonical, adapted)
    _check_teacher_safety(report, canonical, adapted)
    _warn(report, "Visual parity is not checked by this render-input capability assessment.")
    report.notes.extend([
        "Assessment uses registry-required field checks only; component quality rules are not a centralized schema.",
        "Legacy component selection is derived only from canonical presentation_mode and unit_role.",
    ])
    return _write(project_id, report)


def _capabilities(
    canonical: CanonicalPresentationBlueprint,
    registry: dict[str, dict[str, Any]],
    content_plan: PresentationContentPlan | None,
) -> list[PresentationModeCapability]:
    by_mode: dict[str, list] = {}
    for unit in canonical.presentation_units:
        by_mode.setdefault(unit.presentation_mode, []).append(unit)
    by_unit = {item.presentation_unit_id: item for item in (content_plan.content_items if content_plan else [])}
    return [_capability_for_mode(mode, units, registry, by_unit) for mode, units in sorted(by_mode.items())]


def _capability_for_mode(mode: str, units: list, registry: dict[str, dict[str, Any]], content_by_unit: dict) -> PresentationModeCapability:
    unit_ids = [unit.presentation_unit_id for unit in units]
    if mode == "teacher_observation":
        return _capability(mode, unit_ids, "PracticeSlide", None, "teacher_only", [], [], True, False, True)
    if mode == "choice_response":
        return _capability(
            mode, unit_ids, "PracticeSlide", "VocabularyFlipCard", "fallback",
            registry.get("VocabularyFlipCard", {}).get("requires", []),
            registry.get("VocabularyFlipCard", {}).get("optional", []), True, True,
            "VocabularyFlipCard" in RENDERER_COMPONENT_TYPES,
            ["No registered generic choice component exists; VocabularyFlipCard preserves learner content and trace, not choice scoring."],
        )
    if mode == "guided_response":
        return _capability(
            mode, unit_ids, "PracticeSlide", None, "approximate", [], [], True, True, True,
            ["PracticeSlide can display the planned response prompt but has no registered open-response component."],
        )
    if mode == "role_play_response":
        return _capability(
            mode, unit_ids, "PracticeSlide", None, "approximate", [], [], True, True, True,
            ["PracticeSlide can present the planned role-play prompt but cannot implement role-play interaction."],
        )
    component = "ListenAndChoose" if mode == "listening_choice" else "MatchGame"
    content_complete = all(
        content_by_unit.get(unit.presentation_unit_id) and content_item_is_complete(content_by_unit[unit.presentation_unit_id])
        for unit in units
    )
    return _capability(
        mode, unit_ids, "PracticeSlide", component, "exact" if content_complete else "unsupported",
        registry.get(component, {}).get("requires", []), registry.get(component, {}).get("optional", []), True, True,
        component in RENDERER_COMPONENT_TYPES,
        [] if content_complete else [f"Canonical v2 units do not carry the required {component} payload."],
    )


def _capability(
    mode: str,
    unit_ids: list[str],
    slide_type: str,
    component_type: str | None,
    quality: str,
    required: list[str],
    optional: list[str],
    teacher_safe: bool,
    learner_safe: bool,
    renderer_supported: bool,
    warnings: list[str] | None = None,
) -> PresentationModeCapability:
    return PresentationModeCapability(
        presentation_mode=mode,
        presentation_unit_ids=unit_ids,
        recommended_legacy_slide_type=slide_type,
        recommended_legacy_component_type=component_type,
        mapping_quality=quality,
        required_payload_fields=list(required),
        optional_payload_fields=list(optional),
        trace_fields=["presentation_unit_id", "binding_id", "activity_id", "evidence_ids"],
        teacher_safe=teacher_safe,
        learner_safe=learner_safe,
        renderer_supported=renderer_supported,
        warnings=warnings or [],
    )


def _assess_capability(
    report: PresentationAdapterAssessmentReport,
    capability: PresentationModeCapability,
    canonical: CanonicalPresentationBlueprint,
    content_plan: PresentationContentPlan | None,
) -> None:
    mode = capability.presentation_mode
    if capability.mapping_quality == "unsupported":
        report.unsupported_modes.append(mode)
        _block(report, f"Learner-facing presentation mode '{mode}' has no safe legacy payload representation.")
    elif capability.mapping_quality == "fallback":
        report.fallback_modes.append(mode)
        _warn(report, f"Presentation mode '{mode}' uses a registered generic fallback component.")
    elif capability.mapping_quality == "approximate":
        _warn(report, f"Presentation mode '{mode}' is represented by an approximate slide structure.")
    elif capability.mapping_quality == "teacher_only":
        _warn(report, "Teacher-only units are omitted from learner-facing legacy output by design.")

    if capability.recommended_legacy_component_type and not capability.renderer_supported:
        report.renderer_compatibility_findings.append(
            f"Component '{capability.recommended_legacy_component_type}' is not directly supported by the current HTML renderer."
        )
        _block(report, report.renderer_compatibility_findings[-1])
    for unit_id in capability.presentation_unit_ids:
        unit = next(item for item in canonical.presentation_units if item.presentation_unit_id == unit_id)
        content_item = next((item for item in (content_plan.content_items if content_plan else []) if item.presentation_unit_id == unit_id), None)
        payload = _safe_payload(capability.recommended_legacy_component_type, unit, content_item)
        missing = _missing_required_payload(payload, capability.required_payload_fields)
        if missing:
            finding = (
                f"Unit '{unit_id}' / mode '{mode}' cannot satisfy "
                f"{capability.recommended_legacy_component_type} fields: {', '.join(missing)}."
            )
            report.component_payload_findings.append(finding)
            _block(report, finding)


def _safe_payload(component_type: str | None, unit, content_item) -> dict[str, Any]:
    if component_type == "VocabularyFlipCard":
        return {
            "items": [{"word": item} for item in (content_item.display_items if content_item else unit.learner_facing_content) if item],
            "_shadow_trace": unit.trace.model_dump(mode="json"),
        }
    if component_type == "ListenAndChoose" and content_item:
        audio = next((item for item in content_item.audio_asset_refs if item.availability == "available"), None)
        return {
            "choices": [item.text for item in content_item.options],
            "answer": content_item.accepted_responses[0].normalized_value if content_item.accepted_responses else "",
            "audio_key": audio.asset_id if audio else "",
            "_shadow_trace": unit.trace.model_dump(mode="json"),
        }
    if component_type == "MatchGame" and content_item:
        return {
            "pairs": [{"left": pair.left, "right": pair.right} for pair in content_item.matching_pairs],
            "_shadow_trace": unit.trace.model_dump(mode="json"),
        }
    # No answer keys, pairs, or asset keys are invented from flat canonical content.
    return {"_shadow_trace": unit.trace.model_dump(mode="json")}


def _missing_required_payload(payload: dict[str, Any], required: list[str]) -> list[str]:
    return [field for field in required if not payload.get(field)]


def _check_trace_coverage(
    report: PresentationAdapterAssessmentReport,
    canonical: CanonicalPresentationBlueprint,
    adapted: LessonBlueprint,
) -> None:
    expected = {
        unit.presentation_unit_id
        for unit in canonical.presentation_units
        if unit.render_ready and "learner_interaction" in unit.learner_channel
    }
    traces = {
        trace.get("presentation_unit_id")
        for slide in adapted.slides
        for component in slide.components
        for trace in [component.data.get("_shadow_trace")]
        if isinstance(trace, dict)
    }
    report.trace_coverage = len(expected & traces) / len(expected) if expected else 1.0
    for unit_id in sorted(expected - traces):
        _block(report, f"Interactive unit '{unit_id}' loses trace metadata in the adapted legacy input.")


def _check_teacher_safety(
    report: PresentationAdapterAssessmentReport,
    canonical: CanonicalPresentationBlueprint,
    adapted: LessonBlueprint,
) -> None:
    teacher_units = {
        unit.presentation_unit_id
        for unit in canonical.presentation_units
        if unit.teacher_channel_reference
    }
    report.teacher_only_units_count = len(teacher_units)
    report.learner_visible_units_count = len(canonical.presentation_units) - len(teacher_units)
    serialized = str(adapted.model_dump(mode="json")).lower()
    for marker in TEACHER_TEXT_MARKERS:
        if marker in serialized:
            report.teacher_channel_findings.append(f"Adapted learner output contains teacher-only marker '{marker}'.")
    for slide in adapted.slides:
        for component in slide.components:
            trace = component.data.get("_shadow_trace")
            if isinstance(trace, dict) and trace.get("presentation_unit_id") in teacher_units:
                report.teacher_channel_findings.append(
                    f"Teacher-only unit '{trace.get('presentation_unit_id')}' is mapped to a learner-facing component."
                )
    for finding in report.teacher_channel_findings:
        _block(report, finding)


def _increment(report: PresentationAdapterAssessmentReport, quality: str, count: int) -> None:
    field = f"{quality}_mappings_count"
    if hasattr(report, field):
        setattr(report, field, getattr(report, field) + count)


def _load(project_id: str, path: str, model_type, report: PresentationAdapterAssessmentReport, label: str):
    payload = read_json(project_id, path)
    if payload is None:
        _block(report, f"Missing {label} at '{path}'.")
        return None
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        _block(report, f"Invalid {label} at '{path}': {exc}")
        return None


def _load_optional(project_id: str, path: str, model_type, report: PresentationAdapterAssessmentReport, label: str):
    payload = read_json(project_id, path)
    if payload is None:
        return None
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        _block(report, f"Invalid {label} at '{path}': {exc}")
        return None


def _adapt(adapter, canonical, content_plan):
    if content_plan is None:
        return adapter(canonical)
    try:
        return adapter(canonical, content_plan)
    except TypeError:
        return adapter(canonical)


def _as_payload(value: LessonBlueprint | dict[str, Any]) -> dict[str, Any]:
    return value.model_dump(mode="json") if isinstance(value, LessonBlueprint) else value


def _block(report: PresentationAdapterAssessmentReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: PresentationAdapterAssessmentReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)


def _write(project_id: str, report: PresentationAdapterAssessmentReport) -> PresentationAdapterAssessmentReport:
    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    write_json(project_id, ASSESSMENT_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    return report
