"""Unified visual language for HanClassStudio teaching illustrations.

A single style token owns every cross-cutting visual decision so that
illustrations stay consistent regardless of which concept or model produced
them. Components and the renderer read ONLY from here — they never hard-code
colours, stroke widths, or proportions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# The only supported style token in this phase. Components/rules reference it
# by name so we can add variants later without touching component code.
DEFAULT_STYLE_TOKEN = "soft_flat_educational_v1"

# Neutral, varied skin / hair / garment pools so characters are not monochrome
# and avoid implying any single ethnicity. Picked to stay in-palette.
SKIN_TONES = ("#F3C9A8", "#E8B98F", "#D9A06B", "#C68A57")
HAIR_TONES = ("#4A3B33", "#2E2A28", "#6B4A33", "#3A3F4A")


@dataclass
class StyleToken:
    name: str = DEFAULT_STYLE_TOKEN
    # Backgrounds
    bg_light: str = "#F4F8F6"
    bg_light_warm: str = "#FBF6EF"
    # Brand / accents (max 2 accents + neutrals)
    accent: str = "#2E8B78"          # teal (brand)
    accent2: str = "#E0864B"         # warm orange (variety)
    fabric_blue: str = "#5B8FB0"
    fabric_teal: str = "#4E8C9E"
    wood: str = "#B98A5E"
    white: str = "#FFFFFF"
    ink: str = "#33474A"             # dark outline / neutral
    # Night scene
    night_top: str = "#2C3E63"
    night_bottom: str = "#1E2C49"
    moon: str = "#F4E3A1"
    star: str = "#FDF6D8"
    # Soft auxiliary (semantic symbols such as sleep 'Z' marks) — a light,
    # low-weight tint so it never competes with the subject as a 2nd centre.
    aux_symbol: str = "#A9BCC2"
    # Outline rules
    outline: str = "#33474A"
    outline_width: float = 3.5       # absolute px at 1200x675 canvas
    corner_radius: float = 14.0      # soft rounded corners
    shadow_strength: float = 0.10    # very low; flat look
    # Proportion rules
    head_body_ratio: tuple[float, float] = (0.20, 0.26)  # head height / total height
    body_height_unit: float = 320.0  # px for a scene-level standing person
    icon_unit: float = 150.0         # px for an icon-level subject
    # Composition limits
    min_subject_scale_ratio: float = 0.35
    max_subject_scale_ratio: float = 0.65
    decoration_density: str = "low"  # background must not compete with subject
    # Banned effects (enforced by the illustration-quality gate too)
    banned_effects: tuple[str, ...] = (
        "glassmorphism", "gradient-mesh", "heavy-shadow", "neon",
        "photorealistic", "emoji-collage", "skeuomorphic",
    )

    def palette(self) -> set[str]:
        return {
            self.bg_light, self.bg_light_warm, self.accent, self.accent2,
            self.fabric_blue, self.fabric_teal, self.wood, self.white,
            self.ink,             self.night_top, self.night_bottom, self.moon, self.star, self.aux_symbol,
            *SKIN_TONES, *HAIR_TONES,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "accent": self.accent,
            "accent2": self.accent2,
            "outline": self.outline,
            "outline_width": self.outline_width,
            "corner_radius": self.corner_radius,
            "shadow_strength": self.shadow_strength,
            "head_body_ratio": list(self.head_body_ratio),
            "min_subject_scale_ratio": self.min_subject_scale_ratio,
            "max_subject_scale_ratio": self.max_subject_scale_ratio,
            "decoration_density": self.decoration_density,
            "aux_symbol": self.aux_symbol,
            "banned_effects": list(self.banned_effects),
        }


STYLE_TOKENS: dict[str, StyleToken] = {DEFAULT_STYLE_TOKEN: StyleToken()}


def get_style_token(name: str | None = None) -> StyleToken:
    return STYLE_TOKENS.get(name or DEFAULT_STYLE_TOKEN, STYLE_TOKENS[DEFAULT_STYLE_TOKEN])
