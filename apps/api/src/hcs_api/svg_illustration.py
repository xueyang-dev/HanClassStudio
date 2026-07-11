"""Teaching-illustration generation — creation-phase, locked-contract-driven.

Architecture (this phase):
  concept / brief
    -> LLM emits IllustrationSceneSpec (JSON)  [providers.generate_scene_spec]
       OR a deterministic recipe (CONCEPT_RECIPES) when no LLM is available
    -> render_scene_spec() assembles SVG from a REGISTERED component library
    -> check_svg_offline_safe()  (can it load offline / is it safe?)
    -> check_illustration_quality() (is it a good teaching picture?)
    -> SVG asset

Key principle: the LLM (or recipe) plans the SCENE; a deterministic renderer
composes it from reusable, style-consistent components. No free-hand arbitrary
SVG paths, no teaching text baked into the illustration (text lives in the
courseware text layer; only short semantic symbols like a "Z" are allowed).
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator, ValidationError

from .models import LLMProviderSettings
from .providers import ProviderError, generate_scene_spec as _llm_generate_spec
from .svg_components import render_scene_spec

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
VIEWBOX = "0 0 1200 675"
BRAND_ACCENT = "#2E8B78"

# Fields the SceneSpec must NEVER carry (it describes WHAT to draw + HOW to
# compose, never the low-level SVG implementation).
BANNED_KEYS = {
    "coordinates", "x", "y", "cx", "cy", "path", "d", "points",
    "font_size", "font-size", "color", "fill", "stroke", "transform",
    "slide_id", "component_id", "text_content", "translation", "pinyin",
    "evidence", "objective", "teaching_goal", "learning_objective",
}


# ==========================================================================
# SceneSpec models
# ==========================================================================

class CompositionSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    focal_zone: str = "center"
    subject_scale_ratio: float = 0.5
    visual_center_count: int = 1
    foreground: str = ""
    middle_ground: str = ""
    background: str = ""
    whitespace_policy: str = "balanced"
    decoration_density: str = "low"


class SubjectSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    role: str = ""
    pose: str = ""
    action: str = ""
    emotion: str = ""
    relative_scale: float = 0.5
    facing: str = "front"
    position_zone: str = "center"
    object_type: str = ""   # resolved component type, e.g. "PersonStanding"
    symbol_text: str = ""


class ObjectSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    object_type: str = ""
    role: str = ""
    relative_scale: float = 0.5
    position_zone: str = "center"
    symbol_text: str = ""


class IllustrationSceneSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    concept: str = ""
    illustration_level: str = "scene"          # "icon" | "scene"
    scene_type: str = ""
    setting: str = ""
    focal_subject: str = ""
    subjects: list[SubjectSpec] = field(default_factory=list)
    objects: list[ObjectSpec] = field(default_factory=list)
    action: str = ""
    mood: str = ""
    time_of_day: str = ""
    composition: CompositionSpec = field(default_factory=CompositionSpec)
    text_policy: str = "no_text"               # no_text | semantic_symbols_only | short_environment_label
    style_token: str = "soft_flat_educational_v1"
    aspect_ratio: str = "16:9"
    accessibility_label: str = ""
    fallback_strategy: str = "recipe"
    warnings: list[str] = field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_text_policy(self) -> "IllustrationSceneSpec":
        sym = [s.symbol_text for s in self.subjects + self.objects if s.symbol_text]
        if self.text_policy == "no_text" and sym:
            raise ValueError("text_policy=no_text but symbol text is present")
        if self.text_policy == "semantic_symbols_only" and any(len(s) > 8 for s in sym):
            raise ValueError("semantic_symbols_only: symbol text exceeds 8 chars")
        if self.text_policy == "short_environment_label" and any(len(s) > 16 for s in sym):
            raise ValueError("short_environment_label: text exceeds 16 chars")
        return self


def _scan_banned(data: Any, path: str = "") -> None:
    if isinstance(data, dict):
        for k, v in data.items():
            if k in BANNED_KEYS:
                raise ValueError(f"banned field in scene spec: {path}{k}")
            _scan_banned(v, path + str(k) + ".")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _scan_banned(v, path + f"[{i}].")


def validate_scene_spec(data: dict) -> IllustrationSceneSpec:
    """Validate raw dict: reject banned low-level keys, then model-validate."""
    _scan_banned(data)
    return IllustrationSceneSpec.model_validate(data)


# ==========================================================================
# Concept recipe table (deterministic fallback — real teaching pictures)
# ==========================================================================

def _sub(id, object_type, zone, rs, **kw):
    d = {"id": id, "object_type": object_type, "position_zone": zone, "relative_scale": rs}
    d.update(kw)
    return d


CONCEPT_RECIPES: dict[str, dict] = {
    "睡觉": {
        "concept": "睡觉", "illustration_level": "scene", "scene_type": "sleep",
        "setting": "bedroom", "focal_subject": "sleeper", "action": "sleep", "mood": "calm",
        "time_of_day": "night", "text_policy": "semantic_symbols_only",
        "accessibility_label": "一个人躺在床上睡觉",
        "subjects": [_sub("sleeper", "SleepingInBed", "center", 0.68, action="sleep")],
        "objects": [],
        "composition": {"subject_scale_ratio": 0.68, "visual_center_count": 1,
                        "whitespace_policy": "tight", "decoration_density": "low"},
    },
    "吃饭": {
        "concept": "吃饭", "illustration_level": "scene", "scene_type": "eat",
        "setting": "restaurant", "focal_subject": "eater", "action": "eat", "mood": "neutral",
        "text_policy": "no_text", "accessibility_label": "一个人坐在桌前吃饭",
        "subjects": [_sub("eater", "PersonSitting", "center", 0.50, action="eat")],
        "objects": [
            _sub("table", "Table", "center", 0.55),
            _sub("bowl", "Bowl", "center", 0.24),
            _sub("chopsticks", "Chopsticks", "center", 0.20),
        ],
    },
    "喝水": {
        "concept": "喝水", "illustration_level": "scene", "scene_type": "drink",
        "setting": "neutral", "focal_subject": "drinker", "action": "drink", "mood": "neutral",
        "text_policy": "no_text", "accessibility_label": "一个人拿着杯子喝水",
        "subjects": [_sub("drinker", "PersonStanding", "center", 0.50, action="drink")],
        "objects": [
            _sub("cup", "Cup", "right", 0.22),
            _sub("sip", "MotionLines", "right", 0.16),
        ],
    },
    "学习": {
        "concept": "学习", "illustration_level": "scene", "scene_type": "study",
        "setting": "classroom", "focal_subject": "student", "action": "study", "mood": "focused",
        "text_policy": "no_text", "accessibility_label": "学生坐在课桌前学习",
        "subjects": [_sub("student", "StudentSitting", "center", 0.50, action="study")],
        "objects": [
            _sub("desk", "SchoolDesk", "center", 0.58),
            _sub("book", "Book", "center", 0.26, open=True),
            _sub("notebook", "Notebook", "center", 0.22),
            _sub("attention", "AttentionMark", "top_right", 0.15),
        ],
    },
    "看书": {
        "concept": "看书", "illustration_level": "scene", "scene_type": "read",
        "setting": "classroom", "focal_subject": "reader", "action": "read", "mood": "focused",
        "text_policy": "no_text", "accessibility_label": "学生坐着看书",
        "subjects": [_sub("reader", "PersonReading", "center", 0.50, action="read")],
        "objects": [
            _sub("desk", "SchoolDesk", "center", 0.55),
            _sub("book", "Book", "center", 0.26, open=True),
        ],
    },
    "写字": {
        "concept": "写字", "illustration_level": "scene", "scene_type": "write",
        "setting": "classroom", "focal_subject": "writer", "action": "write", "mood": "focused",
        "text_policy": "no_text", "accessibility_label": "学生坐着写字",
        "subjects": [_sub("writer", "PersonWriting", "center", 0.50, action="write")],
        "objects": [
            _sub("desk", "SchoolDesk", "center", 0.55),
            _sub("notebook", "Notebook", "center", 0.24),
        ],
    },
    "餐厅点餐": {
        "concept": "餐厅点餐", "illustration_level": "scene", "scene_type": "order",
        "setting": "restaurant", "focal_subject": "customer", "action": "order", "mood": "polite",
        "text_policy": "semantic_symbols_only", "accessibility_label": "顾客在餐厅点餐",
        "subjects": [
            _sub("customer", "PersonSitting", "left", 0.48, action="order"),
            _sub("waiter", "PersonStanding", "right", 0.50),
        ],
        "objects": [
            _sub("table", "Table", "center", 0.50),
            _sub("bubble", "SpeechBubble", "center", 0.28, symbol_text="点"),
        ],
    },
    "学生向老师问好": {
        "concept": "学生向老师问好", "illustration_level": "scene", "scene_type": "greet",
        "setting": "classroom", "focal_subject": "student", "action": "greet", "mood": "friendly",
        "text_policy": "semantic_symbols_only", "accessibility_label": "学生向老师问好",
        "subjects": [
            _sub("teacher", "TeacherStanding", "right", 0.50),
            _sub("student", "StudentSitting", "left", 0.45, action="greet"),
        ],
        "objects": [
            _sub("bubble", "SpeechBubble", "center", 0.30, symbol_text="你好"),
            _sub("wave", "MotionLines", "right", 0.16),
        ],
    },
}

_CONCEPT_KEYWORDS = {
    "睡觉": ["睡觉", "睡眠", "睡"],
    "吃饭": ["吃饭", "用餐", "吃"],
    "喝水": ["喝水", "喝"],
    "学习": ["学习", "上课"],
    "看书": ["看书", "读书", "阅读"],
    "写字": ["写字", "写", "抄写"],
    "餐厅点餐": ["点餐", "点菜", "餐厅", "饭店"],
    "学生向老师问好": ["问好", "打招呼", "问候", "你好"],
}


def build_scene_spec_for_concept(brief: str, lesson_title: str = "") -> dict:
    """Match a concept from free text and return its deterministic recipe spec."""
    text = f"{brief} {lesson_title}".lower()
    for concept, keys in _CONCEPT_KEYWORDS.items():
        if any(k.lower() in text for k in keys):
            return CONCEPT_RECIPES[concept]
    # Generic semantic fallback (still a real picture, not a placeholder).
    return {
        "concept": (brief or "动作")[:12], "illustration_level": "scene",
        "scene_type": "generic", "setting": "neutral", "focal_subject": "person",
        "text_policy": "no_text", "accessibility_label": (brief or "教学插图")[:40],
        "subjects": [_sub("person", "PersonStanding", "center", 0.50)],
        "objects": [_sub("mark", "AttentionMark", "top_right", 0.15)],
    }


# ==========================================================================
# Legacy contract (kept for media.py call compatibility) + offline-safe gate
# ==========================================================================

@dataclass
class SvgContract:
    asset_id: str = ""
    lesson_title: str = ""
    target_language: str = "Chinese"
    scaffold_language: str = "English"
    learner_level: str = "zero_beginner"
    slide_id: int = 0
    brief: str = ""
    style: str = "flat"
    viewbox: str = VIEWBOX
    offline_safe: bool = True
    max_retries: int = 3
    accent: str = BRAND_ACCENT

    def to_brief(self) -> dict[str, Any]:
        return {
            "lesson_title": self.lesson_title, "target_language": self.target_language,
            "scaffold_language": self.scaffold_language, "learner_level": self.learner_level,
            "slide_id": self.slide_id, "brief": self.brief, "style": self.style,
            "accent": self.accent,
        }


@dataclass
class SvgQualityReport:
    asset_id: str
    passed: bool = False
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def state(self) -> str:
        return "blocked" if self.blocking else ("warning" if self.warnings else "pass")

    def to_dict(self) -> dict[str, Any]:
        return {"asset_id": self.asset_id, "state": self.state, "passed": self.passed,
                "blocking": self.blocking, "warnings": self.warnings}


_BANNED_TAGS = {"foreignObject", "script", "iframe", "object", "embed"}
_EXTERNAL_SCHEME_RE = re.compile(r"^(https?:|//|javascript:)", re.IGNORECASE)
_DATA_URI_RE = re.compile(r"^data:", re.IGNORECASE)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)
_ENTITY_RE = re.compile(r"<!ENTITY", re.IGNORECASE)
_HREF_ATTR_RE = re.compile(r'(?:href|xlink:href|src)\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_VIEWBOX_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s*$")
_URL_RE = re.compile(r"url\(\s*([^)]*)\)", re.IGNORECASE)
_IMPORT_RE = re.compile(r"@import\s+url\(([^)]+)\)", re.IGNORECASE)


def check_svg_offline_safe(svg: str, asset_id: str) -> SvgQualityReport:
    """Validate a single SVG string against the offline-safe contract."""
    report = SvgQualityReport(asset_id=asset_id)
    if not svg or not svg.strip():
        report.blocking.append("SVG is empty")
        return report
    if _DOCTYPE_RE.search(svg) or _ENTITY_RE.search(svg):
        report.blocking.append("SVG must not declare a DOCTYPE or ENTITY (XXE risk)")
    if re.search(r"<script", svg, re.IGNORECASE):
        report.blocking.append("SVG must not contain <script> (offline safety)")
    for ev in re.findall(r"\son\w+\s*=", svg, re.IGNORECASE):
        report.blocking.append(f"SVG must not use event-handler attribute '{ev.strip()}'")
    for m in _HREF_ATTR_RE.finditer(svg):
        if _EXTERNAL_SCHEME_RE.match(m.group(1).strip()):
            report.blocking.append(f"SVG references external resource '{m.group(1)}' (offline safety)")
    for m in _IMPORT_RE.finditer(svg):
        if _EXTERNAL_SCHEME_RE.match(m.group(1).strip()):
            report.blocking.append("SVG <style> imports an external resource")
    for m in _URL_RE.finditer(svg):
        u = m.group(1).strip().strip("'\"")
        if _EXTERNAL_SCHEME_RE.match(u) and not _DATA_URI_RE.match(u):
            report.blocking.append(f"SVG url() references external resource '{u}'")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        report.blocking.append(f"SVG is not well-formed XML: {exc}")
        return report
    if root.tag != f"{{{SVG_NS}}}svg":
        report.blocking.append("Root element must be <svg> in the SVG namespace")
    vb = root.get("viewBox")
    if not vb:
        report.blocking.append("SVG must declare a viewBox")
    elif not _VIEWBOX_RE.match(vb):
        report.blocking.append(f"Invalid viewBox '{vb}'")
    ids: list[str] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.split("}")[-1]
        if tag in _BANNED_TAGS:
            report.blocking.append(f"SVG uses banned element <{tag}>")
        for attr in el.attrib:
            if attr.lower().startswith("on"):
                report.blocking.append(f"SVG uses event-handler attribute '{attr}'")
            if attr.lower() in ("href", f"{{{XLINK_NS}}}href"):
                val = el.get(attr, "").strip()
                if val and not val.startswith("#") and not _DATA_URI_RE.match(val):
                    report.blocking.append(f"SVG references external '{val}'")
        eid = el.get("id")
        if eid:
            ids.append(eid)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        report.blocking.append(f"Duplicate SVG ids: {dup}")
    if len(svg) > 200_000:
        report.warnings.append("SVG is very large (>200KB); may slow offline render")
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.split("}")[-1] == "text" and not el.get("font-family"):
            report.warnings.append("SVG <text> lacks a font-family fallback")
            break
    report.passed = not report.blocking
    return report


def placeholder_svg(brief: str, slide_id: int, accent: str = BRAND_ACCENT) -> str:
    """Deprecated geometric placeholder. Kept only as a last-resort fallback."""
    safe = html.escape((brief or "illustration")[:120])
    hue = (slide_id * 41) % 360
    secondary = f"hsl({(hue + 120) % 360}, 62%, 60%)"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" '
        f'role="img" aria-label="{safe}">\n'
        f'  <rect width="1200" height="675" fill="#F8FAF7"/>\n'
        f'  <circle cx="220" cy="180" r="120" fill="{accent}" opacity="0.16"/>\n'
        f'  <circle cx="980" cy="500" r="160" fill="{secondary}" opacity="0.18"/>\n'
        f'  <rect x="340" y="170" width="520" height="335" rx="14" fill="#FFFFFF" stroke="#DCE8E2" stroke-width="4"/>\n'
        f'  <circle cx="470" cy="300" r="46" fill="{accent}" opacity="0.85"/>\n'
        f'  <path d="M560 360 C640 250 720 300 800 230 C860 180 920 240 960 210" fill="none" '
        f'stroke="{accent}" stroke-width="18" stroke-linecap="round" opacity="0.7"/>\n'
        f'  <rect x="400" y="410" width="300" height="20" rx="8" fill="{accent}" opacity="0.30"/>\n'
        f'  <rect x="400" y="448" width="220" height="16" rx="8" fill="#6F8D88" opacity="0.26"/>\n'
        f'  <text x="600" y="525" text-anchor="middle" font-family="sans-serif" font-size="24" '
        f'fill="#6F8D88" opacity="0.75">{safe}</text>\n'
        f"</svg>"
    )


# ==========================================================================
# Generator orchestration
# ==========================================================================

def generate_svg_illustration(contract: SvgContract, llm_settings: LLMProviderSettings) -> tuple[str, SvgQualityReport]:
    """Return (svg_text, offline_report).

    Tries the LLM scene-spec path, falls back to the deterministic recipe, then
    to the deprecated geometric placeholder only if even that is unsafe.
    """
    asset_id = contract.asset_id or f"slide_{contract.slide_id}_scene"
    spec = None
    prior_errors: list[str] | None = None

    for _ in range(max(1, contract.max_retries)):
        try:
            raw = _llm_generate_spec(llm_settings, contract.to_brief() | ({"prior_errors": prior_errors} if prior_errors else {}))
        except (ProviderError, Exception):
            raw = None
        if raw:
            try:
                spec = validate_scene_spec(raw)
                break
            except (ValidationError, ValueError):
                spec = None
        prior_errors = ["LLM scene spec invalid or unavailable"]

    if spec is None:
        spec = validate_scene_spec(build_scene_spec_for_concept(contract.brief, contract.lesson_title))

    svg = render_scene_spec(spec.model_dump())
    report = check_svg_offline_safe(svg, asset_id)
    if not report.passed:
        svg = placeholder_svg(contract.brief, contract.slide_id, contract.accent)
        report = check_svg_offline_safe(svg, asset_id)
    return svg, report, spec.model_dump()


# ==========================================================================
# Illustration-quality gate (separate from offline-safety)
# ==========================================================================

def check_illustration_quality(spec: dict | IllustrationSceneSpec, svg: str,
                                aspect: str = "16:9") -> dict:
    """Evaluate teaching-suitability of a rendered illustration.

    This is NOT an aesthetic judgement — it checks hard, teachable rules:
    scene-spec validity, single visual centre, subject scale, required action
    props, registered components, text-policy enforcement, and (when cairosvg
    is available) blank / overflow checks. Aesthetic / pedagogical approval
    still requires human visual review.
    """
    if isinstance(spec, dict):
        try:
            spec = validate_scene_spec(spec)
        except (ValidationError, ValueError) as exc:
            return {
                "schema": "hanclassstudio.illustration_quality.v1",
                "state": "blocked", "scene_spec_valid": False,
                "blocking": [f"SceneSpec invalid: {exc}"], "warnings": [],
                "human_visual_review_required": True,
                "notes": ["Fix the scene spec before rendering."],
            }
    s = spec
    blocking: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    # Required action props per scene type
    obj_types = {o.object_type for o in s.objects}
    subj_types = {sub.object_type for sub in s.subjects}
    actions = { (sub.action or "").lower() for sub in s.subjects }
    st = s.scene_type
    required: list[str] = []
    if st == "sleep":
        # Sleep MUST be assembled as ONE cohesive composite (bed+pillow+person
        # +blanket with guaranteed contact). The old pattern of separate floating
        # Bed/Pillow/Blanket/PersonLying components structurally cannot keep the
        # head on the pillow or the blanket over the body, so it is blocked even
        # though it "passes" the pure component-presence check.
        sleep_composite = "SleepingInBed" in subj_types or "SleepingInBed" in obj_types
        old_pattern = ("Bed" in obj_types and "Pillow" in obj_types
                       and "Blanket" in obj_types and "PersonLying" in subj_types)
        if not sleep_composite:
            blocking.append("sleep scene must use the 'SleepingInBed' composite "
                            "(bed+pillow+person+blanket as one cohesive unit)")
        if old_pattern:
            blocking.append("sleep scene must not assemble Bed+Pillow+Blanket+PersonLying "
                            "as separate floating components (head/pillow contact is not guaranteed)")
        # The subject must dominate the frame.
        if not any(sub.relative_scale >= 0.50 for sub in s.subjects if sub.object_type == "SleepingInBed"):
            blocking.append("sleep composite subject scale too small (<0.50): subject must be the clear visual centre")
    elif st == "eat":
        required = ["Bowl"]
        if not any(a for a in actions if "eat" in a):
            blocking.append("eat scene requires a subject with action 'eat'")
    elif st == "drink":
        required = ["Cup"]
        if not any(a for a in actions if "drink" in a):
            blocking.append("drink scene requires a subject with action 'drink'")
    elif st == "study":
        required = ["Book", "Notebook", "SchoolDesk"]
    elif st == "read":
        required = ["Book"]
    elif st == "write":
        required = ["Notebook"]
    elif st == "greet":
        if len(s.subjects) < 2:
            blocking.append("greet scene requires at least two subjects")
    for r in required:
        if r not in obj_types and r not in subj_types:
            warnings.append(f"scene type '{st}' conventionally includes '{r}'")

    # Unknown components
    from .svg_components import known_component
    for o in s.objects:
        if not known_component(o.object_type):
            blocking.append(f"unknown component '{o.object_type}'")
    for sub in s.subjects:
        if sub.object_type and not known_component(sub.object_type):
            blocking.append(f"unknown component '{sub.object_type}'")

    # Single visual centre
    if s.composition.visual_center_count != 1:
        warnings.append("illustration should have exactly one visual centre")
    if len(s.subjects) == 0:
        blocking.append("illustration has no subject")

    # Subject scale ratio
    for sub in s.subjects:
        if not (s.composition.subject_scale_ratio * 0.6 <= sub.relative_scale <= s.composition.subject_scale_ratio * 1.4):
            warnings.append(f"subject '{sub.id}' scale {sub.relative_scale} outside expected band")

    # Text policy
    sym = [x.symbol_text for x in s.subjects + s.objects if x.symbol_text]
    if s.text_policy == "no_text" and sym:
        blocking.append("text_policy=no_text but symbol text present in illustration")
    if s.text_policy == "semantic_symbols_only" and any(len(x) > 8 for x in sym):
        warnings.append("semantic_symbols_only symbol text exceeds 8 chars")

    # Overflow / blank checks (geometry is deterministic; raster is optional)
    overflow = _check_overflow(svg)
    if overflow:
        warnings.append(overflow)
    blank = _check_not_blank(svg)
    if blank:
        warnings.append(blank)

    # Thumbnail composition: the focal subject MUST stay large enough to be
    # recognisable when shrunk. This is the auto-guard against "passes the
    # gate but unreadable at small size".
    if aspect == "thumb":
        if not any(sub.relative_scale >= 0.55 for sub in s.subjects):
            blocking.append("thumbnail composition: focal subject scale < 0.55, "
                            "will be unrecognisable when shrunk")

    # Style consistency (colours must come from the palette / neutrals)
    style_note = _check_style_consistency(svg, s.style_token)
    if style_note:
        warnings.append(style_note)

    # Sleep-specific composition checks (head/pillow/blanket/Z/moon/scale/aspect).
    if st == "sleep":
        s_block, s_warn = _check_sleep_composition(svg, aspect)
        blocking.extend(s_block)
        warnings.extend(s_warn)

    state = "blocked" if blocking else ("warning" if warnings else "pass")
    return {
        "schema": "hanclassstudio.illustration_quality.v1",
        "state": state,
        "scene_spec_valid": True,
        "blocking": blocking,
        "warnings": warnings,
        "concept": s.concept,
        "illustration_level": s.illustration_level,
        "text_policy": s.text_policy,
        "small_size_readability": "unchecked (human review recommended)",
        "style_consistency": "ok" if not style_note else "review",
        "human_visual_review_required": True,
        "notes": notes or ["Auto-checks pass; aesthetic/pedagogical approval needs human review."],
    }


def _check_overflow(svg: str) -> str | None:
    """Deterministic bounds check: nothing should spill outside the viewBox."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return None
    tol = 2.0
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.split("}")[-1]
        try:
            if tag == "rect":
                x = float(el.get("x", 0)); y = float(el.get("y", 0))
                w = float(el.get("width", 0)); h = float(el.get("height", 0))
                if x < -tol or y < -tol or x + w > 1200 + tol or y + h > 675 + tol:
                    return "an element overflows the viewBox"
            elif tag == "circle":
                cx = float(el.get("cx", 0)); cy = float(el.get("cy", 0)); r = float(el.get("r", 0))
                if cx - r < -tol or cy - r < -tol or cx + r > 1200 + tol or cy + r > 675 + tol:
                    return "a circle overflows the viewBox"
        except (TypeError, ValueError):
            continue
    return None


