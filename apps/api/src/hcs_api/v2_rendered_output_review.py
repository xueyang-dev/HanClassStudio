"""Diagnostic review of rendered v2 internal HTML; it has no export authority."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from .models import (
    ActivityPlan,
    AssetManifest,
    CanonicalPresentationBlueprint,
    EvidencePlan,
    PresentationContentPlan,
    V2BrowserRuntimeObservation,
    V2RenderedOutputReviewReport,
)
from .storage import project_dir, read_json, read_model, write_json


REVIEW_PATH = "quality/v2_rendered_output_review.json"
INTERNAL_HTML_PATH = "courseware/lesson_v2_internal.html"
LEGACY_HTML_PATH = "courseware/lesson.html"
RENDER_MANIFEST_PATH = "courseware/render_manifest_v2_internal.json"
DIAGNOSTICS_DIR = "diagnostics/v2_rendered_output"
_MODE_COMPONENTS = {"listening_choice": "listen-choose", "matching_response": "match-game"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list["_Node"] = field(default_factory=list)
    text: list[str] = field(default_factory=list)


class _Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(_Node(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].text.append(data)


def run_v2_rendered_output_review(
    project_id: str,
    *,
    source_input_fingerprint: str = "",
    browser_observation: V2BrowserRuntimeObservation | None = None,
) -> V2RenderedOutputReviewReport:
    """Validate the current internal v2 HTML and write its diagnostic report.

    Browser observations are deliberately supplied by a real browser runner.  The
    backend never invents runtime success from static HTML inspection.
    """
    root = project_dir(project_id)
    report = V2RenderedOutputReviewReport(source_input_fingerprint=source_input_fingerprint)
    html_path = root / INTERNAL_HTML_PATH
    if not html_path.exists():
        _block(report, f"Internal v2 HTML is missing: {INTERNAL_HTML_PATH}")
        return _write(project_id, report)

    canonical = _read(project_id, "presentation/presentation_blueprint.json", CanonicalPresentationBlueprint, report)
    content = _read(project_id, "presentation/presentation_content_plan.reconciled.json", PresentationContentPlan, report)
    evidence = _read(project_id, "learning/evidence_plan.json", EvidencePlan, report)
    activities = _read(project_id, "learning/activity_plan.json", ActivityPlan, report)
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest) or AssetManifest()
    if not canonical or not content or not evidence or not activities:
        return _write(project_id, report)

    raw_html = html_path.read_text(encoding="utf-8")
    _check_render_manifest(report, root)
    _check_runtime_independence(report, raw_html)
    dom = _parse(raw_html, report)
    if dom is None:
        return _write(project_id, report)
    report.normalized_dom_fingerprint = _fingerprint(_normalize(dom.root))
    report.deterministic_dom = True
    _check_document(report, dom.root)
    _check_assets(report, root, dom.root, manifest)
    _check_units_and_content(report, dom.root, canonical, content)
    _check_teacher_safety(report, dom.root, raw_html, evidence, activities)
    _check_accessibility(report, dom.root)
    _compare_legacy(report, root, dom.root, canonical, content)
    _apply_browser_observation(report, browser_observation)
    _finish(report)
    return _write(project_id, report)


def clear_v2_rendered_output_diagnostics(project_id: str) -> None:
    """Drop stale v2-only review evidence before a new internal render."""
    root = project_dir(project_id)
    for path in (root / REVIEW_PATH, root / DIAGNOSTICS_DIR):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _read(project_id: str, path: str, model_type, report):
    payload = read_json(project_id, path)
    if payload is None:
        _block(report, f"Rendered-output review requires {path}.")
        return None
    try:
        return model_type.model_validate(payload)
    except Exception as exc:
        _block(report, f"Rendered-output review cannot validate {path}: {exc}")
        return None


def _parse(raw: str, report) -> _Document | None:
    try:
        document = _Document()
        document.feed(raw)
        document.close()
        return document
    except Exception as exc:  # pragma: no cover - HTMLParser is defensive
        _block(report, f"Internal v2 HTML cannot be parsed: {exc}")
        return None


def _check_document(report, root: _Node) -> None:
    html = _find(root, lambda node: node.tag == "html")
    if not html or not html.attrs.get("lang"):
        _block(report, "Rendered document is missing a language declaration.")
    if not _find(root, lambda node: node.tag == "style"):
        _block(report, "Rendered document has no inline stylesheet.")
    if not _find(root, lambda node: node.tag == "script"):
        _block(report, "Rendered document has no runtime script.")
    if not _find(root, lambda node: node.tag == "main" and node.attrs.get("id") == "slides"):
        _block(report, "Rendered document has no lesson stage.")


def _check_render_manifest(report, root: Path) -> None:
    manifest_path = root / RENDER_MANIFEST_PATH
    if not manifest_path.exists():
        _block(report, f"Internal v2 render manifest is missing: {RENDER_MANIFEST_PATH}")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _block(report, "Internal v2 render manifest is invalid JSON.")
        return
    if manifest.get("entry") != INTERNAL_HTML_PATH:
        _block(report, "Internal v2 render manifest points to the wrong entry file.")


def _check_runtime_independence(report, raw_html: str) -> None:
    for forbidden in ("courseware/lesson.html", "blueprints/lesson_blueprint.json"):
        if forbidden in raw_html:
            _block(report, f"Internal v2 HTML depends on production artifact '{forbidden}'.")


def _check_assets(report, root: Path, dom: _Node, manifest: AssetManifest) -> None:
    available = {asset.id: asset for asset in [*manifest.images, *manifest.audio]}
    for node in _nodes(dom, lambda item: item.tag == "button" and "audio-button" in _classes(item)):
        path = node.attrs.get("data-audio", "")
        if not path:
            _block(report, "A learner audio control has no loadable audio path.")
            continue
        resolved = (root / "courseware" / path).resolve()
        if not str(resolved).startswith(str(root.resolve())) or not resolved.exists():
            report.missing_assets.append(path)
            _block(report, f"Audio path is missing: {path}")
    for node in _nodes(dom, lambda item: item.tag == "img"):
        src = node.attrs.get("src", "")
        if src and not (root / "courseware" / src).resolve().exists():
            report.broken_links.append(src)
            _block(report, f"Image path is broken: {src}")
        if src and not node.attrs.get("alt"):
            report.accessibility_findings.append(f"Image '{src}' has no alt text.")
    # The file check above is authoritative for the rendered path.  Keep the
    # manifest read to make this contract explicit and reject a stale asset id.
    for node in _nodes(dom, lambda item: item.tag == "button" and item.attrs.get("data-audio")):
        path = node.attrs["data-audio"]
        if not any(path == f"../{asset.path}" for asset in available.values()):
            _block(report, f"Audio path is absent from the current AssetManifest: {path}")


def _check_units_and_content(report, dom: _Node, canonical, content) -> None:
    learner_units = [unit for unit in canonical.presentation_units if unit.learner_channel and not unit.teacher_channel_reference]
    content_by_unit = {item.presentation_unit_id: item for item in content.content_items}
    traced = {node.attrs.get("data-shadow-unit", ""): node for node in _nodes(dom, lambda node: bool(node.attrs.get("data-shadow-unit")))}
    report.learner_visible_modes = sorted({unit.presentation_mode for unit in learner_units})
    report.expected_interactions = [unit.presentation_unit_id for unit in learner_units]
    report.discovered_interactions = sorted(traced)
    covered = 0
    document_text = _text(dom)
    for unit in learner_units:
        item = content_by_unit.get(unit.presentation_unit_id)
        node = traced.get(unit.presentation_unit_id)
        expected_component = _MODE_COMPONENTS.get(unit.presentation_mode)
        if not item or not node or not expected_component:
            _block(report, f"Learner unit '{unit.presentation_unit_id}' has no rendered interaction.")
            continue
        if expected_component not in _classes(node):
            _block(report, f"Learner unit '{unit.presentation_unit_id}' rendered as the wrong component.")
            continue
        expected_trace = unit.trace
        if (
            node.attrs.get("data-shadow-binding") != expected_trace.binding_id
            or node.attrs.get("data-shadow-activity") != expected_trace.activity_id
            or node.attrs.get("data-shadow-content") != item.id
            or node.attrs.get("data-shadow-evidence", "").split(",") != expected_trace.evidence_ids
        ):
            _block(report, f"Learner unit '{unit.presentation_unit_id}' lost trace metadata in the DOM.")
            continue
        covered += 1
        _check_unit_payload(report, node, unit.presentation_mode, item, document_text)
    report.trace_dom_coverage = covered / len(learner_units) if learner_units else 0.0
    if report.trace_dom_coverage != 1.0:
        _block(report, "Rendered trace DOM coverage is incomplete.")
    expected_ids = {unit.presentation_unit_id for unit in learner_units}
    for unit_id, node in traced.items():
        if unit_id not in expected_ids or not (set(_classes(node)) & set(_MODE_COMPONENTS.values())):
            _block(report, f"Rendered learner interaction '{unit_id or 'unknown'}' is unexplained.")


def _check_unit_payload(report, node: _Node, mode: str, item, document_text: str) -> None:
    text = _text(node)
    if mode == "listening_choice":
        choices = [child for child in _nodes(node, lambda child: child.tag == "button" and "choice" in _classes(child))]
        if not item.prompt or item.prompt not in document_text or len(choices) < 2 or not item.accepted_responses:
            _block(report, f"Listening unit '{item.presentation_unit_id}' lost its prompt, choices, or accepted-response contract.")
        if not _find(node, lambda child: child.tag == "button" and "audio-button" in _classes(child) and bool(child.attrs.get("data-audio"))):
            _block(report, f"Listening unit '{item.presentation_unit_id}' has no loadable audio trigger.")
        if node.attrs.get("data-answer"):
            _warn(report, f"Listening unit '{item.presentation_unit_id}' keeps its answer contract in client-side interaction metadata.")
    if mode == "matching_response":
        buttons = _nodes(node, lambda child: child.tag == "button" and bool(child.attrs.get("data-value")))
        pair_values = [value for pair in item.matching_pairs for value in (pair.left, pair.right)]
        if len(item.matching_pairs) < 2 or len(buttons) != len(item.matching_pairs) * 2 or any(value not in text for value in pair_values):
            _block(report, f"Matching unit '{item.presentation_unit_id}' lost approved pairs in rendered HTML.")


def _check_teacher_safety(report, dom: _Node, raw_html: str, evidence, activities) -> None:
    learner_text = _text(dom)
    learner_payload = f"{learner_text}\n{raw_html}".lower()
    candidates = [spec.teacher_observation_notes for spec in evidence.evidence_specs]
    candidates.extend(activity.teacher_action for activity in activities.activities)
    candidates.extend(activity.classroom_notes for activity in activities.activities if not activity.learner_facing)
    for value in candidates:
        if value and len(value.strip()) > 3 and value.lower() in learner_payload:
            report.teacher_leakage_findings.append("Teacher-only source text appears in learner DOM.")
    markers = ("private rubric", "private teacher", "teacher observation", "teacher action", "教师观察", "老师观察")
    for marker in markers:
        if marker in learner_payload:
            report.teacher_leakage_findings.append(f"Learner DOM contains teacher-only marker '{marker}'.")
    for finding in report.teacher_leakage_findings:
        _block(report, finding)


def _check_accessibility(report, root: _Node) -> None:
    for button in _nodes(root, lambda node: node.tag == "button"):
        if not button.attrs.get("aria-label") and not _text(button).strip():
            report.accessibility_findings.append("Interactive button has no accessible name.")
    for node in _nodes(root, lambda node: bool(node.attrs.get("data-shadow-unit"))):
        if any(key.startswith("aria-") for key in node.attrs if key.startswith("aria-")):
            report.accessibility_findings.append("Hidden trace metadata must not be announced to learners.")
    if report.accessibility_findings:
        _warn(report, "Accessibility smoke findings require human review.")


def _compare_legacy(report, root: Path, internal: _Node, canonical, content) -> None:
    legacy_path = root / LEGACY_HTML_PATH
    comparison = {
        "legacy_available": legacy_path.exists(),
        "internal_slide_count": len(_nodes(internal, lambda node: node.tag == "article" and "slide" in _classes(node))),
        "internal_interaction_count": len(_nodes(internal, lambda node: bool(node.attrs.get("data-shadow-unit")))),
        "differences": [],
    }
    if not legacy_path.exists():
        comparison["differences"].append("Legacy HTML is unavailable for structural comparison.")
        _warn(report, "Legacy structural comparison is unavailable.")
        report.visual_comparison = comparison
        return
    legacy = _parse(legacy_path.read_text(encoding="utf-8"), report)
    if legacy is None:
        return
    comparison["legacy_slide_count"] = len(_nodes(legacy.root, lambda node: node.tag == "article" and "slide" in _classes(node)))
    comparison["legacy_interaction_count"] = len(_nodes(legacy.root, lambda node: "listen-choose" in _classes(node) or "match-game" in _classes(node)))
    if comparison["legacy_slide_count"] != comparison["internal_slide_count"]:
        comparison["differences"].append("Expected architectural difference: legacy and v2 slide counts differ.")
    expected_strings = _required_learner_strings(canonical, content)
    v2_text, legacy_text = _text(internal), _text(legacy.root)
    missing_v2 = sorted(value for value in expected_strings if value not in v2_text)
    if missing_v2:
        report.learner_content_findings.extend(f"V2 DOM loses required learner text: {value}" for value in missing_v2)
        for finding in report.learner_content_findings:
            _block(report, finding)
    comparison["missing_from_legacy"] = sorted(value for value in expected_strings if value not in legacy_text)
    comparison["additional_v2_text"] = sorted(set(_chinese_tokens(v2_text)) - set(_chinese_tokens(legacy_text)))
    comparison["visual_parity_verified"] = False
    comparison["human_review_required"] = True
    report.visual_comparison = comparison
    _warn(report, "Visual parity is unverified; structural comparison is not pedagogical equivalence.")


def _apply_browser_observation(report, observation: V2BrowserRuntimeObservation | None) -> None:
    if observation is None:
        _warn(report, "Browser runtime validation was not supplied; static DOM review only.")
        report.responsive_findings.append("Desktop, classroom, and narrow viewport checks require a real browser observation.")
        return
    report.browser_runtime_available = True
    report.page_load_success = observation.page_load_success
    report.console_errors = list(observation.console_errors)
    report.uncaught_exceptions = list(observation.uncaught_exceptions)
    report.interaction_results = list(observation.interaction_results)
    report.responsive_findings.extend(observation.responsive_findings)
    report.accessibility_findings.extend(observation.accessibility_findings)
    report.screenshot_artifacts = list(observation.screenshot_artifacts)
    report.notes.extend(observation.notes)
    if observation.source_input_fingerprint != report.source_input_fingerprint:
        _block(report, "Browser observation belongs to a different v2 input fingerprint.")
    if not observation.page_load_success:
        _block(report, "V2 internal HTML did not load in the browser.")
    for error in [*observation.console_errors, *observation.uncaught_exceptions]:
        _block(report, f"Browser runtime error: {error}")
    observed = {result.presentation_unit_id: result for result in observation.interaction_results}
    for unit_id in report.expected_interactions:
        result = observed.get(unit_id)
        if result is None or not result.passed:
            _block(report, f"Browser interaction did not complete for '{unit_id}'.")
    if observation.accessibility_findings:
        _warn(report, "Browser accessibility smoke findings require human review.")


def _required_learner_strings(canonical, content) -> set[str]:
    content_by_unit = {item.presentation_unit_id: item for item in content.content_items}
    values: set[str] = set()
    for unit in canonical.presentation_units:
        if not unit.learner_channel or unit.teacher_channel_reference:
            continue
        item = content_by_unit.get(unit.presentation_unit_id)
        if not item:
            continue
        values.update(value for value in [item.prompt, *item.learner_instructions, *item.display_items] if value)
        values.update(option.text for option in item.options if option.text)
        values.update(value for pair in item.matching_pairs for value in (pair.left, pair.right) if value)
    return values


def _nodes(root: _Node, predicate) -> list[_Node]:
    found: list[_Node] = []
    for node in _walk(root):
        if predicate(node):
            found.append(node)
    return found


def _find(root: _Node, predicate) -> _Node | None:
    return next(iter(_nodes(root, predicate)), None)


def _walk(root: _Node) -> Iterable[_Node]:
    yield root
    for child in root.children:
        yield from _walk(child)


def _classes(node: _Node) -> set[str]:
    return set(node.attrs.get("class", "").split())


def _text(root: _Node) -> str:
    values: list[str] = []
    for node in _walk(root):
        if node.tag not in {"script", "style"}:
            values.extend(node.text)
    return " ".join(" ".join(values).split())


def _normalize(root: _Node):
    return {
        "tag": root.tag,
        "attrs": dict(sorted(root.attrs.items())),
        "text": " ".join(root.text).split(),
        "children": [_normalize(child) for child in root.children if child.tag not in {"script", "style"}],
    }


def _chinese_tokens(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]+", text)


def _fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _block(report, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)


def _finish(report) -> None:
    if report.blocking:
        report.state = "blocked"
    elif report.browser_runtime_available:
        report.state = "pass"
    else:
        report.state = "warning"
    report.notes.append("Visual parity is not verified by this diagnostic; human visual review remains required.")


def _write(project_id: str, report: V2RenderedOutputReviewReport) -> V2RenderedOutputReviewReport:
    write_json(project_id, REVIEW_PATH, report.model_dump(mode="json", by_alias=True))
    return report
