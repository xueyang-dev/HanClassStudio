"""Post-media, shadow-only reconciliation of traceable audio asset references."""

from __future__ import annotations

from .models import (
    AssetManifest,
    AssetReference,
    CanonicalPresentationBlueprint,
    PresentationAssetReconciliationFinding,
    PresentationAssetReconciliationReport,
    PresentationContentPlan,
    PresentationMediaAssetLinkPlan,
    PresentationMediaProjectionLinkPlan,
    PresentationMediaRequestPlan,
)
from .presentation_content import CONTENT_PLAN_PATH, CONTENT_REPORT_PATH, attach_content_references, evaluate_presentation_content_plan
from .storage import read_json, read_model, write_json


RECONCILED_CONTENT_PLAN_PATH = "presentation/presentation_content_plan.reconciled.json"
RECONCILIATION_REPORT_PATH = "quality/presentation_asset_reconciliation_report.json"
ASSET_MANIFEST_PATH = "assets/data/asset_manifest.json"
CANONICAL_BLUEPRINT_PATH = "presentation/presentation_blueprint.json"
MEDIA_REQUEST_PLAN_PATH = "presentation/presentation_media_request_plan.json"
MEDIA_ASSET_LINK_PLAN_PATH = "presentation/presentation_media_asset_links.shadow.json"
MEDIA_PROJECTION_LINK_PLAN_PATH = "presentation/presentation_media_projection_links.shadow.json"
TEACHER_MARKERS = ("teacher-only", "teacher only", "private", "rubric", "observation notes")


def reconcile_presentation_content_assets(
    content_plan: PresentationContentPlan,
    asset_manifest: AssetManifest,
    media_request_plan: PresentationMediaRequestPlan | None = None,
    media_asset_links: PresentationMediaAssetLinkPlan | None = None,
    media_projection_links: PresentationMediaProjectionLinkPlan | None = None,
) -> tuple[PresentationContentPlan, PresentationAssetReconciliationReport]:
    """Return a copy with only valid, deterministic audio references attached."""
    report = PresentationAssetReconciliationReport()
    reconciled = content_plan.model_copy(deep=True)
    all_assets = {asset.id: asset for group in (asset_manifest.images, asset_manifest.audio, asset_manifest.video, asset_manifest.fonts) for asset in group}
    valid_audio = sorted((asset for asset in asset_manifest.audio if asset.path), key=lambda asset: asset.id)
    request_by_content = {request.content_item_id: request for request in (media_request_plan.requests if media_request_plan else [])}
    links_by_request: dict[str, list] = {}
    for link in (media_asset_links.links if media_asset_links else []):
        links_by_request.setdefault(link.media_request_id, []).append(link)
    projection_links_by_request: dict[str, list] = {}
    for link in (media_projection_links.links if media_projection_links else []):
        if link.match_class in {"exact", "linkable"}:
            projection_links_by_request.setdefault(link.shadow_request_id, []).append(link)

    for item in reconciled.content_items:
        before = item.model_dump(mode="json")
        if item.presentation_mode != "listening_choice":
            continue
        report.assessed_audio_items += 1
        finding = _reconcile_item(item, all_assets, valid_audio, request_by_content.get(item.id), links_by_request, projection_links_by_request)
        report.findings.append(finding)
        if finding.state == "pass":
            report.reconciled_audio_items += 1
        elif finding.state == "blocked":
            report.unresolved_audio_items.append(item.id)
            _block(report, f"listening_choice item '{item.id}' has no deterministically traceable available audio asset.")
            if any("not an audio asset" in warning or "not ready" in warning or "absent from AssetManifest" in warning for warning in finding.warnings):
                report.invalid_asset_findings.extend(finding.warnings)
            else:
                report.missing_asset_findings.extend(finding.warnings)
        if finding.matching_strategy == "ambiguous":
            report.ambiguous_audio_items.append(item.id)
        for warning in finding.warnings:
            _warn(report, f"{item.id}: {warning}")
        after = item.model_dump(mode="json")
        for key in set(before) | set(after):
            if key != "audio_asset_refs" and before.get(key) != after.get(key):
                report.mutated_non_asset_fields.append(f"{item.id}.{key}")

    expected = {item.presentation_unit_id for item in reconciled.content_items}
    traced = {item.presentation_unit_id for item in reconciled.content_items if item.trace.presentation_unit_id == item.presentation_unit_id}
    report.trace_coverage = len(expected & traced) / len(expected) if expected else 1.0
    if report.trace_coverage != 1.0:
        _block(report, "Content-item trace coverage is incomplete after reconciliation.")
    if report.mutated_non_asset_fields:
        _block(report, "Reconciliation changed non-asset content fields.")
    if _teacher_leakage(reconciled):
        _block(report, "Teacher-only content appears in learner-facing reconciled content.")
    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    report.notes.append("Only existing AssetManifest audio entries with non-empty paths are eligible for attachment.")
    return reconciled, report


