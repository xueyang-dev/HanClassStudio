"""Small, master-derived presentation theme selection and provenance helpers.

Themes belong to the presentation layer.  They make concrete visual decisions
once, then let PPTX, HTML, SVG fallback and illustration briefs consume those
decisions without making a provider part of the courseware contract.
"""

from __future__ import annotations

import colorsys
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

from .models import (
    AssetManifest,
    PresentationTheme,
    PresentationThemeDecision,
    ThemeImageTreatment,
    ThemeLayout,
    ThemePalette,
    ThemeShapeLanguage,
    ThemeTypography,
)


MASTER_THEME_SOURCE = "ppt-master:第1课 教学课件 中文 七年级 第一学期.pptx"
DEFAULT_THEME_ID = "ppt_master_blue_classroom_v1"
WARM_THEME_ID = "ppt_master_warm_classroom_v1"
THEME_SELECTION_PATH = Path("presentation/theme_selection.json")
THEME_DECISION_PATH = Path("presentation/presentation_theme.json")


def _theme(theme_id: str, *, background: str, surface: str, primary: str, secondary: str,
           accent: str, text: str, muted: str, line: str, image_palette: list[str], mood: str) -> PresentationTheme:
    return PresentationTheme(
        theme_id=theme_id,
        version="1",
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
            illustration_style="soft_flat_educational_v1",
            palette_descriptors=image_palette,
            palette_anchors=[f"#{value}" for value in (primary, secondary, accent, surface)],
            saturation="soft_distinct", contrast="clear_subject_background",
            background_complexity="low", framing="rounded_cover",
            prohibited_traits=["embedded words", "watermark", "poster layout", "UI/infographic layout", "neon", "heavy shadow"],
        ),
    )


# Both definitions use the observable reference-master palette: its blue
# headings and cyan details, its white/light-blue surfaces, and its peach card
# treatment.  The warm variant simply makes the existing peach treatment the
# dominant surface when accepted illustrations are warm and low-saturation.
THEMES: dict[str, PresentationTheme] = {
    DEFAULT_THEME_ID: _theme(
        DEFAULT_THEME_ID, background="F5FAFE", surface="FFFFFF", primary="5B9BD5",
        secondary="EAF4FC", accent="00B0F0", text="26374A", muted="6E747A", line="B9D5EC",
        image_palette=["pale blue classroom surfaces", "clean cyan detail", "soft peach support cards"],
        mood="clear, airy blue classroom",
    ),
    WARM_THEME_ID: _theme(
        WARM_THEME_ID, background="FCF8F3", surface="FFFFFF", primary="2A71AA",
        secondary="FCEDD3", accent="5B9BD5", text="26374A", muted="6E747A", line="D7C6B7",
        image_palette=["warm peach and cream surfaces", "muted blue structure", "soft natural classroom colour"],
        mood="warm, calm classroom with restrained blue structure",
    ),
}


def available_theme_ids() -> set[str]:
    return set(THEMES)


def default_presentation_theme() -> PresentationTheme:
    return THEMES[DEFAULT_THEME_ID].model_copy(deep=True)


def theme_by_id(theme_id: str | None) -> PresentationTheme:
    return THEMES.get(theme_id or "", THEMES[DEFAULT_THEME_ID]).model_copy(deep=True)


def presentation_theme_for_project(project_root: Path) -> PresentationTheme:
    decision_path = project_root / THEME_DECISION_PATH
    if decision_path.is_file():
        try:
            return PresentationThemeDecision.model_validate_json(decision_path.read_text(encoding="utf-8")).theme
        except Exception:
            pass
    return default_presentation_theme()


def project_has_presentation_theme(project_root: Path) -> bool:
    """Keep legacy HTML output unchanged until a project gets a theme decision."""
    return (project_root / THEME_DECISION_PATH).is_file()


def resolve_presentation_theme(
    project_root: Path,
    *,
    lesson_title: str = "",
    manifest: AssetManifest | None = None,
    selection: dict[str, Any] | None = None,
) -> PresentationThemeDecision:
    """Resolve one of the supported, master-derived themes and persist no secrets."""
    config = selection if selection is not None else _read_selection(project_root)
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
        theme = default_presentation_theme()
        rationale.append(f"Auto-selected {theme.theme_id} for {lesson_title or 'the lesson'}.")
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
        for asset in [*manifest.images, *manifest.audio, *manifest.video, *manifest.fonts]:
            asset.presentation_theme_id = decision.theme.theme_id
            asset.presentation_theme_version = decision.theme.version
            if asset.generation:
                asset.generation.theme_id = decision.theme.theme_id
                asset.generation.theme_version = decision.theme.version
    return decision


def observe_existing_image_palette(project_root: Path, manifest: AssetManifest | None = None) -> dict[str, Any]:
    images = (manifest.images if manifest else [])
    samples: list[tuple[int, int, int]] = []
    hashes: list[str] = []
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
        samples.extend(image.get_flattened_data())
        if asset.content_hash:
            hashes.append(asset.content_hash)
    if not samples:
        return {"image_count": 0, "dominant_colors": [], "mean_brightness": None, "mean_saturation": None, "asset_hashes": hashes}
    bins: dict[tuple[int, int, int], int] = {}
    saturations: list[float] = []
    brightness: list[float] = []
    for r, g, b in samples:
        key = (round(r / 32) * 32, round(g / 32) * 32, round(b / 32) * 32)
        bins[key] = bins.get(key, 0) + 1
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        saturations.append(s); brightness.append(v)
    dominant = [f"#{r:02X}{g:02X}{b:02X}" for (r, g, b), _ in sorted(bins.items(), key=lambda item: item[1], reverse=True)[:6]]
    return {
        "image_count": len({asset.path for asset in images if (project_root / asset.path).is_file()}),
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
