
"""State-Evidence Kernel enforcement tests."""

from pathlib import Path

import json


def _binding_fixture():
    from hcs_api.models import LessonProfile, TeachingCandidates, LessonBlueprint, LessonSlide, SlideComponent
    from hcs_api.presentation_bindings import build_activity_bindings
    from hcs_api.state_evidence_kernel import build_activity_plan, build_evidence_plan, build_learning_state_plan

    profile = LessonProfile(lesson_title="第1课 您好", scaffolding_language="Arabic")
    candidates = TeachingCandidates(route_hint="greeting_lesson", core_vocabulary=[
        {"word": "你好", "pinyin": "nǐ hǎo"}, {"word": "您好", "pinyin": "nín hǎo"},
    ])
    sp = build_learning_state_plan(profile, candidates)
    ep = build_evidence_plan(sp, "zero_beginner", "Arabic")
    ap = build_activity_plan(ep, "zero_beginner", "Arabic")
    bp = LessonBlueprint(lesson_title="test", route_hint="greeting_lesson", slides=[
        LessonSlide(id=1, slide_type="CoverSlide", layout_variant="basic", title="第1课", components=[], content_blocks=[]),
        LessonSlide(id=3, slide_type="VocabularySlide", layout_variant="card_grid", title="你好", components=[
            SlideComponent(id="v1", component_type="VocabularyFlipCard", title="", data={"items": [{"word": "你好", "pinyin": "nǐ hǎo"}]}),
        ], content_blocks=[]),
        LessonSlide(id=5, slide_type="GrammarPatternSlide", layout_variant="basic", title="您好 / 你好", components=[], content_blocks=[]),
        LessonSlide(id=6, slide_type="PracticeSlide", layout_variant="basic", title="你好 您好", components=[], content_blocks=[]),
        LessonSlide(id=7, slide_type="PracticeSlide", layout_variant="basic", title="你好 您好", components=[], content_blocks=[]),
    ])
    bindings = build_activity_bindings(bp, ep, ap, sp, "zero_beginner")
    return profile, bp, sp, ep, ap, bindings


def test_transition_without_evidence_blocks() -> None:
    """Transition without required evidence should block unless exposure_only."""
    from hcs_api.models import LearningStatePlan, LearningState, LearningTransition, EvidencePlan, ActivityPlan
    from hcs_api.state_evidence_kernel import check_evidence_alignment
    sp = LearningStatePlan(lesson_title="test", states=[
        LearningState(state_id="s1"), LearningState(state_id="s2"),
    ], transitions=[
        LearningTransition(from_state="s1", to_state="s2", transition_intent="test_transition"),
    ])
    r = check_evidence_alignment(sp, EvidencePlan(), ActivityPlan())
    assert r.state == "blocked"
    assert any("lacks required evidence" in b for b in r.blocking)


def test_exposure_only_passes_without_evidence() -> None:
    from hcs_api.models import LearningStatePlan, LearningState, LearningTransition, EvidencePlan, ActivityPlan
    from hcs_api.state_evidence_kernel import check_evidence_alignment
    sp = LearningStatePlan(lesson_title="test", states=[
        LearningState(state_id="s1"), LearningState(state_id="s2"),
    ], transitions=[
        LearningTransition(from_state="s1", to_state="s2", transition_intent="first_exposure", transition_policy="exposure_only"),
    ])
    r = check_evidence_alignment(sp, EvidencePlan(), ActivityPlan())
    assert r.state != "blocked"


def test_production_goal_not_only_listen_choose() -> None:
    from hcs_api.models import (LearningStatePlan, LearningState, LearningGoal, LearningTransition,
                                 EvidencePlan, EvidenceSpec, ActivityPlan, LearningActivity)
    from hcs_api.state_evidence_kernel import check_evidence_alignment
    sp = LearningStatePlan(lesson_title="test", states=[
        LearningState(state_id="s1"), LearningState(state_id="s2", state_type="controlled_production"),
    ], goals=[
        LearningGoal(goal_id="g", goal_type="production", target_items=["test"], required_state_to_reach="s2"),
    ], transitions=[
        LearningTransition(from_state="s1", to_state="s2", transition_intent="prod", required_evidence_ids=["ev"]),
    ])
    ep = EvidencePlan(evidence_specs=[EvidenceSpec(evidence_id="ev", evidence_type="listen_choose", collector_refs=["act"])])
    ap = ActivityPlan(activities=[LearningActivity(activity_id="act", collects_evidence=["ev"])])
    r = check_evidence_alignment(sp, ep, ap, learner_level="beginner")
    assert any("production" in str(b) for b in r.blocking)


