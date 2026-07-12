"""Compact PPT-master-derived design profile for editable courseware decks."""

from __future__ import annotations

from dataclasses import dataclass, replace


MASTER_SOURCE = "runtime/projects/0bce727f8b6f/uploads/第1课 教学课件 中文 七年级 第一学期.pptx"


@dataclass(frozen=True)
class LayoutRecipe:
    archetype: str
    safe_margin: float
    title_height: float
    content_top: float
    max_items: int
    image_mode: str = "cover"


@dataclass(frozen=True)
class PptMasterDesignProfile:
    source: str = MASTER_SOURCE
    slide_width: float = 13.333
    slide_height: float = 7.5
    safe_margin: float = 0.68
    background: str = "F5FAFE"
    background_alt: str = "EAF4FC"
    primary: str = "5B9BD5"
    accent: str = "00B0F0"
    mint: str = "D9EFCF"
    warm: str = "FCEDD3"
    ink: str = "26374A"
    muted: str = "6E747A"
    line: str = "B9D5EC"
    heading_font: str = "微软雅黑"
    chinese_font: str = "微软雅黑"
    latin_font: str = "Arial"
    title_size: int = 24
    chinese_hero_size: int = 54
    pinyin_size: int = 25
    meaning_size: int = 20
    instruction_size: int = 18
    minimum_body_size: int = 18
    card_radius: float = 0.12
    image_radius: float = 0.12


PROFILE = PptMasterDesignProfile()


def profile_for_theme(theme) -> PptMasterDesignProfile:
    """Apply a shared theme's actionable tokens to the reference-master layout."""
    if theme is None:
        return PptMasterDesignProfile()
    palette, typography, shapes = theme.palette, theme.typography, theme.shapes
    return replace(
        PptMasterDesignProfile(),
        background=palette.background,
        background_alt=palette.secondary,
        primary=palette.primary,
        accent=palette.accent,
        mint=palette.success,
        warm=palette.warning,
        ink=palette.text,
        muted=palette.muted,
        line=palette.line,
        heading_font=typography.chinese_font,
        chinese_font=typography.chinese_font,
        latin_font=typography.latin_font,
        title_size=typography.title_size_pt,
        chinese_hero_size=typography.chinese_hero_size_pt,
        pinyin_size=typography.pinyin_size_pt,
        meaning_size=max(14, typography.body_size_pt + 2),
        instruction_size=typography.body_size_pt,
        minimum_body_size=typography.body_size_pt,
        card_radius=shapes.corner_radius,
        image_radius=shapes.corner_radius,
    )


RECIPES = {
    "cover_title": LayoutRecipe("cover", 0.68, 0.8, 1.45, 1),
    "objectives_cards": LayoutRecipe("objectives", 0.68, 0.7, 1.55, 4),
    "single_item_focus": LayoutRecipe("vocabulary_focus", 0.68, 0.7, 1.5, 6),
    "two_card_contrast": LayoutRecipe("formal_informal_contrast", 0.68, 0.7, 1.55, 2),
    "listen_choose": LayoutRecipe("listening_choice", 0.68, 0.7, 1.55, 4),
    "dialogue_bubbles": LayoutRecipe("visual_scene", 0.68, 0.7, 1.45, 4),
    "match_pairs": LayoutRecipe("matching_activity", 0.68, 0.7, 1.55, 6),
    "summary_cards": LayoutRecipe("recap", 0.68, 0.7, 1.55, 5),
    "generic_content": LayoutRecipe("content", 0.68, 0.7, 1.55, 5),
}