def _check_not_blank(svg: str) -> str | None:
    """If cairosvg is available, rasterize and ensure the picture is not empty."""
    try:
        import cairosvg  # type: ignore
    except Exception:
        return None  # cannot verify; leave for human review
    try:
        import io
        from PIL import Image  # type: ignore
        png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=240, output_height=135)
        img = Image.open(io.BytesIO(png)).convert("L")
        non_bg = sum(1 for p in img.getdata() if p < 240)
        if non_bg < (240 * 135) * 0.02:
            return "illustration appears nearly blank after rasterization"
    except Exception:
        return None
    return None


def _check_style_consistency(svg: str, token_name: str) -> str | None:
    from .style_tokens import get_style_token
    allowed = get_style_token(token_name).palette() | {"#FFFFFF", "#33474A", "#2C3E3A"}
    for m in re.finditer(r'(?:fill|stroke)="#([0-9A-Fa-f]{3,6})"', svg):
        hexv = "#" + m.group(1)
        if len(hexv) == 4:
            hexv = "#" + "".join(c * 2 for c in hexv[1:])
        if hexv.upper() not in {c.upper() for c in allowed}:
            return f"colour {hexv} is outside the style palette"
    return None


def _el_bbox(svg: str, eid: str) -> tuple[float, float, float, float] | None:
    """Bounding box of an element tagged with id=`eid` (rect/circle/path/polyline)."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return None
    for el in root.iter():
        if el.get("id") != eid:
            continue
        tag = el.tag.split("}")[-1]
        try:
            if tag == "rect":
                x = float(el.get("x", 0)); y = float(el.get("y", 0))
                w = float(el.get("width", 0)); h = float(el.get("height", 0))
                return (x, y, x + w, y + h)
            if tag == "circle":
                cx = float(el.get("cx", 0)); cy = float(el.get("cy", 0)); r = float(el.get("r", 0))
                return (cx - r, cy - r, cx + r, cy + r)
            if tag in ("path", "polyline"):
                attr = el.get("d") if tag == "path" else el.get("points", "")
                nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", attr)]
                pts = list(zip(nums[0::2], nums[1::2]))
                if not pts:
                    return None
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                return (min(xs), min(ys), max(xs), max(ys))
        except (TypeError, ValueError):
            return None
    return None


def _union_bbox(svg: str, eids: list[str]) -> tuple[float, float, float, float] | None:
    boxes = [_el_bbox(svg, e) for e in eids]
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _subject_bbox_ratio(svg: str) -> float:
    """Width of the bed+person+blanket union as a fraction of the 1200 canvas."""
    u = _union_bbox(svg, ["sib-bed", "sib-pillow", "sib-head", "sib-body", "sib-blanket"])
    if not u:
        return 0.0
    return (u[2] - u[0]) / 1200.0


# Minimum subject-width ratio per aspect (so the subject is the clear visual
# centre and stays readable when shrunk). Thumbnail must be largest.
_ASPECT_MIN_SUBJECT_RATIO = {"16:9": 0.45, "1:1": 0.50, "thumb": 0.55}


def _check_sleep_composition(svg: str, aspect: str) -> tuple[list[str], list[str]]:
    """Hard teaching-suitability checks for the SleepingInBed composite.

    These catch the 'structurally correct but visually poor' failure: a scene
    can contain all the right components yet still fail to read as 'a person
    sleeping' if the head floats off the pillow, the blanket misses the body,
    the Z drifts to the foot, or the subject is lost in whitespace.
    """
    blocking: list[str] = []
    warnings: list[str] = []
    pillow = _el_bbox(svg, "sib-pillow")
    head = _el_bbox(svg, "sib-head")
    body = _el_bbox(svg, "sib-body")
    blanket = _el_bbox(svg, "sib-blanket")
    z = _el_bbox(svg, "sib-z")
    window = _el_bbox(svg, "sib-window")
    moon = _el_bbox(svg, "sib-moon")

    # (1) Head must rest ON the pillow (horizontal overlap + vertical contact).
    if pillow and head:
        tol = 4.0
        x_in = pillow[0] - tol <= head[0] <= pillow[2] + tol
        on_top = head[3] >= pillow[1] - tol
        if not (x_in and on_top):
            blocking.append("sleep: head is not resting on the pillow "
                            f"(head bbox {tuple(round(v) for v in head)} vs pillow {tuple(round(v) for v in pillow)})")
    else:
        blocking.append("sleep: missing head/pillow contact elements")

    # (2) Blanket must cover the torso (span the body's centre, overlap its top).
    if body and blanket:
        body_cx = (body[0] + body[2]) / 2
        covers_x = blanket[0] <= body_cx <= blanket[2]
        covers_y = blanket[3] >= body[1]
        if not (covers_x and covers_y):
            blocking.append("sleep: blanket does not cover the torso "
                            f"(blanket {tuple(round(v) for v in blanket)} vs body {tuple(round(v) for v in body)})")
    else:
        blocking.append("sleep: missing blanket/body elements")

    # (3) Z must sit ABOVE the head, near its horizontal anchor.
    if z and head:
        z_cx = (z[0] + z[2]) / 2
        head_cx = (head[0] + head[2]) / 2
        above = z[3] <= head[1] + 2
        near = abs(z_cx - head_cx) <= 90
        if not above:
            blocking.append("sleep: 'Z' sleep marks are not above the head")
        elif not near:
            warnings.append("sleep: 'Z' marks drift away from the head anchor")
    elif z and not head:
        blocking.append("sleep: 'Z' marks present but head missing")

    # (4) Moon must sit INSIDE the window's visible area (spatial background).
    if window:
        if not moon:
            blocking.append("sleep: window present but moon (spatial background) missing")
        elif not (window[0] <= moon[0] and window[1] <= moon[1]
                  and moon[2] <= window[2] and moon[3] <= window[3]):
            blocking.append("sleep: moon is outside the window (no spatial background)")
    else:
        # thumbnail intentionally drops the window; nothing to verify.
        pass

    # (5) Subject must dominate the frame (not lost in whitespace).
    ratio = _subject_bbox_ratio(svg)
    min_ratio = _ASPECT_MIN_SUBJECT_RATIO.get(aspect, 0.45)
    if ratio < min_ratio:
        blocking.append(f"sleep: subject occupies only {ratio:.0%} of the canvas width "
                        f"(< {min_ratio:.0%} required for '{aspect}')")
    if ratio > 0.85:
        warnings.append(f"sleep: subject occupies {ratio:.0%} of the canvas (may clip edges)")

    # (6) Different aspects must be genuinely different recipes, not one crop.
    if aspect == "16:9" and not window:
        blocking.append("sleep: 16:9 composition must show the bedroom environment (window)")
    if aspect == "thumb" and window:
        blocking.append("sleep: thumbnail must drop the window (different recipe from 16:9)")

    return blocking, warnings
