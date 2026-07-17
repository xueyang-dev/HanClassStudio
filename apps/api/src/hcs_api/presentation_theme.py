"""Small, master-derived presentation theme selection and provenance helpers.

Themes belong to the presentation layer.  They make concrete visual decisions
once, then let PPTX, HTML, SVG fallback and illustration briefs consume those
decisions without making a provider part of the courseware contract.
"""

from __future__ import annotations

import colorsys
import json
from pathlib import Path
from typing import Any

from PIL import Image

from .models import (
    AssetManifest,
    LessonBlueprint,
    LessonProfile,
    PresentationTheme,
    PresentationThemeDecision,
    ProviderCapabilityDescriptor,
    ProviderSettings,
    ThemeCapabilitySupport,
    ThemeImageTreatment,
    ThemeLayout,
    ThemePalette,
    ThemeShapeLanguage,
    ThemeTypography,
    ThemeVideoTreatment,
    VideoGenerationRequest,
    VisualThemeCatalog,
    VisualThemeId,
    VisualThemePresetSummary,
    VisualThemePreview,
    VisualThemeSelection,
    VisualThemeState,
)


MASTER_THEME_SOURCE = "hanclassstudio:visual-theme-registry.v1"
THEME_VERSION = "1"
DEFAULT_THEME_ID: VisualThemeId = "classroom-clear"
WARM_THEME_ID: VisualThemeId = "warm-story"
THEME_SELECTION_PATH = Path("presentation/theme_selection.json")
THEME_DECISION_PATH = Path("presentation/presentation_theme.json")
VIDEO_REQUEST_PATH = Path("assets/data/video_generation_requests.json")

LEGACY_THEME_ALIASES: dict[str, VisualThemeId] = {
    "ppt_master_blue_classroom_v1": "classroom-clear",
    "ppt_master_warm_classroom_v1": "warm-story",
}


def _theme(
    theme_id: VisualThemeId,
    *,
    background: str,
    surface: str,
    primary: str,
    secondary: str,
    accent: str,
    text: str,
    muted: str,
    line: str,
    image_palette: list[str],
    mood: str,
    illustration_style: str,
    video_grade: str,
    video_motion: str,
) -> PresentationTheme:
    return PresentationTheme(
        theme_id=theme_id,
        version=THEME_VERSION,
        source=MASTER_THEME_SOURCE,
        audience_profile="beginner Chinese classroom",
        visual_mood=mood,
        typography=ThemeTypography(
            chinese_font="微软雅黑",
            pinyin_font="Arial",
            latin_font="Arial",
            fallback_fonts=["Noto Sans SC", "Microsoft YaHei", "sans-serif"],
            title_size_pt=24,
            chinese_hero_size_pt=54,
            pinyin_size_pt=25,
            body_size_pt=18,
        ),
        palette=ThemePalette(
            background=background, surface=surface, primary=primary, secondary=secondary,
            accent=accent, text=text, muted=muted, line=line,
            success="D9EFCF", warning="FCEDD3",
        ),
        shapes=ThemeShapeLanguage(corner_radius=0.12, border_weight=1.2, shadow="subtle", card_treatment="soft_surface"),
        layout=ThemeLayout(safe_margin_inches=0.68, grid_columns=12, whitespace="generous", image_text_ratio="5:4", max_content_items=6),
        image_treatment=ThemeImageTreatment(
            illustration_style=illustration_style,
            palette_descriptors=image_palette,
            palette_anchors=[f"#{value}" for value in (primary, secondary, accent, surface)],
            saturation="soft_distinct", contrast="clear_subject_background",
            background_complexity="low", framing="rounded_cover",
            prohibited_traits=["embedded words", "watermark", "poster layout", "UI/infographic layout", "neon", "heavy shadow"],
        ),
        video_treatment=ThemeVideoTreatment(
            visual_style=f"{mood}; clear educational sequence",
            color_grade=video_grade,
            lighting="even subject lighting with readable faces and teaching objects",
            motion_style=video_motion,
            subtitle_direction="high-contrast support-language subtitles within title-safe lower-third margins",
            prohibited_traits=["rapid cuts", "flashing transitions", "decorative subtitles", "watermark", "unreadable text"],
        ),
    )


