"""Static and observation-contract coverage for the internal v2 rendered review."""

from __future__ import annotations

import os
from pathlib import Path

import hcs_api.storage as storage
from hcs_api.models import LessonBlueprint, LessonProfile, QualityReport, V2BrowserRuntimeObservation, V2RenderedInteractionResult
from hcs_api.renderer import render_lesson
from hcs_api.v2_cutover_readiness import INTERNAL_HTML_PATH, evaluate_v2_cutover_readiness, run_v2_internal_html_cutover
from hcs_api.v2_rendered_output_review import DIAGNOSTICS_DIR, REVIEW_PATH, run_v2_rendered_output_review
from test_v2_cutover import _multi_unit_fixture


def _rendered_multi(tmp_path: Path, monkeypatch):
    run = _multi_unit_fixture(tmp_path, monkeypatch)
    legacy = LessonBlueprint(lesson_title="Legacy comparison", slides=[run.adapted.slides[0]])
    render_lesson(run.root, LessonProfile(), legacy, run.manifest, QualityReport())
    result = run_v2_internal_html_cutover(run.project_id, run.root, LessonProfile(), run.manifest, QualityReport(), enabled=True)
    assert result.selected_route == "v2_internal_html"
    return run, result


def _review(run):
    return run_v2_rendered_output_review(run.project_id, source_input_fingerprint="fixture")


def test_v2_rendered_review_serializes_to_quality_path(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)

    report = _review(run)

    assert (run.root / REVIEW_PATH).exists()
    assert report.state == "warning"  # No repository browser runner is installed.
    assert report.human_review_required is True


def test_v2_internal_html_has_complete_static_dom_contract(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)

    report = _review(run)

    assert report.blocking == []
    assert report.trace_dom_coverage == 1.0
    assert report.expected_interactions == report.discovered_interactions
    assert report.learner_visible_modes == ["listening_choice", "matching_response"]


