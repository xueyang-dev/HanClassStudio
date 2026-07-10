"""Diagnostic-only comparison of shadow media requests with legacy media requirements."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .models import (
    AssetManifest,
    PresentationMediaProjectionFinding,
    PresentationMediaProjectionLink,
    PresentationMediaProjectionLinkPlan,
    PresentationMediaProjectionReport,
    PresentationMediaRequest,
    PresentationMediaRequestPlan,
    PresentationTrace,
)
from .storage import read_json, read_model, write_json


REQUEST_PLAN_PATH = "presentation/presentation_media_request_plan.json"
LEGACY_MEDIA_PLAN_PATH = "blueprints/media_plan.json"
ASSET_MANIFEST_PATH = "assets/data/asset_manifest.json"
PROJECTION_REPORT_PATH = "quality/presentation_media_projection_report.json"
PROJECTION_LINK_PLAN_PATH = "presentation/presentation_media_projection_links.shadow.json"


@dataclass(frozen=True)
class _LegacyRequirement:
    id: str
    media_type: str
    source_text: str
    media_role: str | None
    language_item_ids: tuple[str, ...]
    media_request_id: str | None
    content_item_id: str | None
    presentation_unit_id: str | None
    teacher_only: bool


def audit_presentation_media_projection(
    request_plan: PresentationMediaRequestPlan,
    legacy_media_plan: dict[str, Any],
    asset_manifest: AssetManifest | None = None,
    existing_links: PresentationMediaProjectionLinkPlan | None = None,
) -> tuple[PresentationMediaProjectionReport, PresentationMediaProjectionLinkPlan]:
    """Classify compatibility without changing production requests, assets, or providers."""
    requirements = _legacy_requirements(legacy_media_plan)
    report = PresentationMediaProjectionReport(
        shadow_requests_count=len(request_plan.requests),
        legacy_requirements_count=len(requirements),
        source_artifacts_checked=[REQUEST_PLAN_PATH, LEGACY_MEDIA_PLAN_PATH] + ([ASSET_MANIFEST_PATH] if asset_manifest else []),
    )
    links: list[PresentationMediaProjectionLink] = []
    related_legacy_ids: set[str] = set()
    existing_by_request = {link.shadow_request_id: link for link in (existing_links.links if existing_links else [])}

    for request in request_plan.requests:
        finding, safe_link, related = _project_request(request, requirements, existing_by_request.get(request.id))
        report.findings.append(finding)
        related_legacy_ids.update(related)
        if safe_link is not None:
            links.append(safe_link)
        _count_finding(report, finding)

    for requirement in requirements:
        if requirement.id in related_legacy_ids:
            continue
        report.legacy_only_requirements_count += 1
        report.findings.append(_legacy_only_finding(requirement))

    _validate_asset_chain(report, links, asset_manifest, requirements)
    _validate_duplicate_links(report, links)
    expected = {request.id for request in request_plan.requests}
    traced = {finding.shadow_request_id for finding in report.findings if finding.shadow_request_id and finding.trace.presentation_unit_id == finding.presentation_unit_id}
    report.trace_coverage = len(expected & traced) / len(expected) if expected else 1.0
    if report.trace_coverage != 1.0:
        _block(report, "Shadow media-request trace coverage is incomplete.")
    if report.ambiguous_matches_count or report.unlinkable_shadow_requests_count or report.media_type_mismatches or report.role_mismatches:
        _block(report, "One or more required shadow media requests cannot be safely projected.")
    if report.approximate_matches_count or report.legacy_only_requirements_count:
        _warn(report, "Approximate or legacy-only media requirements remain diagnostic-only.")
    report.projection_safe_for_experiment = not report.blocking and all(link.match_class in {"exact", "linkable"} for link in links)
    report.state = "blocked" if report.blocking else "warning" if report.warnings else "pass"
    report.notes.extend([
        "Legacy media-plan IDs are compatibility keys; slide_id is deliberately excluded from projection.",
        "Explicit AssetManifest origin metadata is preferred over the historical AssetFile.id compatibility convention.",
    ])
    return report, PresentationMediaProjectionLinkPlan(links=links, warnings=list(report.warnings))


def run_presentation_media_projection_audit(
    project_id: str,
    asset_manifest: AssetManifest | None = None,
) -> PresentationMediaProjectionReport:
    """Opt-in artifact writer; this never submits a request or changes generated media."""
    request_payload = read_json(project_id, REQUEST_PLAN_PATH)
    legacy_plan = read_json(project_id, LEGACY_MEDIA_PLAN_PATH)
    if request_payload is None or legacy_plan is None:
        missing = REQUEST_PLAN_PATH if request_payload is None else LEGACY_MEDIA_PLAN_PATH
        report = PresentationMediaProjectionReport(state="blocked", blocking=[f"Missing projection input at '{missing}'."])
        write_json(project_id, PROJECTION_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
        return report
    manifest = asset_manifest or read_model(project_id, "asset_manifest.json", AssetManifest)
    existing_payload = read_json(project_id, PROJECTION_LINK_PLAN_PATH)
    existing_links = PresentationMediaProjectionLinkPlan.model_validate(existing_payload) if existing_payload else None
    report, links = audit_presentation_media_projection(
        PresentationMediaRequestPlan.model_validate(request_payload), legacy_plan, manifest, existing_links,
    )
    write_json(project_id, PROJECTION_REPORT_PATH, report.model_dump(mode="json", by_alias=True))
    write_json(project_id, PROJECTION_LINK_PLAN_PATH, links.model_dump(mode="json", by_alias=True))
    return report


def _legacy_requirements(media_plan: dict[str, Any]) -> list[_LegacyRequirement]:
    requirements: list[_LegacyRequirement] = []
    for media_type, field, text_field in (("audio", "audio", "text"), ("image", "images", "prompt")):
        for raw in media_plan.get(field, []) if isinstance(media_plan, dict) else []:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            language_ids = raw.get("language_item_ids") or raw.get("source_language_item_ids") or []
            requirements.append(_LegacyRequirement(
                id=str(raw["id"]), media_type=media_type, source_text=str(raw.get(text_field) or raw.get("source_text") or ""),
                media_role=str(raw["media_role"] or raw["role"]) if raw.get("media_role") or raw.get("role") else None,
                language_item_ids=tuple(sorted(str(value) for value in language_ids)),
                media_request_id=str(raw["media_request_id"]) if raw.get("media_request_id") else None,
                content_item_id=str(raw["content_item_id"]) if raw.get("content_item_id") else None,
                presentation_unit_id=str(raw["presentation_unit_id"]) if raw.get("presentation_unit_id") else None,
                teacher_only=bool(raw.get("teacher_only")),
            ))
    return sorted(requirements, key=lambda item: (item.media_type, item.id))


def _project_request(
    request: PresentationMediaRequest,
    requirements: list[_LegacyRequirement],
    existing_link: PresentationMediaProjectionLink | None = None,
) -> tuple[PresentationMediaProjectionFinding, PresentationMediaProjectionLink | None, set[str]]:
    if _teacher_only_request(request):
        finding = _finding(request, "unlinkable", "teacher_only", 0.0)
        finding.blocking_reasons.append("Teacher-only media request cannot project to a learner-facing legacy requirement.")
        return finding, None, set()
    incompatible_identity = [item for item in requirements if item.media_request_id == request.id and item.media_type != request.media_type]
    if incompatible_identity:
        return _mismatch(request, incompatible_identity, "media_type", "Shared media_request_id has incompatible media type.")
    same_identity = [item for item in requirements if item.media_request_id == request.id]
    if same_identity:
        return _select(request, same_identity, "media_request_id", "exact", 1.0)
    if existing_link and _valid_existing_link(existing_link, request):
        linked_requirement = [item for item in requirements if item.id == existing_link.legacy_requirement_id]
        if linked_requirement:
            return _select(request, linked_requirement, "explicit_shadow_link", "linkable", 0.95)
    type_candidates = [item for item in requirements if item.media_type == request.media_type]
    language_ids = set(request.source_language_item_ids)
    language_matches = [item for item in type_candidates if language_ids and (set(item.language_item_ids) == language_ids or item.id in language_ids)]
    if language_matches:
        return _select(request, language_matches, "language_item_identity", "linkable", 0.9)
    trace_matches = [item for item in type_candidates if item.content_item_id == request.content_item_id or item.presentation_unit_id == request.presentation_unit_id]
    if trace_matches:
        return _select(request, trace_matches, "compatibility_trace", "linkable", 0.85)
    text_matches = [item for item in type_candidates if item.source_text and item.source_text == request.source_text]
    if text_matches:
        role_mismatch = [item for item in text_matches if item.media_role and item.media_role != request.media_role]
        if role_mismatch:
            return _mismatch(request, role_mismatch, "role", "Legacy media role is incompatible with the shadow request.")
        return _select(request, text_matches, "exact_source_text", "approximate", 0.55)
    wrong_type_text = [item for item in requirements if item.source_text and item.source_text == request.source_text and item.media_type != request.media_type]
    if wrong_type_text:
        return _mismatch(request, wrong_type_text, "media_type", "Matching legacy source text has an incompatible media type.")
    match_class = "unlinkable" if request.required else "shadow_only"
    finding = _finding(request, match_class, "none", 0.0)
    finding.blocking_reasons.append("No compatible legacy media requirement exists.")
    return finding, None, set()


def _select(request, candidates, strategy: str, match_class: str, confidence: float):
    compatible = [item for item in candidates if item.media_type == request.media_type and not item.teacher_only and (not item.media_role or item.media_role == request.media_role)]
    if not compatible:
        return _mismatch(request, candidates, "role", "Legacy media role is incompatible with the shadow request.")
    ids = sorted({item.id for item in compatible})
    if len(compatible) != 1 or len(ids) != 1:
        finding = _finding(request, "ambiguous", strategy, confidence, ids)
        finding.blocking_reasons.append("Multiple equally valid legacy requirements exist; no stable preference rule is available.")
        return finding, None, set(ids)
    selected = compatible[0]
    finding = _finding(request, match_class, strategy, confidence, ids, selected.id)
    if match_class == "approximate":
        finding.warnings.append("Text equality is insufficient for an authoritative shadow link.")
        return finding, None, set(ids)
    if selected.media_role is None and match_class == "linkable":
        finding.warnings.append("Legacy media plan omits media_role; link remains compatibility-only.")
    link = PresentationMediaProjectionLink(
        shadow_request_id=request.id, legacy_requirement_id=selected.id, match_class=match_class,
        matching_strategy=strategy, source_fingerprint=_fingerprint(request.source_text),
        media_type=request.media_type, media_role=request.media_role, trace=request.trace,
    )
    return finding, link, set(ids)


def _mismatch(request, candidates, kind: str, reason: str):
    ids = sorted({item.id for item in candidates})
    finding = _finding(request, "unlinkable", f"{kind}_mismatch", 0.0, ids)
    finding.blocking_reasons.append(reason)
    return finding, None, set(ids)


def _finding(request, match_class, strategy, confidence, candidates=None, selected=None):
    return PresentationMediaProjectionFinding(
        shadow_request_id=request.id, content_item_id=request.content_item_id, presentation_unit_id=request.presentation_unit_id,
        activity_id=request.activity_id, evidence_ids=list(request.evidence_ids), media_type=request.media_type,
        media_role=request.media_role, shadow_source_text=request.source_text,
        shadow_language_item_ids=list(request.source_language_item_ids), candidate_legacy_requirement_ids=candidates or [],
        selected_legacy_requirement_id=selected, match_class=match_class, matching_strategy=strategy,
        confidence=confidence, trace=request.trace,
    )


def _legacy_only_finding(requirement: _LegacyRequirement) -> PresentationMediaProjectionFinding:
    return PresentationMediaProjectionFinding(
        shadow_request_id="", content_item_id="", presentation_unit_id="", activity_id="", media_type=requirement.media_type,
        media_role=requirement.media_role or "unknown", shadow_source_text="", candidate_legacy_requirement_ids=[requirement.id],
        selected_legacy_requirement_id=requirement.id, match_class="legacy_only", matching_strategy="none", confidence=1.0,
        warnings=["Legacy media requirement has no corresponding approved shadow request."],
        trace=PresentationTrace(presentation_unit_id="", binding_id="", activity_id="", evidence_ids=[]),
    )


def _count_finding(report: PresentationMediaProjectionReport, finding: PresentationMediaProjectionFinding) -> None:
    match finding.match_class:
        case "exact": report.exact_matches_count += 1
        case "linkable": report.linkable_matches_count += 1
        case "approximate": report.approximate_matches_count += 1
        case "ambiguous":
            report.ambiguous_matches_count += 1
            for legacy_id in finding.candidate_legacy_requirement_ids:
                if legacy_id not in report.duplicate_semantic_requirements:
                    report.duplicate_semantic_requirements.append(legacy_id)
        case "unlinkable": report.unlinkable_shadow_requests_count += 1
        case "shadow_only": _warn(report, f"Optional shadow-only media request '{finding.shadow_request_id}' has no legacy counterpart.")
    if finding.matching_strategy == "media_type_mismatch":
        report.media_type_mismatches.append(finding.shadow_request_id)
    if finding.matching_strategy == "role_mismatch":
        report.role_mismatches.append(finding.shadow_request_id)


def _validate_asset_chain(report, links, asset_manifest, requirements) -> None:
    if asset_manifest is None:
        report.notes.append("Projection was evaluated before AssetManifest trace availability.")
        return
    assets = [asset for group in (asset_manifest.images, asset_manifest.audio, asset_manifest.video, asset_manifest.fonts) for asset in group]
    requirement_types = {requirement.id: requirement.media_type for requirement in requirements}
    relevant = [asset for asset in assets if asset.id in requirement_types or asset.origin_media_requirement_ids]
    report.assets_with_origin_trace = sorted(asset.id for asset in relevant if asset.origin_media_requirement_ids)
    report.assets_without_origin_trace = sorted(asset.id for asset in relevant if not asset.origin_media_requirement_ids)
    report.origin_trace_coverage = len(report.assets_with_origin_trace) / len(relevant) if relevant else 1.0
    for asset in relevant:
        origins = asset.origin_media_requirement_ids
        if len(origins) != len(set(origins)):
            report.duplicate_origin_findings.append(asset.id)
        incompatible = [origin for origin in origins if origin not in requirement_types or requirement_types[origin] != asset.kind]
        if incompatible:
            report.ambiguous_origin_findings.append(f"{asset.id}: {', '.join(sorted(incompatible))}")
    if report.ambiguous_origin_findings or report.duplicate_origin_findings:
        _block(report, "AssetManifest contains conflicting or invalid legacy media-origin metadata.")
    if relevant and not report.assets_without_origin_trace:
        report.asset_origin_trace_mode = "explicit_origin_metadata"
    elif relevant and all(asset.id in requirement_types for asset in relevant):
        report.asset_origin_trace_mode = "identity_contract"
        _warn(report, "Some historical assets rely on AssetFile.id equality rather than explicit origin metadata.")
    else:
        report.asset_origin_trace_mode = "unresolved_origin"
        if relevant:
            _warn(report, "Some relevant AssetManifest entries have no deterministic legacy media origin.")

    missing_chain: list[str] = []
    for link in links:
        explicit = [asset for asset in assets if link.legacy_requirement_id in asset.origin_media_requirement_ids]
        if explicit:
            continue
        legacy_id_asset = [asset for asset in assets if asset.id == link.legacy_requirement_id]
        if legacy_id_asset:
            _warn(report, f"Legacy requirement '{link.legacy_requirement_id}' reaches AssetManifest only through AssetFile.id compatibility.")
        else:
            missing_chain.append(link.legacy_requirement_id)
    if missing_chain:
        _block(report, f"Safe shadow projection cannot reach generated assets for: {', '.join(sorted(missing_chain))}.")
    report.projection_chain_complete = bool(links) and not missing_chain and all(
        any(link.legacy_requirement_id in asset.origin_media_requirement_ids for asset in assets) for link in links
    )


def _validate_duplicate_links(report, links) -> None:
    seen: dict[str, list[str]] = {}
    for link in links:
        seen.setdefault(link.legacy_requirement_id, []).append(link.shadow_request_id)
    for legacy_id, shadow_ids in seen.items():
        if len(shadow_ids) > 1:
            report.duplicate_semantic_requirements.append(legacy_id)
            _block(report, f"Legacy requirement '{legacy_id}' is claimed by multiple shadow requests.")


def _fingerprint(value: str) -> str:
    return sha256(value.strip().encode("utf-8")).hexdigest()[:16]


def _teacher_only_request(request: PresentationMediaRequest) -> bool:
    values = [*request.generation_constraints, *request.provenance, *request.warnings]
    return any("teacher" in value.lower() for value in values)


def _valid_existing_link(link: PresentationMediaProjectionLink, request: PresentationMediaRequest) -> bool:
    return (
        link.match_class in {"exact", "linkable"}
        and link.media_type == request.media_type
        and link.media_role == request.media_role
        and link.source_fingerprint == _fingerprint(request.source_text)
    )


def _block(report: PresentationMediaProjectionReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: PresentationMediaProjectionReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
