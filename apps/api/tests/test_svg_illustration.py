from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from hcs_api.media import generate_placeholder_media
from hcs_api.models import (
    AssetManifest,
    ContentBlock,
    LessonBlueprint,
    LessonSlide,
    LLMProviderSettings,
    MediaRequirements,
)
from hcs_api.svg_components import COMPONENTS, known_component
from hcs_api.svg_illustration import (
    CONCEPT_RECIPES,
    IllustrationSceneSpec,
    SvgContract,
    build_scene_spec_for_concept,
    check_illustration_quality,
    check_svg_offline_safe,
    generate_svg_illustration,
    placeholder_svg,
    render_scene_spec,
    validate_scene_spec,
)

VALID = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" '
    'role="img" aria-label="x"><rect width="10" height="10" fill="#fff"/>'
    '<text font-family="sans-serif">hi</text></svg>'
)


def test_valid_svg_passes():
    rep = check_svg_offline_safe(VALID, "a")
    assert rep.passed
    assert rep.state == "pass"


def test_foreignobject_blocked():
    svg = VALID.replace(
        '<rect width="10" height="10" fill="#fff"/>',
        "<foreignObject><rect width=\"10\" height=\"10\" fill=\"#fff\"/></foreignObject>",
    )
    rep = check_svg_offline_safe(svg, "a")
    assert not rep.passed
    assert any("foreignObject" in b for b in rep.blocking)


def test_script_blocked():
    svg = VALID.replace("</svg>", "<script>alert(1)</script></svg>")
    rep = check_svg_offline_safe(svg, "a")
    assert not rep.passed


def test_external_href_blocked():
    svg = VALID.replace("<rect", '<a href="https://example.com"><rect')
    rep = check_svg_offline_safe(svg, "a")
    assert not rep.passed


def test_event_handler_blocked():
    svg = VALID.replace("<rect", '<rect onload="x()">')
    rep = check_svg_offline_safe(svg, "a")
    assert not rep.passed


def test_missing_viewbox_blocked():
    svg = VALID.replace(' viewBox="0 0 1200 675"', "")
    rep = check_svg_offline_safe(svg, "a")
    assert not rep.passed


def test_missing_xmlns_blocked():
    svg = VALID.replace('xmlns="http://www.w3.org/2000/svg" ', "")
    rep = check_svg_offline_safe(svg, "a")
    assert not rep.passed


def test_duplicate_ids_blocked():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
        '<rect id="x"/><circle id="x"/></svg>'
    )
    rep = check_svg_offline_safe(svg, "a")
    assert not rep.passed


def test_malformed_xml_blocked():
    rep = check_svg_offline_safe("<svg><unclosed>", "a")
    assert not rep.passed


def test_placeholder_passes_gate():
    rep = check_svg_offline_safe(placeholder_svg("lesson scene", 1), "a")
    assert rep.passed


def test_data_uri_allowed():
    svg = VALID.replace(
        'fill="#fff"', 'fill="url(#g)"'
    ).replace(
        "<rect width", '<defs><linearGradient id="g"></linearGradient></defs><rect width'
    )
    rep = check_svg_offline_safe(svg, "a")
    assert rep.passed


def test_generate_falls_back_without_llm():
    contract = SvgContract(asset_id="s1", brief="a classroom scene", slide_id=1)
    # Default LLMProviderSettings has no key -> provider disabled -> deterministic recipe.
    svg, report, spec = generate_svg_illustration(contract, LLMProviderSettings())
    assert svg.startswith("<svg")
    assert report.passed
    assert isinstance(spec, dict) and spec.get("subjects")