def test_collector_refs_missing_blocks() -> None:
    from hcs_api.models import (LearningStatePlan, LearningState, LearningTransition, EvidencePlan, EvidenceSpec, ActivityPlan)
    from hcs_api.state_evidence_kernel import check_evidence_alignment
    sp = LearningStatePlan(lesson_title="test", states=[LearningState(state_id="s1"), LearningState(state_id="s2")],
                           transitions=[LearningTransition(from_state="s1", to_state="s2", transition_intent="t", required_evidence_ids=["ev"])])
    ep = EvidencePlan(evidence_specs=[EvidenceSpec(evidence_id="ev", evidence_type="deterministic_choice", collector_refs=["act_missing"])])
    r = check_evidence_alignment(sp, ep, ActivityPlan())
    assert r.state == "blocked"
    assert any("no matching activity" in b for b in r.blocking)


def test_activity_collects_unknown_evidence_blocks() -> None:
    from hcs_api.models import (LearningStatePlan, LearningState, LearningTransition, EvidencePlan, ActivityPlan, LearningActivity)
    from hcs_api.state_evidence_kernel import check_evidence_alignment
    sp = LearningStatePlan(lesson_title="test", states=[LearningState(state_id="s1"), LearningState(state_id="s2")],
                           transitions=[LearningTransition(from_state="s1", to_state="s2", transition_intent="t")])
    ap = ActivityPlan(activities=[LearningActivity(activity_id="act", collects_evidence=["ev_ghost"])])
    r = check_evidence_alignment(sp, EvidencePlan(), ap)
    assert r.state == "blocked"
    assert any("does not exist" in b for b in r.blocking)


def test_golden_greeting_lesson_kernel() -> None:
    from hcs_api.models import LessonProfile, TeachingCandidates
    from hcs_api.state_evidence_kernel import build_learning_state_plan, build_evidence_plan, build_activity_plan, check_evidence_alignment
    profile = LessonProfile(lesson_title="第1课 您好", scaffolding_language="Arabic")
    candidates = TeachingCandidates(route_hint="greeting_lesson", core_vocabulary=[
        {"word": "你好", "pinyin": "nǐ hǎo"}, {"word": "您好", "pinyin": "nín hǎo"},
    ])
    sp = build_learning_state_plan(profile, candidates)
    assert len(sp.states) >= 4
    ep = build_evidence_plan(sp, "zero_beginner", "Arabic")
    assert len(ep.evidence_specs) >= 2
    ap = build_activity_plan(ep, "zero_beginner", "Arabic")
    assert len(ap.activities) >= 2
    al = check_evidence_alignment(sp, ep, ap, "zero_beginner")
    assert al.state in ("pass", "warning")


def test_pptx_deck_evidence_in_speaker_notes() -> None:
    from hcs_api.pptx_deck import build_pptx_deck_plan
    profile, bp, sp, ep, ap, bindings = _binding_fixture()
    deck = build_pptx_deck_plan(bp, "Chinese", profile.scaffolding_language, "zero_beginner", None, ep, ap, sp, bindings)
    ev_slides = [s for s in deck.slides if s.evidence_id]
    assert len(ev_slides) >= 1
    for s in ev_slides:
        assert s.binding_id
        assert s.activity_id
        assert s.evidence_claim
        notes = " ".join(s.speaker_notes)
        assert "Binding:" in notes
        assert "Activity:" in notes
        assert any("Evidence:" in n for n in s.speaker_notes)

def test_html_lesson_data_has_non_empty_evidence_ids(tmp_path: Path) -> None:
    import json
    from hcs_api.models import QualityReport, AssetManifest
    from hcs_api.renderer import render_lesson
    profile, bp, _sp, _ep, _ap, bindings = _binding_fixture()
    manifest = AssetManifest(images=[], audio=[])
    result_path = render_lesson(tmp_path, profile, bp, manifest, QualityReport(), render_mode="classroom", activity_bindings=bindings)
    html = result_path.read_text(encoding="utf-8")
    # Extract lesson-data JSON
    marker = 'id="lesson-data">'
    start = html.find(marker)
    end = html.find("</script>", start) if start >= 0 else -1
    if start >= 0 and end > start:
        data_json = html[start + len(marker):end].strip()
        data = json.loads(data_json)
        found = False
        for s in data.get("blueprint", {}).get("slides", []):
            for c in s.get("components", []):
                comp_data = c.get("data", {})
                if comp_data.get("evidence_id", "") and comp_data.get("binding_id", "") and comp_data.get("activity_id", ""):
                    found = True
        assert found, "No component has a non-empty evidence_id in lesson-data"
        assert "binding_id" not in html.replace(data_json, "")


