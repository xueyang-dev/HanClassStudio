"""Shadow-only deterministic media request identities for presentation content."""

from __future__ import annotations

from hashlib import sha256

from .models import (
    AssetManifest,
    PresentationContentPlan,
    PresentationMediaAssetLink,
    PresentationMediaAssetLinkPlan,
    PresentationMediaRequest,
    PresentationMediaRequestPlan,
    PresentationMediaRequestReport,
)
from .storage import read_json, read_model, write_json


CONTENT_PLAN_PATH = "presentation/presentation_content_plan.json"
REQUEST_PLAN_PATH = "presentation/presentation_media_request_plan.json"
REQUEST_REPORT_PATH = "quality/presentation_media_request_report.json"
ASSET_LINK_PLAN_PATH = "presentation/presentation_media_asset_links.shadow.json"
ASSET_MANIFEST_PATH = "assets/data/asset_manifest.json"
NAMESPACE = "hanclassstudio.presentation_media_requests.v1"


def build_presentation_media_request_plan(
    content_plan: PresentationContentPlan,
) -> tuple[PresentationMediaRequestPlan, PresentationMediaRequestReport]:
    """Create planned request identities without submitting or generating media."""
    report = PresentationMediaRequestReport(source_artifacts_checked=list(content_plan.source_artifacts))
    requests: list[PresentationMediaRequest] = []
    for item in content_plan.content_items:
        if item.presentation_mode != "listening_choice":
            continue
        if item.teacher_channel_reference:
            report.teacher_only_requests.append(item.id)
            continue
        source_text = _source_text(item)
        if not source_text:
            report.missing_source_findings.append(item.id)
            _block(report, f"Required listening media request for '{item.id}' has no approved source text.")
            continue
        request = PresentationMediaRequest(
            id=_request_id(item.id, item.presentation_unit_id, "audio", "listening_prompt", source_text, item.language_items),
            content_item_id=item.id,
            presentation_unit_id=item.presentation_unit_id,
            activity_id=item.activity_id,
            evidence_ids=list(item.evidence_ids),
            media_type="audio",
            media_role="listening_prompt",
            source_text=source_text,
            source_language_item_ids=list(item.language_items),
            required=True,
            generation_constraints=["approved_content_only", "target_language_audio"],
            expected_asset_type="audio",
            status="planned",
            provenance=[CONTENT_PLAN_PATH, item.id],
            trace=item.trace,
        )
        requests.append(request)

    _validate_requests(requests, report)
    plan = PresentationMediaRequestPlan(
        requests=requests,
        warnings=list(report.warnings),
        trace=[request.trace for request in requests],
    )
    report.requests_count = len(requests)
    report.required_requests_count = sum(request.required for request in requests)
    report.optional_requests_count = report.requests_count - report.required_requests_count
    report.complete_requests_count = sum(bool(request.source_text) for request in requests)
    report.incomplete_requests_count = report.requests_count - report.complete_requests_count
    expected = {request.content_item_id for request in requests}
    traced = {request.content_item_id for request in requests if request.trace.presentation_unit_id == request.presentation_unit_id}
    report.trace_coverage = len(expected & traced) / len(expected) if expected else 1.0
    if report.trace_coverage != 1.0:
        _block(report, "Media request trace coverage is incomplete.")
    if requests:
        _warn(report, "Shadow media requests are planned only; production media generation does not consume them.")
    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    report.notes.append("AssetManifest has no direct request-trace field; post-media shadow linkage is used.")
    return plan, report