def test_placeholder_media_writes_svg_for_illustration(tmp_path: Path):
    bp = LessonBlueprint(
        lesson_title="Test",
        slides=[
            LessonSlide(
                id=1,
                slide_type="CoverSlide",
                layout_variant="centered_title",
                title="t",
                content_blocks=[ContentBlock(id="c1", block_type="subtitle", text="x")],
                media_requirements=MediaRequirements(
                    image_prompt="a scene",
                    image_key="slide_1_scene",
                    media_kind="svg_illustration",
                ),
            )
        ],
    )
    manifest = generate_placeholder_media(tmp_path, bp)
    assert isinstance(manifest, AssetManifest)
    svg_path = tmp_path / "assets" / "images" / "slide_1_scene.svg"
    scene_path = tmp_path / "assets" / "images" / "slide_1_scene.scene.json"
    assert svg_path.exists()
    assert scene_path.exists()
    rep = check_svg_offline_safe(svg_path.read_text(encoding="utf-8"), "slide_1_scene")
    assert rep.passed


# ==========================================================================
# SceneSpec schema + banned-content tests
# ==========================================================================

def test_scene_spec_serializes():
    spec = validate_scene_spec({"concept": "x", "subjects": [{"id": "p", "object_type": "PersonStanding"}]})
    assert isinstance(spec, IllustrationSceneSpec)
    assert spec.model_dump()["concept"] == "x"


def test_scene_spec_rejects_svg_coordinates():
    with __import__("pytest").raises(Exception):
        validate_scene_spec({"concept": "x", "subjects": [{"id": "p", "object_type": "PersonStanding", "x": 123}]})


def test_scene_spec_rejects_slide_and_component_ids():
    with __import__("pytest").raises(Exception):
        validate_scene_spec({"concept": "x", "slide_id": 3})
    with __import__("pytest").raises(Exception):
        validate_scene_spec({"concept": "x", "subjects": [{"id": "p", "object_type": "PersonStanding", "component_id": "z"}]})


def test_scene_spec_rejects_large_text_content():
    # no_text must reject any symbol text
    with __import__("pytest").raises(Exception):
        validate_scene_spec({"concept": "x", "text_policy": "no_text",
                             "objects": [{"id": "b", "object_type": "SpeechBubble", "symbol_text": "hi"}]})
    # semantic_symbols_only rejects > 8 chars
    with __import__("pytest").raises(Exception):
        validate_scene_spec({"concept": "x", "text_policy": "semantic_symbols_only",
                             "objects": [{"id": "b", "object_type": "SpeechBubble", "symbol_text": "longgreeting"}]})


def test_vocab_illustration_defaults_to_no_text():
    assert IllustrationSceneSpec().text_policy == "no_text"


# ==========================================================================
# Component system + renderer
# ==========================================================================

def test_svg_renderer_uses_registered_components():
    spec = {"concept": "x", "subjects": [{"id": "p", "object_type": "PersonStanding",
            "position_zone": "center", "relative_scale": 0.5}], "objects": []}
    svg = render_scene_spec(spec)
    assert "<circle" in svg  # head drawn by the registered component
    assert svg.startswith("<svg")


def test_unknown_component_is_rejected():
    import copy
    bad = copy.deepcopy(CONCEPT_RECIPES["睡觉"])
    # 睡觉 has no objects, so inject a non-existent component to exercise the
    # unknown-component guard.
    bad["objects"] = [{"id": "x", "object_type": "NotAComponent",
                      "position_zone": "center", "relative_scale": 0.5}]
    spec = validate_scene_spec(bad)
    svg = render_scene_spec(spec.model_dump())
    iq = check_illustration_quality(spec.model_dump(), svg)
    assert iq["state"] == "blocked"
    assert any("unknown component" in b for b in iq["blocking"])


# ==========================================================================
# Per-concept required-object rules
# ==========================================================================

import json as _json

def _copy(spec):
    return _json.loads(_json.dumps(spec))