def test_v2_responsive_fix_is_scoped_to_internal_html(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    legacy_html = (run.root / "courseware/lesson.html").read_text(encoding="utf-8")
    internal_html = (run.root / INTERNAL_HTML_PATH).read_text(encoding="utf-8")

    assert '<body class="v2-internal">' not in legacy_html
    assert '<body class="v2-internal">' in internal_html
    assert ".v2-internal .slide-frame { min-width: 0; }" in internal_html


def test_v2_listening_prompt_options_and_audio_are_rendered(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    report = _review(run)
    html = (run.root / INTERNAL_HTML_PATH).read_text(encoding="utf-8")

    assert report.missing_assets == []
    assert run.content.content_items[0].prompt in html
    assert "你好" in html and "再见" in html
    assert 'class="audio-button"' in html


def test_v2_matching_all_pairs_are_rendered_and_deterministic(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    first = _review(run)
    second = _review(run)
    pairs = run.content.content_items[1].matching_pairs

    assert len(pairs) == 2
    assert len({pair.id for pair in pairs}) == 2
    assert first.normalized_dom_fingerprint == second.normalized_dom_fingerprint
    assert first.blocking == []


def test_v2_rendered_review_blocks_missing_audio(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    html_path = run.root / INTERNAL_HTML_PATH
    html_path.write_text(html_path.read_text(encoding="utf-8").replace("../assets/audio/lang_nihao.wav", "../assets/audio/missing.wav"), encoding="utf-8")

    report = _review(run)

    assert report.state == "blocked"
    assert report.missing_assets


def test_v2_rendered_review_blocks_teacher_content(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    html_path = run.root / INTERNAL_HTML_PATH
    html_path.write_text(html_path.read_text(encoding="utf-8").replace("</body>", "<p>private teacher observation</p></body>"), encoding="utf-8")

    report = _review(run)

    assert report.state == "blocked"
    assert report.teacher_leakage_findings


def test_v2_structural_comparison_allows_different_slide_counts(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)

    report = _review(run)

    assert report.visual_comparison["legacy_slide_count"] == 1
    assert report.visual_comparison["internal_slide_count"] == 2
    assert report.blocking == []
    assert report.visual_parity_verified is False


def test_v2_browser_observation_requires_all_successful_interactions(tmp_path: Path, monkeypatch) -> None:
    run, cutover = _rendered_multi(tmp_path, monkeypatch)
    observation = V2BrowserRuntimeObservation(
        source_input_fingerprint=cutover.input_fingerprint,
        page_load_success=True,
        interaction_results=[
            V2RenderedInteractionResult(presentation_unit_id="unit_activity_listen", presentation_mode="listening_choice", passed=True),
            V2RenderedInteractionResult(presentation_unit_id="unit_activity_match", presentation_mode="matching_response", passed=False),
        ],
    )

    report = run_v2_rendered_output_review(run.project_id, source_input_fingerprint=cutover.input_fingerprint, browser_observation=observation)

    assert report.state == "blocked"
    assert any("interaction did not complete" in issue for issue in report.blocking)


def test_v2_browser_observation_can_record_runtime_success(tmp_path: Path, monkeypatch) -> None:
    run, cutover = _rendered_multi(tmp_path, monkeypatch)
    observation = V2BrowserRuntimeObservation(
        source_input_fingerprint=cutover.input_fingerprint,
        page_load_success=True,
        interaction_results=[
            V2RenderedInteractionResult(presentation_unit_id="unit_activity_listen", presentation_mode="listening_choice", passed=True),
            V2RenderedInteractionResult(presentation_unit_id="unit_activity_match", presentation_mode="matching_response", passed=True),
        ],
    )

    report = run_v2_rendered_output_review(run.project_id, source_input_fingerprint=cutover.input_fingerprint, browser_observation=observation)

    assert report.state == "pass"
    assert report.browser_runtime_available is True
    assert report.page_load_success is True


def test_v2_browser_observation_blocks_serious_console_errors(tmp_path: Path, monkeypatch) -> None:
    run, cutover = _rendered_multi(tmp_path, monkeypatch)
    observation = V2BrowserRuntimeObservation(
        source_input_fingerprint=cutover.input_fingerprint,
        page_load_success=True,
        console_errors=["Uncaught runtime error"],
        interaction_results=[
            V2RenderedInteractionResult(presentation_unit_id="unit_activity_listen", presentation_mode="listening_choice", passed=True),
            V2RenderedInteractionResult(presentation_unit_id="unit_activity_match", presentation_mode="matching_response", passed=True),
        ],
    )

    report = run_v2_rendered_output_review(run.project_id, source_input_fingerprint=cutover.input_fingerprint, browser_observation=observation)

    assert report.state == "blocked"
    assert report.console_errors == ["Uncaught runtime error"]


def test_v2_stale_rendered_review_is_rejected_by_cutover_gate(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    review = storage.read_json(run.project_id, REVIEW_PATH)
    review["source_input_fingerprint"] = "stale"
    storage.write_json(run.project_id, REVIEW_PATH, review)

    report, _ = evaluate_v2_cutover_readiness(run.project_id, enabled=True, require_courseware_review=True)

    assert report.selected_route == "legacy"
    assert report.stale_artifacts


def test_v2_rendered_review_predating_internal_html_is_rejected(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    review_path = run.root / REVIEW_PATH
    html_path = run.root / INTERNAL_HTML_PATH
    os.utime(review_path, ns=(html_path.stat().st_atime_ns, html_path.stat().st_mtime_ns - 1))

    report, _ = evaluate_v2_cutover_readiness(run.project_id, enabled=True, require_courseware_review=True)

    assert report.selected_route == "legacy"
    assert any("predates its internal HTML" in finding for finding in report.stale_artifacts)


def test_v2_blocked_rendered_review_removes_internal_html_on_next_cutover(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    review = storage.read_json(run.project_id, REVIEW_PATH)
    review["state"] = "blocked"
    review["blocking"] = ["fixture rendered failure"]
    storage.write_json(run.project_id, REVIEW_PATH, review)

    report = run_v2_internal_html_cutover(run.project_id, run.root, LessonProfile(), run.manifest, QualityReport(), enabled=True)

    assert report.selected_route == "legacy"
    assert not (run.root / INTERNAL_HTML_PATH).exists()


def test_v2_failed_gate_removes_stale_visual_diagnostics(tmp_path: Path, monkeypatch) -> None:
    run, _ = _rendered_multi(tmp_path, monkeypatch)
    diagnostic = run.root / DIAGNOSTICS_DIR / "desktop.png"
    diagnostic.parent.mkdir(parents=True)
    diagnostic.write_bytes(b"stale")
    (run.root / "presentation/presentation_content_plan.reconciled.json").unlink()

    report = run_v2_internal_html_cutover(run.project_id, run.root, LessonProfile(), run.manifest, QualityReport(), enabled=True)

    assert report.selected_route == "legacy"
    assert not diagnostic.exists()
    assert not (run.root / INTERNAL_HTML_PATH).exists()
