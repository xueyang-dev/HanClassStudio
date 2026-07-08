
"""State-Evidence Kernel enforcement tests."""

from pathlib import Path

import json


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
    from hcs_api.models import (LessonProfile, TeachingCandidates, LessonBlueprint, LessonSlide, SlideComponent)
    from hcs_api.state_evidence_kernel import build_learning_state_plan, build_evidence_plan, build_activity_plan
    from hcs_api.pptx_deck import build_pptx_deck_plan
    profile = LessonProfile(lesson_title="第1课 您好", scaffolding_language="Arabic")
    candidates = TeachingCandidates(route_hint="greeting_lesson", core_vocabulary=[
        {"word": "你好", "pinyin": "nǐ hǎo"}, {"word": "您好", "pinyin": "nín hǎo"},
    ])
    sp = build_learning_state_plan(profile, candidates)
    ep = build_evidence_plan(sp, "zero_beginner", "Arabic")
    ap = build_activity_plan(ep, "zero_beginner", "Arabic")
    bp = LessonBlueprint(lesson_title="第1课 您好", route_hint="greeting_lesson", slides=[
        LessonSlide(id=1, slide_type="CoverSlide", layout_variant="basic", title="第1课 您好", components=[], content_blocks=[]),
        LessonSlide(id=3, slide_type="VocabularySlide", layout_variant="card_grid", title="", components=[
            SlideComponent(id="v1", component_type="VocabularyFlipCard", title="", data={"items": [{"word": "你好", "pinyin": "nǐ hǎo"}]}),
        ], content_blocks=[]),
    ])
    deck = build_pptx_deck_plan(bp, "Chinese", "Arabic", "zero_beginner", None, ep, ap, sp)
    ev_slides = [s for s in deck.slides if s.evidence_id]
    assert len(ev_slides) >= 1
    for s in ev_slides:
        assert s.evidence_claim
        assert any("Evidence:" in n for n in s.speaker_notes)

def test_html_lesson_data_has_non_empty_evidence_ids(tmp_path: Path) -> None:
    import json
    from hcs_api.models import LessonProfile, TeachingCandidates, LessonBlueprint, LessonSlide, SlideComponent, QualityReport, AssetManifest
    from hcs_api.state_evidence_kernel import build_learning_state_plan, build_evidence_plan, build_activity_plan
    from hcs_api.renderer import render_lesson
    profile = LessonProfile(lesson_title="第1课 您好", scaffolding_language="Arabic")
    candidates = TeachingCandidates(route_hint="greeting_lesson", core_vocabulary=[
        {"word": "你好", "pinyin": "nǐ hǎo"}, {"word": "您好", "pinyin": "nín hǎo"},
    ])
    sp = build_learning_state_plan(profile, candidates)
    ep = build_evidence_plan(sp, "zero_beginner", "Arabic")
    ap = build_activity_plan(ep, "zero_beginner", "Arabic")
    # Build evidence map
    ev_map: dict[int, str] = {}
    bp = LessonBlueprint(lesson_title="test", route_hint="greeting_lesson", slides=[
        LessonSlide(id=3, slide_type="VocabularySlide", layout_variant="card_grid", title="", components=[
            SlideComponent(id="v1", component_type="VocabularyFlipCard", title="", data={"items": [{"word": "你好", "pinyin": "nǐ hǎo"}]}),
        ], content_blocks=[]),
    ])
    for slide in bp.slides:
        for c in slide.components:
            for item in c.data.get("items", []):
                w = item.get("word", "")
                for ev in ep.evidence_specs:
                    if w in ev.target_items:
                        ev_map[slide.id] = ev.evidence_id
    manifest = AssetManifest(images=[], audio=[])
    result_path = render_lesson(tmp_path, profile, bp, manifest, QualityReport(), render_mode="classroom", evidence_map=ev_map)
    html = result_path.read_text(encoding="utf-8")
    # Extract lesson-data JSON
    start = html.find("<script id=\"lesson-data\">")
    end = html.find("</script>", start) if start >= 0 else -1
    if start >= 0 and end > start:
        data_json = html[start + len("<script id=\"lesson-data\">"):end].strip()
        data = json.loads(data_json)
        found = False
        for s in data.get("blueprint", {}).get("slides", []):
            for c in s.get("components", []):
                if c.get("data", {}).get("evidence_id", ""):
                    found = True
        assert found, "No component has a non-empty evidence_id in lesson-data"


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
    """Smoke: PPTX deck plan evidence mapping accuracy."""
    from hcs_api.models import LessonProfile, TeachingCandidates, LessonBlueprint, LessonSlide, SlideComponent
    from hcs_api.state_evidence_kernel import build_learning_state_plan, build_evidence_plan, build_activity_plan
    from hcs_api.pptx_deck import build_pptx_deck_plan
    profile = LessonProfile(lesson_title="第1课 您好", scaffolding_language="Arabic")
    candidates = TeachingCandidates(route_hint="greeting_lesson", core_vocabulary=[
        {"word": "你好", "pinyin": "nǐ hǎo"}, {"word": "您好", "pinyin": "nín hǎo"},
    ])
    sp = build_learning_state_plan(profile, candidates)
    ep = build_evidence_plan(sp, "zero_beginner", "Arabic")
    ap = build_activity_plan(ep, "zero_beginner", "Arabic")
    bp = LessonBlueprint(lesson_title="test", route_hint="greeting_lesson", slides=[
        LessonSlide(id=1, slide_type="CoverSlide", layout_variant="basic", title="第1课", components=[], content_blocks=[]),
        LessonSlide(id=3, slide_type="VocabularySlide", layout_variant="card_grid", title="", components=[
            SlideComponent(id="v1", component_type="VocabularyFlipCard", title="", data={"items": [{"word": "你好", "pinyin": "nǐ hǎo"}]}),
        ], content_blocks=[]),
        LessonSlide(id=5, slide_type="GrammarPatternSlide", layout_variant="basic", title="", components=[], content_blocks=[]),
        LessonSlide(id=7, slide_type="PracticeSlide", layout_variant="basic", title="", components=[], content_blocks=[]),
    ])
    deck = build_pptx_deck_plan(bp, "Chinese", "Arabic", "zero_beginner", None, ep, ap, sp)
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