THEMES: dict[VisualThemeId, PresentationTheme] = {
    DEFAULT_THEME_ID: _theme(
        DEFAULT_THEME_ID, background="F5FAFE", surface="FFFFFF", primary="5B9BD5",
        secondary="EAF4FC", accent="D96B4B", text="26374A", muted="626D75", line="B9D5EC",
        image_palette=["pale blue classroom surfaces", "restrained terracotta accents", "clean white teaching space"],
        mood="clear, bright, restrained classroom",
        illustration_style="soft_flat_educational_v1", video_grade="neutral daylight with restrained blue and terracotta accents",
        video_motion="locked or gently guided classroom camera",
    ),
    "active-learning": _theme(
        "active-learning", background="F4FBF8", surface="FFFFFF", primary="167A72",
        secondary="DDF4EA", accent="E5684A", text="203C39", muted="60726E", line="A9D9CF",
        image_palette=["fresh teal activity zones", "coral action accents", "bright natural classroom light"],
        mood="energetic, participatory, age-neutral",
        illustration_style="soft_flat_educational_v1", video_grade="fresh teal-and-coral classroom colour with natural skin tones",
        video_motion="stable medium shots with restrained activity-focused cuts",
    ),
    WARM_THEME_ID: _theme(
        WARM_THEME_ID, background="FCF7F0", surface="FFFDF9", primary="9A5139",
        secondary="F7E6D2", accent="C98752", text="3D302B", muted="786B64", line="D9C6B7",
        image_palette=["warm peach and cream surfaces", "terracotta structure", "soft natural light"],
        mood="warm, calm, gently narrative",
        illustration_style="soft_flat_educational_v1", video_grade="warm natural light with cream and terracotta anchors",
        video_motion="calm observational shots with slow, purposeful transitions",
    ),
    "eastern-elegance": _theme(
        "eastern-elegance", background="F7F4EC", surface="FFFEFA", primary="263D36",
        secondary="E9E4D7", accent="A54232", text="252A27", muted="686C66", line="C9C3B5",
        image_palette=["paper white and ink", "restrained cinnabar accent", "muted jade detail"],
        mood="modern eastern restraint with generous whitespace",
        illustration_style="soft_flat_educational_v1", video_grade="paper-neutral highlights, ink shadows, restrained cinnabar and jade accents",
        video_motion="composed static frames with deliberate, minimal movement",
    ),
    "future-exploration": _theme(
        "future-exploration", background="101B2D", surface="18273C", primary="69D2E7",
        secondary="213754", accent="A98AF2", text="F2F7FC", muted="B8C5D3", line="3B5875",
        image_palette=["deep navy structure", "clear cyan light", "restrained violet signals"],
        mood="structured, exploratory, projection-safe technology",
        illustration_style="soft_flat_educational_v1", video_grade="deep navy environment with controlled cyan and violet highlights",
        video_motion="precise grid-led movement and slow technical reveals",
    ),
}

THEME_METADATA: dict[VisualThemeId, tuple[str, str, str]] = {
    "classroom-clear": ("visualTheme.preset.classroom-clear.name", "visualTheme.preset.classroom-clear.description", "clarity"),
    "active-learning": ("visualTheme.preset.active-learning.name", "visualTheme.preset.active-learning.description", "activity"),
    "warm-story": ("visualTheme.preset.warm-story.name", "visualTheme.preset.warm-story.description", "story"),
    "eastern-elegance": ("visualTheme.preset.eastern-elegance.name", "visualTheme.preset.eastern-elegance.description", "paper"),
    "future-exploration": ("visualTheme.preset.future-exploration.name", "visualTheme.preset.future-exploration.description", "grid"),
}


def available_theme_ids() -> set[str]:
    return set(THEMES)


def default_presentation_theme() -> PresentationTheme:
    return THEMES[DEFAULT_THEME_ID].model_copy(deep=True)