def run_presentation_media_request_shadow(project_id: str) -> PresentationMediaRequestReport:
    payload = read_json(project_id, CONTENT_PLAN_PATH)
    if payload is None:
        report = PresentationMediaRequestReport(state="blocked", blocking=[f"Missing content plan at '{CONTENT_PLAN_PATH}'."])
        write_json(project_id, REQUEST_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
        return report
    plan, report = build_presentation_media_request_plan(PresentationContentPlan.model_validate(payload))
    write_json(project_id, REQUEST_PLAN_PATH, plan.model_dump(mode="json", by_alias=True))
    write_json(project_id, REQUEST_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    return report


def link_presentation_media_requests_to_assets(
    request_plan: PresentationMediaRequestPlan,
    asset_manifest: AssetManifest,
) -> PresentationMediaAssetLinkPlan:
    """Build a diagnostic request-to-existing-asset map without modifying media assets."""
    all_assets = {asset.id: asset for group in (asset_manifest.images, asset_manifest.audio, asset_manifest.video, asset_manifest.fonts) for asset in group}
    valid_audio = sorted((asset for asset in asset_manifest.audio if asset.path), key=lambda asset: asset.id)
    links: list[PresentationMediaAssetLink] = []
    for request in request_plan.requests:
        if request.media_type != "audio":
            continue
        direct_assets = [asset for asset in all_assets.values() if asset.media_request_id == request.id]
        if not direct_assets and request.id in all_assets:
            direct_assets = [all_assets[request.id]]
        if direct_assets:
            if len(direct_assets) > 1:
                links.append(PresentationMediaAssetLink(
                    media_request_id=request.id,
                    matching_strategy="media_request_id",
                    candidate_count=len(direct_assets),
                    state="ambiguous",
                    warnings=["Multiple assets claim the same media_request_id."],
                ))
                continue
            direct = direct_assets[0]
            if direct.kind != "audio" or not direct.path:
                links.append(PresentationMediaAssetLink(
                    media_request_id=request.id,
                    matching_strategy="media_request_id",
                    candidate_count=1,
                    state="failed",
                    warnings=["Asset claiming media_request_id is incompatible or unavailable."],
                ))
                continue
            links.append(PresentationMediaAssetLink(
                media_request_id=request.id,
                asset_id=direct.id,
                matching_strategy="media_request_id",
                candidate_count=1,
                state="linked_to_existing_asset",
            ))
            continue
        candidates = [asset for asset in valid_audio if asset.id in request.source_language_item_ids]
        strategy = "language_item_id"
        if not candidates:
            candidates = [asset for asset in valid_audio if asset.text and asset.text == request.source_text]
            strategy = "exact_approved_text"
        if not candidates:
            links.append(PresentationMediaAssetLink(media_request_id=request.id, matching_strategy="none", state="unavailable"))
        elif len(candidates) == 1:
            links.append(PresentationMediaAssetLink(
                media_request_id=request.id,
                asset_id=candidates[0].id,
                matching_strategy=strategy,
                candidate_count=1,
                state="linked_to_existing_asset",
            ))
        else:
            links.append(PresentationMediaAssetLink(
                media_request_id=request.id,
                matching_strategy="ambiguous",
                candidate_count=len(candidates),
                state="ambiguous",
                warnings=["Multiple equally valid manifest assets match this shadow request."],
            ))
    return PresentationMediaAssetLinkPlan(links=links)


def run_presentation_media_asset_linkage(project_id: str, asset_manifest: AssetManifest | None = None) -> PresentationMediaAssetLinkPlan | None:
    payload = read_json(project_id, REQUEST_PLAN_PATH)
    manifest = asset_manifest or read_model(project_id, "asset_manifest.json", AssetManifest)
    if payload is None or manifest is None:
        return None
    links = link_presentation_media_requests_to_assets(PresentationMediaRequestPlan.model_validate(payload), manifest)
    write_json(project_id, ASSET_LINK_PLAN_PATH, links.model_dump(mode="json", by_alias=True))
    return links


def _request_id(content_item_id: str, unit_id: str, media_type: str, media_role: str, source_text: str, language_ids: list[str]) -> str:
    identity = "|".join([NAMESPACE, content_item_id, unit_id, media_type, media_role, source_text.strip(), *sorted(language_ids)])
    return f"pmr_{sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _source_text(item) -> str:
    if item.accepted_responses:
        return item.accepted_responses[0].normalized_value
    return next((value for value in item.display_items if value), "")


def _validate_requests(requests: list[PresentationMediaRequest], report: PresentationMediaRequestReport) -> None:
    seen: set[tuple[str, str, str]] = set()
    ids: set[str] = set()
    for request in requests:
        semantic_key = (request.content_item_id, request.media_type, request.media_role)
        if semantic_key in seen or request.id in ids:
            report.duplicate_requests.append(request.id)
            _block(report, f"Duplicate primary media request '{request.id}'.")
        seen.add(semantic_key)
        ids.add(request.id)


def _block(report: PresentationMediaRequestReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: PresentationMediaRequestReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