def test_sleep_scene_requires_composite():
    base = _copy(CONCEPT_RECIPES["睡觉"])
    # valid recipe (SleepingInBed composite) passes — render per aspect, because
    # the gate enforces genuinely different per-aspect recipes (window in 16:9,
    # absent in thumb), so the same SVG cannot be reused across aspects.
    for aspect in ("16:9", "1:1", "thumb"):
        svg = render_scene_spec(base, aspect=aspect)
        assert check_illustration_quality(base, svg, aspect=aspect)["state"] == "pass"
    # removing the composite subject -> blocking (no subject / not composite)
    no_subj = _copy(base); no_subj["subjects"] = []
    assert check_illustration_quality(no_subj, svg)["state"] == "blocked"
    # the OLD floating pattern (Bed+Pillow+Blanket+PersonLying) is now blocked
    old = _copy(base)
    old["subjects"] = [{"id": "s", "object_type": "PersonLying", "position_zone": "center",
                        "relative_scale": 0.42, "action": "sleep"}]
    old["objects"] = [{"id": "b", "object_type": "Bed", "position_zone": "center", "relative_scale": 0.62},
                      {"id": "p", "object_type": "Pillow", "position_zone": "left", "relative_scale": 0.26},
                      {"id": "bl", "object_type": "Blanket", "position_zone": "center", "relative_scale": 0.5}]
    old_svg = render_scene_spec(old)
    res = check_illustration_quality(old, old_svg)
    assert res["state"] == "blocked"
    assert any("SleepingInBed" in b for b in res["blocking"])


def test_eating_scene_requires_food_and_eating_action():
    base = _copy(CONCEPT_RECIPES["吃饭"])
    svg = render_scene_spec(base)
    assert check_illustration_quality(base, svg)["state"] == "pass"
    no_food = _copy(base); no_food["objects"] = [o for o in base["objects"] if o["object_type"] != "Bowl"]
    assert any("Bowl" in w for w in check_illustration_quality(no_food, svg)["warnings"])
    no_action = _copy(base); no_action["subjects"][0]["action"] = "stand"
    assert any("eat" in b for b in check_illustration_quality(no_action, svg)["blocking"])


def test_drinking_scene_requires_drink_container():
    base = _copy(CONCEPT_RECIPES["喝水"])
    svg = render_scene_spec(base)
    assert check_illustration_quality(base, svg)["state"] == "pass"
    no_cup = _copy(base); no_cup["objects"] = [o for o in base["objects"] if o["object_type"] != "Cup"]
    assert any("Cup" in w for w in check_illustration_quality(no_cup, svg)["warnings"])
    no_action = _copy(base); no_action["subjects"][0]["action"] = "stand"
    assert any("drink" in b for b in check_illustration_quality(no_action, svg)["blocking"])


def test_study_scene_requires_learning_object():
    base = _copy(CONCEPT_RECIPES["学习"])
    svg = render_scene_spec(base)
    assert check_illustration_quality(base, svg)["state"] == "pass"
    no_book = _copy(base); no_book["objects"] = [o for o in base["objects"] if o["object_type"] != "Book"]
    assert any("Book" in w for w in check_illustration_quality(no_book, svg)["warnings"])


# ==========================================================================
# Composition / scale / visual-centre rules
# ==========================================================================

def test_subject_scale_within_allowed_range():
    spec = {"concept": "x", "illustration_level": "scene",
            "subjects": [{"id": "p", "object_type": "PersonStanding", "relative_scale": 0.95,
                          "position_zone": "center"}], "objects": []}
    svg = render_scene_spec(spec)
    iq = check_illustration_quality(spec, svg)
    assert any("scale" in w for w in iq["warnings"])


def test_single_visual_center_rule():
    spec = {"concept": "x", "composition": {"visual_center_count": 2},
            "subjects": [{"id": "p", "object_type": "PersonStanding", "position_zone": "center"}],
            "objects": []}
    svg = render_scene_spec(spec)
    iq = check_illustration_quality(spec, svg)
    assert any("visual centre" in w for w in iq["warnings"])


