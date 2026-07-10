"""Opt-in structural parity checks for the v2 presentation shadow path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .blueprint_compatibility import adapt_canonical_presentation_blueprint
from .models import (
    AbstractPresentationBindingPlan,
    CanonicalPresentationBlueprint,
    LessonBlueprint,
    PresentationContentPlan,
    PresentationParityReport,
    PresentationShadowReport,
)
from .storage import read_json, write_json


CANONICAL_BLUEPRINT_PATH = "presentation/presentation_blueprint.json"
ABSTRACT_BINDING_PATH = "presentation/abstract_activity_bindings.json"
SHADOW_REPORT_PATH = "quality/presentation_shadow_report.json"
PRODUCTION_BLUEPRINT_PATH = "blueprints/lesson_blueprint.json"
SHADOW_LEGACY_BLUEPRINT_PATH = "presentation/legacy_blueprint_from_v2.shadow.json"
PARITY_REPORT_PATH = "quality/presentation_parity_report.json"
CONTENT_PLAN_PATH = "presentation/presentation_content_plan.json"
RECONCILED_CONTENT_PLAN_PATH = "presentation/presentation_content_plan.reconciled.json"
SUPPORTED_MODES = {
    "choice_response",
    "listening_choice",
    "matching_response",
    "guided_response",
    "role_play_response",
    "teacher_observation",
}
KERNEL_OWNED_KEYS = {
    "learning_goals",
    "evidence_specs",
    "learning_state_plan",
    "success_criteria",
    "acceptable_response",
    "teacher_observation_notes",
}
TEACHER_TEXT_MARKERS = ("teacher-only", "teacher only", "private rubric", "teacher observation notes")


def run_presentation_parity_harness(
    project_id: str,
    adapter: Callable[[CanonicalPresentationBlueprint], LessonBlueprint | dict[str, Any]] = adapt_canonical_presentation_blueprint,
) -> PresentationParityReport:
    """Write diagnostic-only structural parity artifacts; no renderer is invoked."""
    report = PresentationParityReport()
    canonical = _load(project_id, CANONICAL_BLUEPRINT_PATH, CanonicalPresentationBlueprint, report, "canonical presentation blueprint")
    bindings = _load(project_id, ABSTRACT_BINDING_PATH, AbstractPresentationBindingPlan, report, "abstract presentation bindings")
    shadow = _load(project_id, SHADOW_REPORT_PATH, PresentationShadowReport, report, "presentation shadow report")
    content_plan = _load_optional(project_id, RECONCILED_CONTENT_PLAN_PATH, PresentationContentPlan, report, "reconciled presentation content plan")
    content_plan = content_plan or _load_optional(project_id, CONTENT_PLAN_PATH, PresentationContentPlan, report, "presentation content plan")
    production = _load(project_id, PRODUCTION_BLUEPRINT_PATH, LessonBlueprint, report, "production lesson blueprint")
    if shadow and shadow.state == "blocked":
        _block(report, "V2 presentation shadow report is blocked.")
    if not all((canonical, bindings, shadow, production)):
        return _write(project_id, report)

    unsupported = sorted({binding.presentation_mode for binding in bindings.bindings} - SUPPORTED_MODES)
    report.unsupported_modes.extend(unsupported)
    for mode in unsupported:
        _warn(report, f"Unsupported non-production presentation mode '{mode}'.")

    try:
        first_payload = _as_payload(_adapt(adapter, canonical, content_plan))
        second_payload = _as_payload(_adapt(adapter, canonical, content_plan))
        for path in _kernel_owned_paths(first_payload):
            _block(report, f"Adapted shadow blueprint contains kernel-owned field '{path}'.")
        first = LessonBlueprint.model_validate(first_payload)
        second = LessonBlueprint.model_validate(second_payload)
    except Exception as exc:  # diagnostic harness must turn adapter failures into a report
        _block(report, f"Adapted shadow blueprint is not LessonBlueprint-compatible: {exc}")
        return _write(project_id, report)

    report.deterministic_output = first.model_dump(mode="json") == second.model_dump(mode="json")
    if not report.deterministic_output:
        _block(report, "Compatibility adapter output is not deterministic.")
    write_json(project_id, SHADOW_LEGACY_BLUEPRINT_PATH, first.model_dump(mode="json"))

    report.slide_count_production = len(production.slides)
    report.slide_count_shadow = len(first.slides)
    report.component_count_production = _component_count(production)
    report.component_count_shadow = _component_count(first)
    report.interactive_count_production = _component_count(production)
    report.interactive_count_shadow = _component_count(first)
    _warn_on_count_difference(report, "slide", report.slide_count_production, report.slide_count_shadow)
    _warn_on_count_difference(report, "component", report.component_count_production, report.component_count_shadow)
    _warn_on_count_difference(report, "interactive unit", report.interactive_count_production, report.interactive_count_shadow)
    _warn_on_count_difference(report, "media requirement", _media_count(production), _media_count(first))
    if _has_learner_text(production) != _has_learner_text(first):
        _warn(report, "Learner-facing text presence differs between production and shadow blueprints.")

    _check_trace_coverage(report, canonical, first)
    _check_teacher_leakage(report, canonical, first)
    for unit in canonical.presentation_units:
        if unit.fallback_mode != "none":
            _warn(report, f"Presentation unit '{unit.presentation_unit_id}' uses fallback mode '{unit.fallback_mode}'.")
    _warn(report, "Visual parity is not checked by this diagnostic-only harness.")
    _warn(report, "Legacy fields in the adapted blueprint are compatibility projections only.")
    report.notes.extend([
        "Structural counts and traceability are compared; HTML and PPTX rendering are not invoked.",
        "Adapter-owned legacy layout fields are excluded from v2-source boundary checks.",
    ])
    return _write(project_id, report)


def _load(project_id: str, path: str, model_type, report: PresentationParityReport, label: str):
    payload = read_json(project_id, path)
    if payload is None:
        _block(report, f"Missing {label} at '{path}'.")
        return None
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        _block(report, f"Invalid {label} at '{path}': {exc}")
        return None


def _as_payload(value: LessonBlueprint | dict[str, Any]) -> dict[str, Any]:
    return value.model_dump(mode="json") if isinstance(value, LessonBlueprint) else value


def _load_optional(project_id: str, path: str, model_type, report: PresentationParityReport, label: str):
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


def _component_count(blueprint: LessonBlueprint) -> int:
    return sum(len(slide.components) for slide in blueprint.slides)


def _media_count(blueprint: LessonBlueprint) -> int:
    return sum(
        bool(value)
        for slide in blueprint.slides
        for value in slide.media_requirements.model_dump(mode="json").values()
    )


def _has_learner_text(blueprint: LessonBlueprint) -> bool:
    return any(block.text for slide in blueprint.slides for block in slide.content_blocks)


def _check_trace_coverage(
    report: PresentationParityReport,
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
    missing = sorted(expected - traces)
    report.missing_units.extend(missing)
    report.trace_coverage = len(expected & traces) / len(expected) if expected else 1.0
    for unit_id in missing:
        _block(report, f"Interactive presentation unit '{unit_id}' has no trace metadata in the adapted blueprint.")


def _check_teacher_leakage(
    report: PresentationParityReport,
    canonical: CanonicalPresentationBlueprint,
    adapted: LessonBlueprint,
) -> None:
    teacher_units = {
        unit.presentation_unit_id
        for unit in canonical.presentation_units
        if unit.teacher_channel_reference
    }
    adapted_payload = adapted.model_dump(mode="json")
    serialized = str(adapted_payload).lower()
    for marker in TEACHER_TEXT_MARKERS:
        if marker in serialized:
            report.teacher_leakage_findings.append(f"Learner-facing adapted output contains teacher-only marker '{marker}'.")
    for trace in _traces(adapted):
        if trace.get("presentation_unit_id") in teacher_units:
            report.teacher_leakage_findings.append(
                f"Teacher-only presentation unit '{trace.get('presentation_unit_id')}' appears in adapted learner output."
            )
    for finding in report.teacher_leakage_findings:
        _block(report, finding)


def _traces(blueprint: LessonBlueprint) -> list[dict[str, Any]]:
    return [
        trace
        for slide in blueprint.slides
        for component in slide.components
        for trace in [component.data.get("_shadow_trace")]
        if isinstance(trace, dict)
    ]


def _kernel_owned_paths(value: Any, path: str = "") -> list[str]:
    if isinstance(value, dict):
        paths = []
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else key
            if key in KERNEL_OWNED_KEYS:
                paths.append(item_path)
            paths.extend(_kernel_owned_paths(item, item_path))
        return paths
    if isinstance(value, list):
        return [found for index, item in enumerate(value) for found in _kernel_owned_paths(item, f"{path}[{index}]")]
    return []


def _warn_on_count_difference(report: PresentationParityReport, label: str, production: int, shadow: int) -> None:
    if production != shadow:
        _warn(report, f"{label.capitalize()} count differs: production={production}, shadow={shadow}.")


def _block(report: PresentationParityReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: PresentationParityReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)


def _write(project_id: str, report: PresentationParityReport) -> PresentationParityReport:
    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    write_json(project_id, PARITY_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    return report