def test_v0_2_1_smoke_learning_state_plan() -> None:
    """Smoke: learning_state_plan structural validity."""
    from hcs_api.models import LessonProfile, TeachingCandidates
    from hcs_api.state_evidence_kernel import build_learning_state_plan
    profile = LessonProfile(lesson_title="第1课 您好", scaffolding_language="Arabic")
    candidates = TeachingCandidates(route_hint="greeting_lesson", core_vocabulary=[
        {"word": "你好", "pinyin": "nǐ hǎo"}, {"word": "您好", "pinyin": "nín hǎo"},
        {"word": "你"}, {"word": "您"},
    ])
    sp = build_learning_state_plan(profile, candidates)
    assert len(sp.states) >= 4
    assert len(sp.goals) >= 3
    assert len(sp.transitions) >= 4
    assert any(t.transition_policy == "exposure_only" for t in sp.transitions), "Missing exposure_only"
    for t in sp.transitions:
        if t.transition_policy != "exposure_only" and not t.metadata.get("allow_without_evidence"):
            assert t.required_evidence_ids, f"{t.transition_intent} lacks evidence"


def test_v0_2_1_smoke_golden_kernel() -> None:
    """Smoke: golden greeting lesson produces valid evidence + activity plan with alignment pass."""
    from hcs_api.models import LessonProfile, TeachingCandidates
    from hcs_api.state_evidence_kernel import build_learning_state_plan, build_evidence_plan, build_activity_plan, check_evidence_alignment
    profile = LessonProfile(lesson_title="第1课 您好", scaffolding_language="Arabic")
    candidates = TeachingCandidates(route_hint="greeting_lesson", core_vocabulary=[
        {"word": "你好", "pinyin": "nǐ hǎo"}, {"word": "您好", "pinyin": "nín hǎo"},
    ])
    sp = build_learning_state_plan(profile, candidates)
    ep = build_evidence_plan(sp, "zero_beginner", "Arabic")
    ap = build_activity_plan(ep, "zero_beginner", "Arabic")
    assert len(ep.evidence_specs) >= 3
    assert len(ap.activities) >= 3
    # Bidirectional collector consistency
    ev_ids = {e.evidence_id for e in ep.evidence_specs}
    act_ids = {a.activity_id for a in ap.activities}
    for a in ap.activities:
        for ce in a.collects_evidence:
            assert ce in ev_ids, f"{ce} not in evidence"
    for e in ep.evidence_specs:
        for ref in e.collector_refs:
            assert ref in act_ids, f"{ref} not in activities"
    al = check_evidence_alignment(sp, ep, ap, "zero_beginner")
    assert al.state in ("pass", "warning"), f"Bad: {al.state}"


def test_v0_2_1_smoke_blocked_transition() -> None:
    """Smoke: transition without evidence blocks unless explicit exemption."""
    from hcs_api.models import LearningStatePlan, LearningState, LearningTransition, EvidencePlan, ActivityPlan
    from hcs_api.state_evidence_kernel import check_evidence_alignment
    sp = LearningStatePlan(lesson_title="bad", states=[
        LearningState(state_id="s1"), LearningState(state_id="s2"),
    ], transitions=[
        LearningTransition(from_state="s1", to_state="s2", transition_intent="bad"),
    ])
    r = check_evidence_alignment(sp, EvidencePlan(), ActivityPlan())
    assert r.state == "blocked"


def test_v0_2_1_smoke_pptx_evidence_mapping() -> None:
    """Smoke: PPTX deck plan consumes presentation bindings."""
    from hcs_api.pptx_deck import build_pptx_deck_plan
    profile, bp, sp, ep, ap, bindings = _binding_fixture()
    deck = build_pptx_deck_plan(bp, "Chinese", "Arabic", "zero_beginner", None, ep, ap, sp, bindings)
    # Cover should have NO evidence
    cover = [s for s in deck.slides if s.slide_id == 1][0]
    assert not cover.evidence_id, f"Cover should not have evidence: {cover.evidence_id}"
    # Non-cover should have evidence
    non_cover = [s for s in deck.slides if s.slide_id != 1]
    assert any(s.evidence_id for s in non_cover), "No non-cover slide has evidence"
    # Evidence slides have proper speaker notes
    for s in non_cover:
        if s.evidence_id:
            notes_text = " ".join(s.speaker_notes)
            assert "Evidence:" in notes_text
            assert "Claim:" in notes_text
            assert "Pass:" in notes_text