# ==========================================================================
# Deterministic semantic fallback (not a geometric placeholder)
# ==========================================================================

def test_fallback_is_semantically_specific():
    spec = build_scene_spec_for_concept("睡觉", "")
    subj_types = [s["object_type"] for s in spec["subjects"]]
    # sleep is now one cohesive composite (bed+pillow+person+blanket), not
    # separate floating Bed/Pillow/Blanket/PersonLying objects.
    assert any(st == "SleepingInBed" for st in subj_types)
    svg = render_scene_spec(spec)
    assert placeholder_svg("睡觉", 1) != svg  # not the old geometric placeholder
    # and it actually assembles a real bed scene (head/pillow/blanket contact)
    assert "睡觉" in svg or "sleep" in svg.lower() or "Bed" in svg or "bed" in svg.lower()


def test_fallback_contains_no_debug_text():
    spec = build_scene_spec_for_concept("睡觉", "")
    svg = render_scene_spec(spec).lower()
    for token in ("placeholder", "llm", "error", "todo", "debug", "fallback"):
        assert token not in svg


# ==========================================================================
# Offline safety + geometry of rendered output
# ==========================================================================

def test_svg_is_offline_safe():
    for concept in CONCEPT_RECIPES:
        svg = render_scene_spec(CONCEPT_RECIPES[concept])
        assert check_svg_offline_safe(svg, concept).passed


def test_svg_has_valid_viewbox():
    for concept in CONCEPT_RECIPES:
        svg = render_scene_spec(CONCEPT_RECIPES[concept])
        assert 'viewBox="0 0 1200 675"' in svg


def test_svg_does_not_overflow_viewbox():
    from hcs_api.svg_illustration import _check_overflow
    for concept in CONCEPT_RECIPES:
        svg = render_scene_spec(CONCEPT_RECIPES[concept])
        assert _check_overflow(svg) is None


def test_key_subject_is_visible():
    try:
        import cairosvg  # noqa: F401
    except Exception:
        __import__("pytest").skip("cairosvg not installed; visual raster check skipped")
    from hcs_api.svg_illustration import _check_not_blank
    for concept in CONCEPT_RECIPES:
        svg = render_scene_spec(CONCEPT_RECIPES[concept])
        assert _check_not_blank(svg) is None


def test_text_policy_is_enforced():
    spec = {"concept": "x", "text_policy": "no_text",
            "objects": [{"id": "b", "object_type": "SpeechBubble", "symbol_text": "hi"}]}
    svg = render_scene_spec(spec)
    iq = check_illustration_quality(spec, svg)
    assert any("text_policy" in b for b in iq["blocking"])


# ==========================================================================
# Gallery + determinism + compatibility
# ==========================================================================

def test_gallery_contains_all_benchmarks():
    benchmarks = ["睡觉", "吃饭", "喝水", "学习", "学生向老师问好", "看书", "写字", "餐厅点餐"]
    for c in benchmarks:
        spec = build_scene_spec_for_concept(c, "")
        assert spec["subjects"], f"benchmark {c} has no subject"
        svg = render_scene_spec(spec)
        assert check_svg_offline_safe(svg, c).passed


def test_generation_is_deterministic_when_using_fallback():
    a = build_scene_spec_for_concept("睡觉", "")
    b = build_scene_spec_for_concept("睡觉", "")
    assert a == b
    assert render_scene_spec(a) == render_scene_spec(b)


def test_existing_courseware_generation_remains_compatible():
    import tempfile
    from pathlib import Path
    bp = LessonBlueprint(
        lesson_title="Test",
        slides=[
            LessonSlide(id=1, slide_type="CoverSlide", layout_variant="x", title="t",
                content_blocks=[ContentBlock(id="c1", block_type="subtitle", text="x")],
                media_requirements=MediaRequirements(image_prompt="raster pic", image_key="slide_1_photo", media_kind="raster")),
            LessonSlide(id=2, slide_type="VocabSlide", layout_variant="x", title="v",
                content_blocks=[ContentBlock(id="c2", block_type="subtitle", text="x")],
                media_requirements=MediaRequirements(image_prompt="睡觉 scene", image_key="slide_2_sleep", media_kind="svg_illustration")),
        ],
    )
    manifest = generate_placeholder_media(Path(tempfile.mkdtemp()), bp)
    ids = {a.id for a in manifest.images}
    assert "slide_1_photo" in ids and "slide_2_sleep" in ids