def run_post_media_presentation_reconciliation(
    project_id: str,
    asset_manifest: AssetManifest | None = None,
) -> PresentationAssetReconciliationReport:
    """Write reconciled shadow artifacts after the authoritative media manifest exists."""
    source_payload = read_json(project_id, CONTENT_PLAN_PATH)
    if source_payload is None:
        report = PresentationAssetReconciliationReport(state="blocked", blocking=[f"Missing source content plan at '{CONTENT_PLAN_PATH}'."])
        write_json(project_id, RECONCILIATION_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
        return report
    content_plan = PresentationContentPlan.model_validate(source_payload)
    manifest = asset_manifest or read_model(project_id, "asset_manifest.json", AssetManifest)
    if manifest is None:
        report = PresentationAssetReconciliationReport(state="blocked", blocking=[f"Missing authoritative AssetManifest at '{ASSET_MANIFEST_PATH}'."])
        write_json(project_id, RECONCILIATION_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
        return report

    request_payload = read_json(project_id, MEDIA_REQUEST_PLAN_PATH)
    links_payload = read_json(project_id, MEDIA_ASSET_LINK_PLAN_PATH)
    projection_links_payload = read_json(project_id, MEDIA_PROJECTION_LINK_PLAN_PATH)
    request_plan = PresentationMediaRequestPlan.model_validate(request_payload) if request_payload else None
    link_plan = PresentationMediaAssetLinkPlan.model_validate(links_payload) if links_payload else None
    projection_link_plan = PresentationMediaProjectionLinkPlan.model_validate(projection_links_payload) if projection_links_payload else None
    reconciled, report = reconcile_presentation_content_assets(content_plan, manifest, request_plan, link_plan, projection_link_plan)
    write_json(project_id, RECONCILED_CONTENT_PLAN_PATH, reconciled.model_dump(mode="json", by_alias=True))
    content_report = evaluate_presentation_content_plan(reconciled)
    write_json(project_id, CONTENT_REPORT_PATH, content_report.model_dump(mode="json", by_alias=True))
    report.recomputed_reports.append(CONTENT_REPORT_PATH)

    canonical_payload = read_json(project_id, CANONICAL_BLUEPRINT_PATH)
    if canonical_payload is not None:
        canonical = CanonicalPresentationBlueprint.model_validate(canonical_payload)
        canonical = attach_content_references(canonical, reconciled)
        write_json(project_id, CANONICAL_BLUEPRINT_PATH, canonical.model_dump(mode="json", by_alias=True))
        report.recomputed_reports.append(CANONICAL_BLUEPRINT_PATH)
        _recompute_downstream(project_id, report)
    else:
        _warn(report, f"Canonical shadow blueprint is unavailable at '{CANONICAL_BLUEPRINT_PATH}'.")
    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    write_json(project_id, RECONCILIATION_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    return report


def _reconcile_item(item, all_assets, valid_audio, media_request, links_by_request, projection_links_by_request) -> PresentationAssetReconciliationFinding:
    requested = list(item.audio_asset_refs)
    finding = PresentationAssetReconciliationFinding(
        content_item_id=item.id,
        presentation_unit_id=item.presentation_unit_id,
        activity_id=item.activity_id,
        evidence_ids=list(item.evidence_ids),
        presentation_mode=item.presentation_mode,
        requested_asset_refs=requested,
    )
    if item.teacher_channel_reference:
        finding.matching_strategy = "teacher_only"
        finding.state = "warning"
        finding.warnings.append("Teacher-only item is not eligible for learner audio attachment.")
        return finding

    strategy, candidates, invalid = _candidates(item, requested, all_assets, valid_audio, media_request, links_by_request, projection_links_by_request)
    finding.matching_strategy = strategy
    finding.candidate_count = len(candidates)
    if invalid:
        finding.state = "blocked"
        finding.warnings.extend(invalid)
        item.audio_asset_refs = []
        return finding
    if not candidates:
        finding.state = "blocked"
        finding.warnings.append("No asset matched an explicit, trace, language-item, or exact target-text linkage.")
        item.audio_asset_refs = []
        return finding
    if len(candidates) > 1:
        finding.matching_strategy = "ambiguous"
        finding.state = "blocked"
        finding.warnings.append("Multiple equally strong audio candidates exist; no stable preference rule is available.")
        item.audio_asset_refs = []
        return finding

    asset = candidates[0]
    matched = AssetReference(
        asset_id=asset.id,
        asset_type="audio",
        path_or_key=asset.path,
        availability="available",
        provenance=["assets/data/asset_manifest.json", strategy, asset.id],
    )
    item.audio_asset_refs = [matched]
    finding.matched_asset_refs = [matched]
    finding.state = "pass"
    return finding


def _candidates(item, requested, all_assets, valid_audio, media_request, links_by_request, projection_links_by_request):
    if media_request:
        direct_assets = [asset for asset in all_assets.values() if asset.media_request_id == media_request.id]
        if direct_assets:
            invalid = []
            candidates = []
            for asset in direct_assets:
                if asset.kind != "audio":
                    invalid.append(f"Asset '{asset.id}' claiming media_request_id is not an audio asset.")
                elif not asset.path:
                    invalid.append(f"Asset '{asset.id}' claiming media_request_id is not ready because its path is empty.")
                else:
                    candidates.append(asset)
            return "media_request_id", candidates, invalid
        projection_links = projection_links_by_request.get(media_request.id, [])
        if projection_links:
            projected_ids = [link.legacy_requirement_id for link in projection_links]
            origin_candidates = [asset for asset in all_assets.values() if any(
                requirement_id in asset.origin_media_requirement_ids for requirement_id in projected_ids
            )]
            if origin_candidates:
                invalid = []
                candidates = []
                for asset in origin_candidates:
                    if asset.kind != "audio":
                        invalid.append(f"Origin-traced asset '{asset.id}' is not an audio asset.")
                    elif not asset.path:
                        invalid.append(f"Origin-traced asset '{asset.id}' is not ready because its path is empty.")
                    else:
                        candidates.append(asset)
                return "origin_media_requirement_id", candidates, invalid
            invalid = []
            candidates = []
            for asset_id in projected_ids:
                asset = all_assets.get(asset_id)
                if asset is None:
                    invalid.append(f"Projected legacy requirement asset '{asset_id}' is absent from AssetManifest.")
                elif asset.kind != "audio":
                    invalid.append(f"Projected legacy requirement asset '{asset_id}' is not an audio asset.")
                elif not asset.path:
                    invalid.append(f"Projected legacy requirement asset '{asset_id}' is not ready because its path is empty.")
                else:
                    candidates.append(asset)
            return "projection_legacy_requirement_id", candidates, invalid
        links = links_by_request.get(media_request.id, [])
        if any(link.state in {"ambiguous", "failed"} for link in links):
            return "media_request_id", [], ["Shadow media request linkage is ambiguous or incompatible."]
        linked_ids = [link.asset_id for link in links if link.state == "linked_to_existing_asset" and link.asset_id]
        if linked_ids:
            invalid = []
            candidates = []
            for asset_id in linked_ids:
                asset = all_assets.get(asset_id)
                if asset is None:
                    invalid.append(f"Linked media_request_id asset '{asset_id}' is absent from AssetManifest.")
                elif asset.kind != "audio":
                    invalid.append(f"Linked media_request_id asset '{asset_id}' is not an audio asset.")
                elif not asset.path:
                    invalid.append(f"Linked media_request_id asset '{asset_id}' is not ready because its path is empty.")
                else:
                    candidates.append(asset)
            return "media_request_id", candidates, invalid
    explicit_ids = sorted({ref.asset_id for ref in requested if ref.asset_id})
    if explicit_ids:
        invalid = []
        candidates = []
        for asset_id in explicit_ids:
            asset = all_assets.get(asset_id)
            if asset is None:
                invalid.append(f"Explicit audio reference '{asset_id}' is absent from AssetManifest.")
            elif asset.kind != "audio":
                invalid.append(f"Explicit reference '{asset_id}' is not an audio asset.")
            elif not asset.path:
                invalid.append(f"Explicit audio reference '{asset_id}' is not ready because its path is empty.")
            else:
                candidates.append(asset)
        return "explicit_asset_id", candidates, invalid

    trace_ids = {item.presentation_unit_id, item.activity_id, *item.evidence_ids}
    candidates = [asset for asset in valid_audio if asset.id in trace_ids]
    if candidates:
        return "trace_id", candidates, []
    language_ids = set(item.language_items)
    candidates = [asset for asset in valid_audio if asset.id in language_ids]
    if candidates:
        return "language_item_id", candidates, []
    target_text = set(item.display_items) | {response.normalized_value for response in item.accepted_responses}
    candidates = [asset for asset in valid_audio if asset.text and asset.text in target_text]
    if candidates:
        return "exact_approved_text", candidates, []
    return "none", [], []


def _teacher_leakage(plan: PresentationContentPlan) -> bool:
    for item in plan.content_items:
        if item.teacher_channel_reference and any((item.prompt, item.learner_instructions, item.display_items, item.options, item.matching_pairs)):
            return True
        if item.teacher_channel_reference and any(marker in str(item.model_dump(mode="json")).lower() for marker in TEACHER_MARKERS):
            return True
    return False


def _recompute_downstream(project_id: str, report: PresentationAssetReconciliationReport) -> None:
    from .presentation_parity import run_presentation_parity_harness
    from .presentation_adapter_assessment import run_presentation_adapter_assessment

    parity = run_presentation_parity_harness(project_id)
    report.recomputed_reports.extend([
        "presentation/legacy_blueprint_from_v2.shadow.json",
        "quality/presentation_parity_report.json",
    ])
    assessment = run_presentation_adapter_assessment(project_id)
    report.recomputed_reports.extend([
        "presentation/legacy_component_mapping.shadow.json",
        "quality/presentation_adapter_assessment_report.json",
    ])
    if parity.state == "blocked":
        _block(report, "Recomputed presentation parity report is blocked.")
    if assessment.state == "blocked":
        _block(report, "Recomputed presentation adapter assessment report is blocked.")


def _block(report: PresentationAssetReconciliationReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: PresentationAssetReconciliationReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