def test_golden_lesson_generates_activity_bindings() -> None:
    _profile, _bp, _sp, ep, _ap, bindings = _binding_fixture()
    assert bindings.state in ("pass", "warning")
    assert bindings.bindings
    assert {ev.evidence_id for ev in ep.evidence_specs} <= {b.evidence_id for b in bindings.bindings}


def test_binding_references_are_valid() -> None:
    _profile, bp, _sp, ep, ap, bindings = _binding_fixture()
    activity_ids = {a.activity_id for a in ap.activities}
    evidence_ids = {e.evidence_id for e in ep.evidence_specs}
    slide_ids = {s.id for s in bp.slides}
    components = {(s.id, c.id) for s in bp.slides for c in s.components}
    for binding in bindings.bindings:
        assert binding.activity_id in activity_ids
        assert binding.evidence_id in evidence_ids
        assert binding.slide_id in slide_ids
        if binding.component_id:
            assert (binding.slide_id, binding.component_id) in components


def test_duplicate_presentation_target_binding_blocks() -> None:
    from hcs_api.models import PresentationBinding, PresentationBindingPlan
    from hcs_api.presentation_bindings import check_activity_bindings
    _profile, bp, sp, ep, ap, bindings = _binding_fixture()
    duplicate = PresentationBinding(**bindings.bindings[1].model_dump(mode="json"))
    duplicate.slide_id = bindings.bindings[0].slide_id
    duplicate.component_id = bindings.bindings[0].component_id
    report = check_activity_bindings(bp, ep, ap, sp, PresentationBindingPlan(bindings=[bindings.bindings[0], duplicate, *bindings.bindings[2:]]), "zero_beginner")
    assert report.state == "blocked"
    assert any("Duplicate presentation target binding" in issue for issue in report.blocking)


def test_duplicate_html_target_binding_blocks() -> None:
    from hcs_api.models import PresentationBinding, PresentationBindingPlan
    from hcs_api.presentation_bindings import check_activity_bindings
    _profile, bp, sp, ep, ap, bindings = _binding_fixture()
    first = PresentationBinding(**bindings.bindings[0].model_dump(mode="json"))
    second = PresentationBinding(**bindings.bindings[1].model_dump(mode="json"))
    first.presentation_modes = ["html_classroom"]
    second.presentation_modes = ["html_interactive"]
    second.slide_id = first.slide_id
    second.component_id = first.component_id
    report = check_activity_bindings(bp, ep, ap, sp, PresentationBindingPlan(bindings=[first, second, *bindings.bindings[2:]]), "zero_beginner")
    assert report.state == "blocked"
    assert any("mode=html" in issue for issue in report.blocking)


def test_duplicate_pptx_target_binding_blocks() -> None:
    from hcs_api.models import PresentationBinding, PresentationBindingPlan
    from hcs_api.presentation_bindings import check_activity_bindings
    _profile, bp, sp, ep, ap, bindings = _binding_fixture()
    first = PresentationBinding(**bindings.bindings[0].model_dump(mode="json"))
    second = PresentationBinding(**bindings.bindings[1].model_dump(mode="json"))
    first.presentation_modes = ["pptx_classroom"]
    second.presentation_modes = ["speaker_notes"]
    second.slide_id = first.slide_id
    second.component_id = first.component_id
    report = check_activity_bindings(bp, ep, ap, sp, PresentationBindingPlan(bindings=[first, second, *bindings.bindings[2:]]), "zero_beginner")
    assert report.state == "blocked"
    assert any("mode=pptx" in issue for issue in report.blocking)


def test_golden_activity_bindings_have_no_duplicate_target_keys() -> None:
    _profile, _bp, _sp, _ep, _ap, bindings = _binding_fixture()
    seen = set()
    for binding in bindings.bindings:
        component_id = binding.component_id or "__slide__"
        modes = set(binding.presentation_modes)
        keys = []
        if {"html_classroom", "html_interactive"} & modes:
            keys.append((binding.slide_id, component_id, "html"))
        if {"pptx_classroom", "speaker_notes"} & modes:
            keys.append((binding.slide_id, component_id, "pptx"))
        if "teacher_observation" in modes:
            keys.append((binding.slide_id, component_id, "teacher"))
        for key in keys:
            assert key not in seen
            seen.add(key)


def test_fake_binding_unknown_evidence_blocks() -> None:
    from hcs_api.models import PresentationBinding, PresentationBindingPlan
    from hcs_api.presentation_bindings import check_activity_bindings
    _profile, bp, sp, ep, ap, bindings = _binding_fixture()
    bad = PresentationBinding(**bindings.bindings[0].model_dump(mode="json"))
    bad.evidence_id = "ev_missing"
    report = check_activity_bindings(bp, ep, ap, sp, PresentationBindingPlan(bindings=[bad]), "zero_beginner")
    assert report.state == "blocked"
    assert any("unknown evidence" in issue for issue in report.blocking)