# ==========================================================================
# SleepingInBed composite — geometric contact relationships (regression guard)
# These prove the "structurally correct but visually poor" failure is gone:
# head must rest ON the pillow, blanket must cover the body, and the subject
# must dominate the frame (clear visual centre, controlled blank space).
# ==========================================================================

SVG_NS = "http://www.w3.org/2000/svg"


def _bbox_by_id(svg: str, elem_id: str):
    root = ET.fromstring(svg)
    for el in root.iter():
        if el.get("id") == elem_id:
            tag = el.tag.split("}")[-1]
            if tag == "rect":
                x, y, w, h = (float(el.get(k)) for k in ("x", "y", "width", "height"))
                return (x, y, x + w, y + h)
            if tag == "circle":
                cx, cy, r = (float(el.get(k)) for k in ("cx", "cy", "r"))
                return (cx - r, cy - r, cx + r, cy + r)
            if tag == "path":
                nums = [float(n) for n in __import__("re").findall(r"-?\d+\.?\d*", el.get("d", ""))]
                pts = list(zip(nums[0::2], nums[1::2]))
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                return (min(xs), min(ys), max(xs), max(ys))
            if tag == "polyline":
                import re as _re
                nums = [float(n) for n in _re.findall(r"-?\d+\.?\d*", el.get("points", ""))]
                pts = list(zip(nums[0::2], nums[1::2]))
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                return (min(xs), min(ys), max(xs), max(ys))
    return None


def _composite_union_bbox(svg: str, ids=("sib-bed", "sib-pillow", "sib-head", "sib-body", "sib-blanket")):
    boxes = [_bbox_by_id(svg, i) for i in ids]
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def test_sleeping_in_bed_head_rests_on_pillow():
    spec = build_scene_spec_for_concept("睡觉", "")
    svg = render_scene_spec(spec, aspect="16:9")
    pillow = _bbox_by_id(svg, "sib-pillow")
    head = _bbox_by_id(svg, "sib-head")
    assert pillow and head, "pillow/head must be tagged in composite"
    # head horizontally within the pillow's x-span (resting on it, not floating beside)
    assert pillow[0] - 1 <= head[0] <= pillow[2] + 1, f"head x {head[0]:.1f} outside pillow x [{pillow[0]:.1f},{pillow[2]:.1f}]"
    # head bottom must overlap / sit on the pillow top (contact, not gap)
    assert head[3] >= pillow[1] - 1, f"head bottom {head[3]:.1f} floats above pillow top {pillow[1]:.1f}"


def test_sleeping_in_bed_blanket_covers_body():
    spec = build_scene_spec_for_concept("睡觉", "")
    svg = render_scene_spec(spec, aspect="16:9")
    body = _bbox_by_id(svg, "sib-body")
    blanket = _bbox_by_id(svg, "sib-blanket")
    assert body and blanket, "body/blanket must be tagged in composite"
    # blanket must horizontally cover the bulk of the body (not just a corner)
    body_cx = (body[0] + body[2]) / 2
    assert blanket[0] <= body_cx <= blanket[2], "blanket does not span the body"
    # blanket must overlap the body vertically (draped over, head uncovered allowed)
    assert blanket[3] >= body[1], "blanket does not reach the body top"


