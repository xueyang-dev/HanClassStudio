"""Aggregate eligibility gate for the opt-in, internal-only v2 HTML experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .blueprint_compatibility import adapt_canonical_presentation_blueprint
from .models import (
    AbstractPresentationBindingPlan,
    AssetManifest,
    CanonicalPresentationBlueprint,
    CoursewareReviewReport,
    EvidenceAlignmentReport,
    LessonBlueprint,
    LessonProfile,
    PresentationAdapterAssessmentReport,
    PresentationAssetReconciliationReport,
    PresentationContentPlan,
    PresentationContentReport,
    PresentationMediaProjectionLinkPlan,
    PresentationMediaProjectionReport,
    PresentationMediaRequestPlan,
    PresentationMediaRequestReport,
    PresentationParityReport,
    PresentationReadinessReport,
    PresentationShadowReport,
    QualityReport,
    V2CutoverReadinessReport,
    V2RenderedOutputReviewReport,
)
from .presentation_content import content_item_is_complete
from .storage import project_dir, read_json, write_json


REPORT_PATH = "quality/v2_cutover_readiness_report.json"
INTERNAL_HTML_PATH = "courseware/lesson_v2_internal.html"
INTERNAL_RENDER_MANIFEST_PATH = "courseware/render_manifest_v2_internal.json"
RENDERED_OUTPUT_REVIEW_PATH = "quality/v2_rendered_output_review.json"
APPROVED_MODES = {"listening_choice", "matching_response"}
CONDITIONAL_MODES = {"guided_response", "role_play_response"}
ALLOWED_PARITY_WARNINGS = ("Visual parity is not checked", "Legacy fields in the adapted blueprint")
ALLOWED_ADAPTER_WARNINGS = ("Visual parity is not checked",)

REQUIRED_MODELS = {
    "quality/evidence_alignment_report.json": EvidenceAlignmentReport,
    "quality/presentation_content_report.json": PresentationContentReport,
    "quality/presentation_media_request_report.json": PresentationMediaRequestReport,
    "quality/presentation_media_projection_report.json": PresentationMediaProjectionReport,
    "quality/presentation_asset_reconciliation_report.json": PresentationAssetReconciliationReport,
    "quality/presentation_shadow_report.json": PresentationShadowReport,
    "quality/presentation_adapter_assessment_report.json": PresentationAdapterAssessmentReport,
    "quality/presentation_parity_report.json": PresentationParityReport,
    "quality/presentation_readiness_report.json": PresentationReadinessReport,
    "presentation/abstract_activity_bindings.json": AbstractPresentationBindingPlan,
    "presentation/presentation_blueprint.json": CanonicalPresentationBlueprint,
    "presentation/presentation_content_plan.json": PresentationContentPlan,
    "presentation/presentation_content_plan.reconciled.json": PresentationContentPlan,
    "presentation/presentation_media_request_plan.json": PresentationMediaRequestPlan,
    "presentation/presentation_media_projection_links.shadow.json": PresentationMediaProjectionLinkPlan,
}


def evaluate_v2_cutover_readiness(
    project_id: str,
    *,
    enabled: bool,
    require_courseware_review: bool = True,
) -> tuple[V2CutoverReadinessReport, LessonBlueprint | None]:
    """Evaluate current artifacts afresh; never trust a prior readiness decision."""
    report = V2CutoverReadinessReport()
    models, payloads = _load_required_models(project_id, report)
    review = _load_courseware_review(project_id, report, require_courseware_review)
    _record_mtimes(project_id, report, payloads, review is not None)
    if report.missing_artifacts or report.blocking:
        if report.missing_artifacts:
            _block(report, "Required v2 cutover artifacts are missing.")
        return _finish(report, enabled), None

    alignment = models["quality/evidence_alignment_report.json"]
    content_report = models["quality/presentation_content_report.json"]
    request_report = models["quality/presentation_media_request_report.json"]
    projection_report = models["quality/presentation_media_projection_report.json"]
    reconciliation_report = models["quality/presentation_asset_reconciliation_report.json"]
    shadow_report = models["quality/presentation_shadow_report.json"]
    adapter_report = models["quality/presentation_adapter_assessment_report.json"]
    parity_report = models["quality/presentation_parity_report.json"]
    readiness_report = models["quality/presentation_readiness_report.json"]
    bindings = models["presentation/abstract_activity_bindings.json"]
    canonical = models["presentation/presentation_blueprint.json"]
    initial_content = models["presentation/presentation_content_plan.json"]
    reconciled_content = models["presentation/presentation_content_plan.reconciled.json"]
    request_plan = models["presentation/presentation_media_request_plan.json"]
    projection_links = models["presentation/presentation_media_projection_links.shadow.json"]

    _check_freshness(project_id, report, review is not None)
    _check_cross_artifact_identity(report, bindings, canonical, initial_content, reconciled_content)
    _record_gate_states(report, {
        "evidence_alignment": alignment, "presentation_content": content_report,
        "presentation_media_request": request_report, "presentation_media_projection": projection_report,
        "presentation_asset_reconciliation": reconciliation_report, "presentation_shadow": shadow_report,
        "presentation_adapter_assessment": adapter_report, "presentation_parity": parity_report,
        "presentation_readiness": readiness_report, "courseware_review": review,
    })

    _require_not_blocked(report, "Evidence alignment", alignment)
    _require_not_blocked(report, "Presentation content", content_report)
    _require_not_blocked(report, "Presentation shadow", shadow_report)
    _require_not_blocked(report, "Presentation adapter assessment", adapter_report)
    _require_not_blocked(report, "Presentation parity", parity_report)
    _require_not_blocked(report, "Presentation readiness", readiness_report)
    if review is not None:
        report.courseware_review_state = review.state
        _require_not_blocked(report, "Courseware review", review)
        for warning in review.warnings:
            _warn(report, f"Courseware review: {warning}")
    _surface_gate_warnings(report, {
        "Evidence alignment": alignment,
        "Presentation content": content_report,
        "Presentation media projection": projection_report,
        "Presentation asset reconciliation": reconciliation_report,
        "Presentation shadow": shadow_report,
        "Presentation readiness": readiness_report,
    })

    learner_units = [unit for unit in canonical.presentation_units if unit.learner_channel and not unit.teacher_channel_reference]
    report.learner_facing_modes = sorted({unit.presentation_mode for unit in learner_units})
    report.unsupported_modes = sorted(set(report.learner_facing_modes) - APPROVED_MODES)
    report.whole_lesson_routing = bool(learner_units) and not report.unsupported_modes
    if not learner_units:
        _block(report, "V2 internal HTML requires at least one learner-facing presentation unit.")
    if report.unsupported_modes:
        _block(report, "Whole-lesson allowlist rejects learner-facing modes: " + ", ".join(report.unsupported_modes) + ".")

    content_by_unit = {item.presentation_unit_id: item for item in reconciled_content.content_items}
    report.content_complete = all(
        content_by_unit.get(unit.presentation_unit_id) and content_item_is_complete(content_by_unit[unit.presentation_unit_id])
        for unit in learner_units
    )
    if not report.content_complete:
        _block(report, "One or more learner-facing v2 content items are incomplete.")
    _check_teacher_safety(report, canonical, reconciled_content, adapter_report, parity_report)
    _check_trace_coverage(report, learner_units, reconciled_content, request_plan, projection_links, adapter_report, parity_report)
    _check_media_requirements(
        report, learner_units, content_by_unit, request_plan, projection_links,
        request_report, projection_report, reconciliation_report,
    )
    _check_matching_requirements(report, learner_units, content_by_unit)
    _check_report_warnings(report, adapter_report, parity_report, request_report)

    adapted = _adapt(report, canonical, reconciled_content)
    if adapted is not None:
        _check_adapted_payloads(report, adapted, learner_units, content_by_unit)
    report.renderer_contract_preserved = report.adapter_compatible and not adapter_report.renderer_compatibility_findings
    report.structural_parity_state = parity_report.state
    report.input_fingerprint = _fingerprint(payloads)
    _check_rendered_output_review(project_id, report)
    if report.stale_artifacts:
        _block(report, "V2 cutover inputs are stale or inconsistent.")
    return _finish(report, enabled), adapted if not report.blocking else None


def run_v2_internal_html_cutover(
    project_id: str,
    project_root: Path,
    profile: LessonProfile,
    manifest: AssetManifest,
    quality_report: QualityReport,
    *,
    enabled: bool,
    require_courseware_review: bool = True,
) -> V2CutoverReadinessReport:
    """Render a separate internal HTML file or remove it and select the legacy route."""
    report, adapted = evaluate_v2_cutover_readiness(
        project_id, enabled=enabled, require_courseware_review=require_courseware_review,
    )
    if not report.experiment_eligible or adapted is None:
        _remove_internal_output(project_root)
        # Preserve a blocked review as the reason a repeated attempt must stay
        # on legacy; ordinary stale diagnostics are safe to remove.
        if report.rendered_output_state != "blocked":
            _clear_rendered_output_diagnostics(project_id)
        write_json(project_id, REPORT_PATH, report.model_dump(mode="json", by_alias=True))
        return report

    from .renderer import render_lesson
    from .v2_rendered_output_review import clear_v2_rendered_output_diagnostics, run_v2_rendered_output_review

    clear_v2_rendered_output_diagnostics(project_id)
    legacy_html = project_root / "courseware/lesson.html"
    legacy_before = legacy_html.read_bytes() if legacy_html.exists() else None
    render_lesson(
        project_root, profile, adapted, manifest, quality_report,
        output_filename=Path(INTERNAL_HTML_PATH).name,
    )
    rendered_review = run_v2_rendered_output_review(
        project_id, source_input_fingerprint=report.input_fingerprint,
    )
    rendered_review.production_output_unchanged = not legacy_html.exists() or legacy_before == legacy_html.read_bytes()
    if not rendered_review.production_output_unchanged:
        rendered_review.blocking.append("Internal v2 render changed production lesson.html.")
        rendered_review.state = "blocked"
    write_json(project_id, RENDERED_OUTPUT_REVIEW_PATH, rendered_review.model_dump(mode="json", by_alias=True))
    report.rendered_output_state = rendered_review.state
    report.experiment_run_healthy = rendered_review.state != "blocked"
    if rendered_review.state == "blocked":
        _block(report, "V2 rendered-output review is blocked.")
        report.experiment_eligible = False
        report.selected_route = "legacy"
        report.fallback_reason = report.blocking[0]
        report.state = "blocked"
        _remove_internal_output(project_root)
    write_json(project_id, REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    return report


def invalidate_v2_internal_cutover(project_id: str) -> None:
    """Remove experiment output when a legacy blueprint or manual edit changes authority."""
    root = project_dir(project_id)
    _remove_internal_output(root)
    report = root / REPORT_PATH
    if report.exists():
        report.unlink()
    _clear_rendered_output_diagnostics(project_id)


def _load_required_models(project_id: str, report: V2CutoverReadinessReport):
    models: dict[str, Any] = {}
    payloads: dict[str, Any] = {}
    for path, model_type in REQUIRED_MODELS.items():
        payload = read_json(project_id, path)
        if payload is None:
            report.missing_artifacts.append(path)
            continue
        try:
            models[path] = model_type.model_validate(payload)
            payloads[path] = payload
        except ValidationError as exc:
            _block(report, f"Invalid required artifact '{path}': {exc.errors()[0]['msg']}")
    return models, payloads


def _load_courseware_review(project_id: str, report: V2CutoverReadinessReport, required: bool):
    path = "quality/courseware_review_report.json"
    payload = read_json(project_id, path)
    if payload is None:
        if required:
            report.missing_artifacts.append(path)
        return None
    try:
        return CoursewareReviewReport.model_validate(payload)
    except ValidationError as exc:
        _block(report, f"Invalid courseware review: {exc.errors()[0]['msg']}")
        return None


def _record_mtimes(project_id: str, report: V2CutoverReadinessReport, payloads: dict[str, Any], has_review: bool) -> None:
    root = project_dir(project_id)
    paths = [*payloads, *( ["quality/courseware_review_report.json"] if has_review else [] )]
    for path in paths:
        candidate = root / path
        if candidate.exists():
            report.artifact_mtimes_ns[path] = candidate.stat().st_mtime_ns


def _check_freshness(project_id: str, report: V2CutoverReadinessReport, has_review: bool) -> None:
    root = project_dir(project_id)
    pairs = (
        ("quality/evidence_alignment_report.json", "learning/learning_state_plan.json"),
        ("quality/evidence_alignment_report.json", "learning/evidence_plan.json"),
        ("quality/evidence_alignment_report.json", "learning/activity_plan.json"),
        ("quality/presentation_content_report.json", "presentation/presentation_content_plan.reconciled.json"),
        ("quality/presentation_media_request_report.json", "presentation/presentation_media_request_plan.json"),
        ("quality/presentation_asset_reconciliation_report.json", "presentation/presentation_content_plan.reconciled.json"),
        ("quality/presentation_adapter_assessment_report.json", "presentation/presentation_blueprint.json"),
        ("quality/presentation_parity_report.json", "presentation/presentation_blueprint.json"),
    )
    if has_review:
        pairs += (
            ("quality/courseware_review_report.json", "blueprints/lesson_blueprint.json"),
            ("quality/courseware_review_report.json", "presentation/presentation_blueprint.json"),
            ("quality/courseware_review_report.json", "presentation/presentation_content_plan.reconciled.json"),
        )
    for report_path, source_path in pairs:
        target, source = root / report_path, root / source_path
        if target.exists() and source.exists() and target.stat().st_mtime_ns < source.stat().st_mtime_ns:
            report.stale_artifacts.append(f"{report_path} predates {source_path}")


def _check_cross_artifact_identity(report, bindings, canonical, initial, reconciled) -> None:
    if _content_identity(initial) != _content_identity(reconciled):
        report.stale_artifacts.append("Reconciled content changes non-asset content fields from the current initial content plan.")
    items = {item.id: item for item in reconciled.content_items}
    bindings_by_id = {binding.id: binding for binding in bindings.bindings}
    for unit in canonical.presentation_units:
        item = items.get(unit.content_item_id or "")
        binding = bindings_by_id.get(unit.binding_id)
        if item is None or binding is None:
            report.stale_artifacts.append(f"Canonical unit '{unit.presentation_unit_id}' lacks current content or binding.")
            continue
        if (item.presentation_unit_id, item.activity_id, item.evidence_ids) != (unit.presentation_unit_id, unit.activity_id, unit.evidence_ids):
            report.stale_artifacts.append(f"Canonical unit '{unit.presentation_unit_id}' has stale content trace.")
        if binding.trace.presentation_unit_id != unit.presentation_unit_id or binding.activity_id != unit.activity_id:
            report.stale_artifacts.append(f"Canonical unit '{unit.presentation_unit_id}' has stale binding trace.")


def _record_gate_states(report, reports: dict[str, Any]) -> None:
    for name, value in reports.items():
        if value is not None:
            report.required_gate_states[name] = getattr(value, "state", "unknown")


def _require_not_blocked(report, label: str, gate) -> None:
    if gate.state == "blocked":
        _block(report, f"{label} is blocked.")


def _check_teacher_safety(report, canonical, content, adapter, parity) -> None:
    for item in content.content_items:
        if item.teacher_channel_reference and any((item.prompt, item.learner_instructions, item.display_items, item.options, item.matching_pairs)):
            report.teacher_leakage_findings.append(f"Teacher-only content item '{item.id}' contains learner payload.")
    teacher_units = {unit.presentation_unit_id for unit in canonical.presentation_units if unit.teacher_channel_reference}
    try:
        adapted = adapt_canonical_presentation_blueprint(canonical, content)
    except Exception as exc:
        _block(report, f"Teacher-channel safety could not validate the compatibility adapter: {exc}")
        return
    for slide in adapted.slides:
        for component in slide.components:
            trace = component.data.get("_shadow_trace")
            if isinstance(trace, dict) and trace.get("presentation_unit_id") in teacher_units:
                report.teacher_leakage_findings.append("Teacher-only unit appears in adapted learner output.")
    report.teacher_leakage_findings.extend(adapter.teacher_channel_findings)
    report.teacher_leakage_findings.extend(parity.teacher_leakage_findings)
    for finding in report.teacher_leakage_findings:
        _block(report, finding)


def _check_trace_coverage(report, learner_units, content, request_plan, projection_links, adapter, parity) -> None:
    expected = {unit.presentation_unit_id for unit in learner_units}
    content_units = {item.presentation_unit_id for item in content.content_items if item.trace.presentation_unit_id == item.presentation_unit_id}
    report.trace_coverage = len(expected & content_units) / len(expected) if expected else 0.0
    if report.trace_coverage != 1.0 or adapter.trace_coverage != 1.0 or parity.trace_coverage != 1.0:
        _block(report, "Required v2 trace coverage is incomplete.")
    request_ids = {request.id for request in request_plan.requests}
    for link in projection_links.links:
        if link.shadow_request_id not in request_ids:
            report.stale_artifacts.append(f"Projection link references missing request '{link.shadow_request_id}'.")


def _check_media_requirements(report, learner_units, content_by_unit, request_plan, projection_links, request_report, projection_report, reconciliation_report) -> None:
    listening = [unit for unit in learner_units if unit.presentation_mode == "listening_choice"]
    report.media_complete = not listening
    if not listening:
        return
    _require_not_blocked(report, "Presentation media request", request_report)
    _require_not_blocked(report, "Presentation media projection", projection_report)
    _require_not_blocked(report, "Presentation asset reconciliation", reconciliation_report)
    requests_by_content = {request.content_item_id: request for request in request_plan.requests}
    links_by_request = {link.shadow_request_id: link for link in projection_links.links}
    findings = {finding.content_item_id: finding for finding in reconciliation_report.findings}
    complete = True
    for unit in listening:
        item = content_by_unit.get(unit.presentation_unit_id)
        request = requests_by_content.get(item.id if item else "")
        link = links_by_request.get(request.id if request else "")
        finding = findings.get(item.id if item else "")
        if not item or len(item.options) < 2 or not item.accepted_responses or not any(ref.availability == "available" for ref in item.audio_asset_refs):
            complete = False
            _block(report, f"Listening unit '{unit.presentation_unit_id}' lacks complete content or available audio.")
        if not request or not request.id.startswith("pmr_"):
            complete = False
            _block(report, f"Listening unit '{unit.presentation_unit_id}' lacks a deterministic media request.")
        if not link or link.match_class not in {"exact", "linkable"}:
            complete = False
            _block(report, f"Listening unit '{unit.presentation_unit_id}' lacks an exact or linkable media projection.")
        if not finding or finding.state != "pass":
            complete = False
            _block(report, f"Listening unit '{unit.presentation_unit_id}' lacks successful asset reconciliation.")
    report.media_complete = complete


def _check_matching_requirements(report, learner_units, content_by_unit) -> None:
    for unit in learner_units:
        if unit.presentation_mode != "matching_response":
            continue
        item = content_by_unit.get(unit.presentation_unit_id)
        pairs = item.matching_pairs if item else []
        if len(pairs) < 2 or len({pair.id for pair in pairs}) != len(pairs) or len({pair.left for pair in pairs}) != len(pairs) or len({pair.right for pair in pairs}) != len(pairs):
            _block(report, f"Matching unit '{unit.presentation_unit_id}' lacks two deterministic unambiguous pairs.")


def _check_report_warnings(report, adapter, parity, request) -> None:
    for warning in adapter.warnings:
        if not warning.startswith(ALLOWED_ADAPTER_WARNINGS):
            _block(report, f"Adapter warning is not accepted for the internal experiment: {warning}")
        _warn(report, f"Adapter: {warning}")
    for warning in parity.warnings:
        safe_fallback = warning.endswith("uses fallback mode 'scaffold_and_retry'.")
        if not warning.startswith(ALLOWED_PARITY_WARNINGS) and not safe_fallback:
            _block(report, f"Parity warning is not accepted for the internal experiment: {warning}")
        _warn(report, f"Parity: {warning}")
    for warning in request.warnings:
        if "planned only" not in warning:
            _block(report, f"Media-request warning is not accepted for the internal experiment: {warning}")
        _warn(report, f"Media request: {warning}")


def _check_rendered_output_review(project_id: str, report: V2CutoverReadinessReport) -> None:
    """A review is optional before first render, but authoritative once it exists."""
    root = project_dir(project_id)
    payload = read_json(project_id, RENDERED_OUTPUT_REVIEW_PATH)
    html_path = root / INTERNAL_HTML_PATH
    if payload is None:
        if html_path.exists():
            report.stale_artifacts.append("Internal v2 HTML exists without a rendered-output review.")
        return
    try:
        rendered = V2RenderedOutputReviewReport.model_validate(payload)
    except ValidationError as exc:
        _block(report, f"Invalid v2 rendered-output review: {exc.errors()[0]['msg']}")
        return
    report.rendered_output_state = rendered.state
    report.experiment_run_healthy = rendered.state != "blocked"
    if rendered.source_input_fingerprint != report.input_fingerprint:
        report.stale_artifacts.append("Rendered-output review belongs to different v2 inputs.")
    review_path = root / RENDERED_OUTPUT_REVIEW_PATH
    if html_path.exists() and review_path.stat().st_mtime_ns < html_path.stat().st_mtime_ns:
        report.stale_artifacts.append("Rendered-output review predates its internal HTML.")
    if rendered.state == "blocked":
        _block(report, "V2 rendered-output review is blocked.")
    elif rendered.state == "warning":
        _warn(report, "V2 rendered-output review has unresolved internal-experiment warnings.")
    if not html_path.exists():
        report.stale_artifacts.append("Rendered-output review exists without its internal HTML output.")


def _surface_gate_warnings(report, reports: dict[str, Any]) -> None:
    """Keep non-blocking upstream limitations visible in the aggregate decision."""
    for label, gate in reports.items():
        for warning in getattr(gate, "warnings", []):
            _warn(report, f"{label}: {warning}")


def _adapt(report, canonical, content) -> LessonBlueprint | None:
    try:
        adapted = LessonBlueprint.model_validate(adapt_canonical_presentation_blueprint(canonical, content).model_dump(mode="json"))
    except Exception as exc:
        _block(report, f"Compatibility adapter cannot produce a LessonBlueprint input: {exc}")
        return None
    report.adapter_compatible = True
    return adapted


def _check_adapted_payloads(report, adapted, learner_units, content_by_unit) -> None:
    traces = {
        trace.get("presentation_unit_id"): component
        for slide in adapted.slides
        for component in slide.components
        for trace in [component.data.get("_shadow_trace")]
        if isinstance(trace, dict)
    }
    for unit in learner_units:
        component = traces.get(unit.presentation_unit_id)
        item = content_by_unit.get(unit.presentation_unit_id)
        if item is None:
            _block(report, f"Adapted unit '{unit.presentation_unit_id}' has no current content item.")
            continue
        if component is None:
            _block(report, f"Adapted unit '{unit.presentation_unit_id}' lacks shadow trace metadata.")
            continue
        if unit.presentation_mode == "listening_choice":
            if component.component_type != "ListenAndChoose" or component.data.get("answer") not in component.data.get("choices", []) or not component.data.get("audio_key"):
                _block(report, f"Listening unit '{unit.presentation_unit_id}' has an invalid legacy adapter payload.")
        if unit.presentation_mode == "matching_response":
            if component.component_type != "MatchGame" or len(component.data.get("pairs", [])) < 2:
                _block(report, f"Matching unit '{unit.presentation_unit_id}' has an invalid legacy adapter payload.")


def _content_identity(plan: PresentationContentPlan) -> str:
    payload = plan.model_dump(mode="json")
    for item in payload.get("content_items", []):
        item["audio_asset_refs"] = []
        item["image_asset_refs"] = []
    return _fingerprint({"content": payload})


def _fingerprint(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _finish(report: V2CutoverReadinessReport, enabled: bool) -> V2CutoverReadinessReport:
    if report.blocking:
        report.state = "blocked"
        report.selected_route = "legacy"
        report.fallback_reason = report.blocking[0]
        return report
    if not enabled:
        report.state = "warning"
        report.selected_route = "legacy"
        report.fallback_reason = "V2 internal HTML cutover flag is disabled."
        _warn(report, report.fallback_reason)
        return report
    report.pre_render_eligible = True
    report.experiment_eligible = True
    report.selected_route = "v2_internal_html"
    report.state = "warning" if report.warnings else "pass"
    report.notes.append("Internal-only route selected; public HTML, ZIP, and editable PPTX remain legacy outputs.")
    return report


def _remove_internal_output(root: Path) -> None:
    for relative in (INTERNAL_HTML_PATH, INTERNAL_RENDER_MANIFEST_PATH):
        path = root / relative
        if path.exists():
            path.unlink()


def _clear_rendered_output_diagnostics(project_id: str) -> None:
    from .v2_rendered_output_review import clear_v2_rendered_output_diagnostics

    clear_v2_rendered_output_diagnostics(project_id)


def _block(report: V2CutoverReadinessReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: V2CutoverReadinessReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