def test_fake_binding_unknown_slide_blocks() -> None:
    from hcs_api.models import PresentationBinding, PresentationBindingPlan
    from hcs_api.presentation_bindings import check_activity_bindings
    _profile, bp, sp, ep, ap, bindings = _binding_fixture()
    bad = PresentationBinding(**bindings.bindings[0].model_dump(mode="json"))
    bad.slide_id = 999
    report = check_activity_bindings(bp, ep, ap, sp, PresentationBindingPlan(bindings=[bad]), "zero_beginner")
    assert report.state == "blocked"
    assert any("unknown slide" in issue for issue in report.blocking)


def test_zero_beginner_sentence_drag_binding_blocks() -> None:
    from hcs_api.models import LessonBlueprint, LessonSlide, PresentationBinding, PresentationBindingPlan, SlideComponent
    from hcs_api.presentation_bindings import check_activity_bindings
    _profile, _bp, sp, ep, ap, bindings = _binding_fixture()
    bp = LessonBlueprint(lesson_title="bad", slides=[
        LessonSlide(id=3, slide_type="PracticeSlide", layout_variant="basic", title="bad", components=[
            SlideComponent(id="drag", component_type="SentenceDragBuilder", data={}),
        ])
    ])
    bad = PresentationBinding(**bindings.bindings[0].model_dump(mode="json"))
    bad.slide_id = 3
    bad.component_id = "drag"
    report = check_activity_bindings(bp, ep, ap, sp, PresentationBindingPlan(bindings=[bad]), "zero_beginner")
    assert report.state == "blocked"
    assert any("unsuitable" in issue for issue in report.blocking)


def test_html_lesson_data_uses_binding_not_heuristic(tmp_path: Path) -> None:
    from hcs_api.models import AssetManifest, PresentationBinding, PresentationBindingPlan, QualityReport
    from hcs_api.renderer import render_lesson
    profile, bp, _sp, _ep, _ap, bindings = _binding_fixture()
    binding = PresentationBinding(**bindings.bindings[0].model_dump(mode="json"))
    binding.evidence_id = "ev_binding_only"
    plan = PresentationBindingPlan(bindings=[binding])
    html_path = render_lesson(tmp_path, profile, bp, AssetManifest(), QualityReport(), render_mode="classroom", activity_bindings=plan)
    html = html_path.read_text(encoding="utf-8")
    data_json = html.split('id="lesson-data">', 1)[1].split("</script>", 1)[0]
    data = json.loads(data_json)
    component_data = data["blueprint"]["slides"][1]["components"][0]["data"]
    assert component_data["evidence_id"] == "ev_binding_only"
    assert component_data["binding_id"] == binding.binding_id


def test_html_and_pptx_consume_same_binding_for_shared_target(tmp_path: Path) -> None:
    from hcs_api.models import AssetManifest, QualityReport
    from hcs_api.pptx_deck import build_pptx_deck_plan
    from hcs_api.renderer import render_lesson
    profile, bp, sp, ep, ap, bindings = _binding_fixture()
    binding = next(b for b in bindings.bindings if b.component_id)
    html_path = render_lesson(tmp_path, profile, bp, AssetManifest(), QualityReport(), render_mode="classroom", activity_bindings=bindings)
    html = html_path.read_text(encoding="utf-8")
    data_json = html.split('id="lesson-data">', 1)[1].split("</script>", 1)[0]
    data = json.loads(data_json)
    html_binding = None
    for slide in data["blueprint"]["slides"]:
        if slide["id"] == binding.slide_id:
            for component in slide["components"]:
                if component["data"].get("binding_id") == binding.binding_id:
                    html_binding = component["data"]
    deck = build_pptx_deck_plan(bp, "Chinese", profile.scaffolding_language, "zero_beginner", None, ep, ap, sp, bindings)
    deck_slide = next(slide for slide in deck.slides if slide.slide_id == binding.slide_id)
    assert html_binding is not None
    assert html_binding["binding_id"] == deck_slide.binding_id
    assert html_binding["evidence_id"] == deck_slide.evidence_id


def test_cover_slide_has_no_binding_by_default() -> None:
    _profile, _bp, _sp, _ep, _ap, bindings = _binding_fixture()
    assert all(binding.slide_id != 1 for binding in bindings.bindings)
