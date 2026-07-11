"""Compact PPT-master-derived design profile for editable courseware decks."""

from __future__ import annotations

from dataclasses import dataclass


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