def normalize_theme_id(theme_id: str | None) -> VisualThemeId:
    candidate = LEGACY_THEME_ALIASES.get(theme_id or "", theme_id)
    return candidate if candidate in THEMES else DEFAULT_THEME_ID  # type: ignore[return-value]


def theme_by_id(theme_id: str | None) -> PresentationTheme:
    return THEMES[normalize_theme_id(theme_id)].model_copy(deep=True)


def visual_theme_catalog() -> VisualThemeCatalog:
    presets: list[VisualThemePresetSummary] = []
    for theme_id, theme in THEMES.items():
        name_key, description_key, motif = THEME_METADATA[theme_id]
        presets.append(VisualThemePresetSummary(
            theme_id=theme_id,
            version=theme.version,
            name_key=name_key,
            description_key=description_key,
            preview=VisualThemePreview(
                background=f"#{theme.palette.background}",
                surface=f"#{theme.palette.surface}",
                primary=f"#{theme.palette.primary}",
                accent=f"#{theme.palette.accent}",
                text=f"#{theme.palette.text}",
                motif=motif,
            ),
        ))
    return VisualThemeCatalog(theme_version=THEME_VERSION, presets=presets)


def recommend_visual_theme(
    profile: LessonProfile | None = None,
    blueprint: LessonBlueprint | None = None,
) -> tuple[VisualThemeId, str]:
    """Small, deterministic and explainable recommendation rules."""
    parts: list[str] = []
    if profile:
        parts.extend([
            profile.lesson_title,
            profile.subject,
            profile.learner_level,
            profile.target_students,
            profile.lesson_type,
        ])
    if blueprint:
        parts.extend([
            blueprint.lesson_title,
            blueprint.route_hint,
            *blueprint.objectives,
            *blueprint.grammar_points,
            *(slide.title for slide in blueprint.slides),
            *(slide.slide_type for slide in blueprint.slides),
        ])
    text = " ".join(parts).casefold()
    if any(token in text for token in ("科技", "工程", "能源", "职业", "technology", "engineering", "energy", "stem", "career")):
        return "future-exploration", "future_content"
    if any(token in text for token in ("节日", "文学", "古诗", "文化", "跨文化", "festival", "literature", "poetry", "culture")):
        return "eastern-elegance", "cultural_content"
    if any(token in text for token in ("幼儿", "儿童", "少年", "游戏", "竞赛", "练习", "child", "children", "young", "game", "quiz", "practice")):
        return "active-learning", "younger_or_activity_focused"
    if any(token in text for token in ("故事", "生活", "阅读", "情景", "对话", "story", "daily life", "reading", "scenario", "dialogue")):
        return "warm-story", "story_or_life_context"
    return DEFAULT_THEME_ID, "default_clear"


def visual_theme_selection_for_project(
    project_root: Path,
    *,
    profile: LessonProfile | None = None,
    blueprint: LessonBlueprint | None = None,
) -> VisualThemeSelection:
    if profile is None:
        profile = _read_project_model(project_root / "assets/data/lesson_profile.json", LessonProfile)
    if blueprint is None:
        blueprint = _read_project_model(project_root / "blueprints/lesson_blueprint.json", LessonBlueprint)
    config = _read_selection(project_root)
    recommended, reason = recommend_visual_theme(profile, blueprint)
    if config.get("mode") in {"auto", "manual"}:
        mode = str(config["mode"])
        requested = normalize_theme_id(str(config.get("selected_theme_id") or recommended))
        selected = recommended if mode == "auto" else requested
        return VisualThemeSelection(
            mode=mode,
            selected_theme_id=selected,
            recommended_theme_id=recommended,
            recommendation_reason=reason,
            theme_version=THEME_VERSION,
        )
    if config.get("decision_source") == "teacher_selected":
        return VisualThemeSelection(
            mode="manual", selected_theme_id=normalize_theme_id(str(config.get("theme_id") or "")),
            recommended_theme_id=recommended, recommendation_reason=reason,
        )
    if config.get("decision_source") == "inherited_from_existing_assets":
        manifest = _read_project_model(project_root / "assets/data/asset_manifest.json", AssetManifest)
        decision = resolve_presentation_theme(project_root, manifest=manifest, selection=config)
        return VisualThemeSelection(
            mode="manual", selected_theme_id=normalize_theme_id(decision.theme.theme_id),
            recommended_theme_id=recommended, recommendation_reason=reason,
        )
    decision_path = project_root / THEME_DECISION_PATH
    if decision_path.is_file():
        try:
            decision = PresentationThemeDecision.model_validate_json(decision_path.read_text(encoding="utf-8"))
            if decision.decision_source in {"teacher_selected", "inherited_from_existing_assets"}:
                return VisualThemeSelection(
                    mode="manual", selected_theme_id=normalize_theme_id(decision.theme.theme_id),
                    recommended_theme_id=recommended, recommendation_reason=reason,
                )
        except Exception:
            pass
    return VisualThemeSelection(
        mode="auto",
        selected_theme_id=recommended,
        recommended_theme_id=recommended,
        recommendation_reason=reason,
    )