def test_sleeping_in_bed_subject_dominates_frame():
    spec = build_scene_spec_for_concept("睡觉", "")
    for aspect in ("16:9", "1:1", "thumb"):
        svg = render_scene_spec(spec, aspect=aspect)
        union = _composite_union_bbox(svg)
        assert union, "composite must render tagged parts"
        w = union[2] - union[0]
        h = union[3] - union[1]
        cx = (union[0] + union[2]) / 2
        # subject must occupy a substantial, centred share of the canvas
        assert w >= 1200 * 0.30, f"{aspect}: subject width {w:.0f} too small (clear visual centre fails)"
        assert h >= 675 * 0.22, f"{aspect}: subject height {h:.0f} too small"
        assert abs(cx - 600) <= 220, f"{aspect}: subject not centred (cx={cx:.0f})"


def test_sleeping_in_bed_thumb_recognisable_scale():
    # The thumbnail gate requires the subject to occupy >= 55% of the canvas
    # width (the recipe uses scale 0.68, so it passes). A too-small subject is
    # now blocked with a clear message (not the old "thumbnail" wording).
    spec = build_scene_spec_for_concept("睡觉", "")
    svg = render_scene_spec(spec, aspect="thumb")
    iq = check_illustration_quality(spec, svg, aspect="thumb")
    assert iq["state"] == "pass"
    assert not any("subject occupies only" in b for b in iq["blocking"])


def test_sleeping_in_bed_z_above_head_anchor():
    spec = build_scene_spec_for_concept("睡觉", "")
    for aspect in ("16:9", "1:1", "thumb"):
        svg = render_scene_spec(spec, aspect=aspect)
        head = _bbox_by_id(svg, "sib-head")
        z = _bbox_by_id(svg, "sib-z")
        assert head and z, f"{aspect}: head/Z must be tagged"
        # Z must sit ABOVE the head (its lowest point above the head's top)
        assert z[3] <= head[1] + 2, f"{aspect}: Z bottom {z[3]:.0f} not above head top {head[1]:.0f}"
        # Z horizontally near the head anchor (drifting to the foot is wrong)
        z_cx = (z[0] + z[2]) / 2
        head_cx = (head[0] + head[2]) / 2
        assert abs(z_cx - head_cx) <= 90, f"{aspect}: Z drifts from head anchor"


def test_sleeping_in_bed_moon_in_window():
    spec = build_scene_spec_for_concept("睡觉", "")
    # 16:9 and 1:1 show the bedroom environment: a window with the moon inside.
    for aspect in ("16:9", "1:1"):
        svg = render_scene_spec(spec, aspect=aspect)
        win = _bbox_by_id(svg, "sib-window")
        moon = _bbox_by_id(svg, "sib-moon")
        assert win and moon, f"{aspect}: window + moon must be present"
        inside = (win[0] <= moon[0] and win[1] <= moon[1]
                  and moon[2] <= win[2] and moon[3] <= win[3])
        assert inside, f"{aspect}: moon must sit inside the window"
    # thumbnail drops the window entirely (a genuinely different recipe).
    svg_t = render_scene_spec(spec, aspect="thumb")
    assert _bbox_by_id(svg_t, "sib-window") is None, "thumb must drop the window"
    assert _bbox_by_id(svg_t, "sib-moon") is None, "thumb must drop the moon"


def test_sleep_quality_gate_blocks_aspect_recipe_mismatch():
    # The gate must distinguish real per-aspect recipes from one crop passed
    # under a different aspect label.
    spec = build_scene_spec_for_concept("睡觉", "")
    svg16 = render_scene_spec(spec, aspect="16:9")
    svg_t = render_scene_spec(spec, aspect="thumb")
    # A 16:9 render (window present) checked as thumb must be blocked.
    assert check_illustration_quality(spec, svg16, aspect="thumb")["state"] == "blocked"
    # A thumb render (no window) checked as 16:9 must be blocked.
    assert check_illustration_quality(spec, svg_t, aspect="16:9")["state"] == "blocked"