def presentation_theme_for_project(project_root: Path) -> PresentationTheme:
    profile = _read_project_model(project_root / "assets/data/lesson_profile.json", LessonProfile)
    blueprint = _read_project_model(project_root / "blueprints/lesson_blueprint.json", LessonBlueprint)
    decision_path = project_root / THEME_DECISION_PATH
    if decision_path.is_file():
        try:
            decision = PresentationThemeDecision.model_validate_json(decision_path.read_text(encoding="utf-8"))
            if decision.theme.theme_id in THEMES:
                return decision.theme
            if decision.decision_source == "ppt_master_auto":
                selection = visual_theme_selection_for_project(project_root, profile=profile, blueprint=blueprint)
                return theme_by_id(selection.selected_theme_id)
            return theme_by_id(decision.theme.theme_id)
        except Exception:
            pass
    selection = visual_theme_selection_for_project(project_root, profile=profile, blueprint=blueprint)
    return theme_by_id(selection.selected_theme_id)


def project_has_presentation_theme(project_root: Path) -> bool:
    """Projects with a profile receive the deterministic default/recommendation."""
    return any((project_root / path).is_file() for path in (
        THEME_DECISION_PATH,
        THEME_SELECTION_PATH,
        Path("assets/data/lesson_profile.json"),
    ))


def _read_project_model(
    path: Path,
    model_type: type[LessonProfile] | type[LessonBlueprint] | type[AssetManifest],
):
    if not path.is_file():
        return None
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_presentation_theme(
    project_root: Path,
    *,
    lesson_title: str = "",
    profile: LessonProfile | None = None,
    blueprint: LessonBlueprint | None = None,
    manifest: AssetManifest | None = None,
    selection: dict[str, Any] | None = None,
) -> PresentationThemeDecision:
    """Resolve one registry preset and persist no secrets or provider fields."""
    config = selection if selection is not None else _read_selection(project_root)
    if config.get("mode") in {"auto", "manual"}:
        mode = str(config["mode"])
        recommended, reason = recommend_visual_theme(profile, blueprint)
        requested = normalize_theme_id(str(config.get("selected_theme_id") or recommended))
        selected = recommended if mode == "auto" else requested
        return PresentationThemeDecision(
            decision_source="ppt_master_auto" if mode == "auto" else "teacher_selected",
            requested_theme_id=selected if mode == "manual" else None,
            theme=theme_by_id(selected),
            rationale=[
                f"Visual theme registry: {MASTER_THEME_SOURCE}",
                f"{'Auto recommendation' if mode == 'auto' else 'Teacher selection'}: {selected} ({reason if mode == 'auto' else 'manual'}).",
            ],
        )
    source = str(config.get("decision_source", "ppt_master_auto"))
    if source not in {"ppt_master_auto", "teacher_selected", "inherited_from_existing_assets"}:
        source = "ppt_master_auto"
    requested = config.get("theme_id")
    observations: dict[str, Any] = {}
    rationale = [f"Reference master: {MASTER_THEME_SOURCE}"]
    if source == "teacher_selected":
        theme = theme_by_id(requested)
        if requested not in THEMES:
            rationale.append(f"Unknown teacher theme '{requested}'; used {DEFAULT_THEME_ID}.")
        else:
            rationale.append(f"Teacher selected {theme.theme_id}.")
        _apply_teacher_overrides(theme, config.get("overrides", {}), rationale)
    elif source == "inherited_from_existing_assets":
        observations = observe_existing_image_palette(project_root, manifest)
        theme, score = _closest_theme(observations)
        rationale.extend([
            f"Selected {theme.theme_id} from {observations.get('image_count', 0)} local accepted/generated image(s).",
            f"Palette compatibility score: {score:.3f}; warm master surfaces are closer to the observed peach/cream anchors.",
        ])
    else:
        recommended, reason = recommend_visual_theme(profile, blueprint)
        theme = theme_by_id(recommended)
        rationale.append(f"Auto-selected {theme.theme_id} for {lesson_title or 'the lesson'} ({reason}).")
    return PresentationThemeDecision(
        decision_source=source,
        requested_theme_id=requested if source == "teacher_selected" else None,
        theme=theme,
        rationale=rationale,
        asset_observations=observations,
    )


def persist_theme_decision(project_root: Path, decision: PresentationThemeDecision, manifest: AssetManifest | None = None) -> PresentationThemeDecision:
    path = project_root / THEME_DECISION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(decision.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    for relative_path in (
        Path("presentation/presentation_content_plan.json"),
        Path("presentation/presentation_content_plan.reconciled.json"),
    ):
        plan_path = project_root / relative_path
        if not plan_path.is_file():
            continue
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if isinstance(plan, dict):
                plan["presentation_theme_id"] = decision.theme.theme_id
                plan["presentation_theme_version"] = decision.theme.version
                plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # Theme provenance must never block an otherwise valid lesson build.
            continue
    if manifest is not None:
        manifest.presentation_theme_id = decision.theme.theme_id
        manifest.presentation_theme_version = decision.theme.version
        # An inherited decision explicitly classifies the observed assets that
        # produced it. Other decisions must never fill missing provenance on
        # retained media: unknown historical assets need to remain observable
        # as a mismatch instead of being silently declared current.
        if decision.decision_source == "inherited_from_existing_assets":
            for asset in [*manifest.images, *manifest.video]:
                asset.presentation_theme_id = decision.theme.theme_id
                asset.presentation_theme_version = decision.theme.version
    return decision


def persist_visual_theme_selection(
    project_root: Path,
    *,
    mode: str,
    selected_theme_id: str | None,
    profile: LessonProfile | None = None,
    blueprint: LessonBlueprint | None = None,
) -> VisualThemeSelection:
    recommended, reason = recommend_visual_theme(profile, blueprint)
    if mode not in {"auto", "manual"}:
        raise ValueError("Visual theme mode must be auto or manual")
    if mode == "manual" and selected_theme_id not in THEMES:
        raise ValueError("A supported visual theme is required for manual mode")
    selected = recommended if mode == "auto" else normalize_theme_id(selected_theme_id)
    selection = VisualThemeSelection(
        mode=mode,
        selected_theme_id=selected,
        recommended_theme_id=recommended,
        recommendation_reason=reason,
        theme_version=THEME_VERSION,
    )
    path = project_root / THEME_SELECTION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(selection.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    temporary.replace(path)
    decision = resolve_presentation_theme(
        project_root,
        profile=profile,
        blueprint=blueprint,
        selection=selection.model_dump(mode="json", by_alias=True),
    )
    persist_theme_decision(project_root, decision)
    return selection


def _capability_support(
    capability: str,
    provider_id: str | None,
    catalog: list[ProviderCapabilityDescriptor],
) -> ThemeCapabilitySupport:
    if capability == "presentation":
        return ThemeCapabilitySupport(capability="presentation", state="supported")
    descriptor = next(
        (item for item in catalog if item.capability == capability and item.provider_id == provider_id),
        None,
    )
    if descriptor is None:
        return ThemeCapabilitySupport(
            capability=capability, provider_id=provider_id, state="unsupported",
            reason="No selected Provider exposes a visual-theme contract.",
        )
    if not descriptor.implemented or "visual_theme" not in descriptor.supported_operations:
        return ThemeCapabilitySupport(
            capability=capability, provider_id=provider_id, state="unsupported",
            reason=descriptor.unavailable_reason or "This Provider does not support visual-theme direction.",
        )
    if not descriptor.configured:
        return ThemeCapabilitySupport(
            capability=capability, provider_id=provider_id, state="not_configured",
            reason=descriptor.unavailable_reason or "Provider configuration is incomplete.",
        )
    if not descriptor.available:
        return ThemeCapabilitySupport(
            capability=capability, provider_id=provider_id, state="unavailable",
            reason=descriptor.unavailable_reason or "Provider is currently unavailable.",
        )
    return ThemeCapabilitySupport(capability=capability, provider_id=provider_id, state="supported")


def visual_theme_state_for_project(
    project_root: Path,
    *,
    profile: LessonProfile | None = None,
    blueprint: LessonBlueprint | None = None,
    manifest: AssetManifest | None = None,
    provider_catalog: list[ProviderCapabilityDescriptor] | None = None,
    provider_settings: ProviderSettings | None = None,
) -> VisualThemeState:
    selection = visual_theme_selection_for_project(project_root, profile=profile, blueprint=blueprint)
    catalog = provider_catalog or []
    image_provider = provider_settings.image.provider if provider_settings else None
    video_provider = provider_settings.video.provider if provider_settings else None
    support = [
        _capability_support("presentation", None, catalog),
        _capability_support("image", image_provider, catalog),
        _capability_support("video", video_provider, catalog),
    ]
    mismatch_ids: list[str] = []
    mismatch_capabilities: set[str] = set()
    media = [*(manifest.images if manifest else []), *(manifest.video if manifest else [])]
    for asset in media:
        if not asset.path:
            continue
        asset_theme_id = normalize_theme_id(asset.presentation_theme_id) if asset.presentation_theme_id else None
        if asset_theme_id != selection.selected_theme_id or asset.presentation_theme_version != selection.theme_version:
            mismatch_ids.append(asset.id)
            mismatch_capabilities.add("video" if asset.kind == "video" else "image")
    support_by_capability = {item.capability: item for item in support}
    regeneration_available = bool(mismatch_ids) and all(
        support_by_capability[capability].state == "supported"
        for capability in mismatch_capabilities
    )
    return VisualThemeState(
        selection=selection,
        effective_theme_id=selection.selected_theme_id,
        effective_theme_version=selection.theme_version,
        media_state="not_generated" if not media else "mixed" if mismatch_ids else "current",
        mismatched_media_count=len(mismatch_ids),
        mismatched_media_ids=sorted(mismatch_ids),
        provider_support=support,
        regeneration_available=regeneration_available,
    )


def video_generation_requests(
    blueprint: LessonBlueprint,
    theme: PresentationTheme,
    support: ThemeCapabilitySupport,
) -> list[VideoGenerationRequest]:
    """Compile requests without claiming that an unsupported adapter ran."""
    requests: list[VideoGenerationRequest] = []
    for slide in blueprint.slides:
        requirements = slide.media_requirements
        if not requirements.video_key or not requirements.video_scene_prompt:
            continue
        requests.append(VideoGenerationRequest(
            id=requirements.video_key,
            prompt=requirements.video_scene_prompt,
            provider_id=support.provider_id,
            theme_id=normalize_theme_id(theme.theme_id),
            theme_version=theme.version,
            theme_direction=theme.video_treatment.model_copy(deep=True),
            theme_application_state=support.state,
            theme_application_reason=support.reason,
        ))
    return requests


def observe_existing_image_palette(project_root: Path, manifest: AssetManifest | None = None) -> dict[str, Any]:
    images = (manifest.images if manifest else [])
    samples: list[tuple[int, int, int]] = []
    hashes: list[str] = []
    sampled_image_count = 0
    for asset in images:
        if asset.kind != "image" or not asset.path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        path = project_root / asset.path
        if not path.is_file():
            continue
        try:
            image = Image.open(path).convert("RGB").resize((48, 27))
        except Exception:
            continue
        sampled_image_count += 1
        samples.extend(image.get_flattened_data())
        if asset.content_hash:
            hashes.append(asset.content_hash)
    if not samples:
        return {"image_count": 0, "dominant_colors": [], "mean_brightness": None, "mean_saturation": None, "asset_hashes": hashes}
    bins: dict[tuple[int, int, int], int] = {}
    saturations: list[float] = []
    brightness: list[float] = []
    for r, g, b in samples:
        key = tuple(min(255, round(channel / 32) * 32) for channel in (r, g, b))
        bins[key] = bins.get(key, 0) + 1
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        saturations.append(s); brightness.append(v)
    dominant = [f"#{r:02X}{g:02X}{b:02X}" for (r, g, b), _ in sorted(bins.items(), key=lambda item: item[1], reverse=True)[:6]]
    return {
        "image_count": sampled_image_count,
        "dominant_colors": dominant,
        "mean_brightness": round(sum(brightness) / len(brightness), 3),
        "mean_saturation": round(sum(saturations) / len(saturations), 3),
        "asset_hashes": hashes,
    }


def _closest_theme(observations: dict[str, Any]) -> tuple[PresentationTheme, float]:
    colors = observations.get("dominant_colors", [])
    if not colors:
        return default_presentation_theme(), 0.0
    observed = [_rgb(value) for value in colors]
    scored: list[tuple[float, PresentationTheme]] = []
    for theme in THEMES.values():
        anchors = [_rgb("#" + value) for value in [theme.palette.background, theme.palette.surface, theme.palette.primary, theme.palette.secondary, theme.palette.accent]]
        distance = sum(min(_distance(color, anchor) for anchor in anchors) for color in observed) / len(observed)
        # Warm images get a small, explainable preference for the master palette's peach surface variant.
        if theme.theme_id == WARM_THEME_ID and observations.get("mean_saturation", 1) <= 0.55:
            distance *= 0.88
        scored.append((distance, theme))
    distance, selected = min(scored, key=lambda item: item[0])
    return selected.model_copy(deep=True), max(0.0, 1 - distance / 441.7)


def _read_selection(project_root: Path) -> dict[str, Any]:
    path = project_root / THEME_SELECTION_PATH
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _apply_teacher_overrides(theme: PresentationTheme, overrides: Any, rationale: list[str]) -> None:
    if not isinstance(overrides, dict):
        return
    fonts = overrides.get("typography")
    if isinstance(fonts, dict):
        for field in ("chinese_font", "pinyin_font", "latin_font"):
            value = fonts.get(field)
            if isinstance(value, str) and value.strip():
                # The config-level contract validates against its explicit fallback chain:
                # an unsupported arbitrary name never becomes the only font choice.
                if value in {"微软雅黑", "Arial", "Noto Sans SC", "Microsoft YaHei"}:
                    setattr(theme.typography, field, value)
                else:
                    rationale.append(f"Unavailable font '{value}' for {field}; retained {getattr(theme.typography, field)} with fallback chain.")
    palette = overrides.get("palette")
    if isinstance(palette, dict):
        for field in ("background", "surface", "primary", "secondary", "accent", "text", "muted", "line"):
            value = palette.get(field)
            if isinstance(value, str) and _valid_hex(value):
                setattr(theme.palette, field, value.lstrip("#").upper())


def _valid_hex(value: str) -> bool:
    value = value.lstrip("#")
    return len(value) == 6 and all(char in "0123456789abcdefABCDEF" for char in value)


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right)) ** 0.5
