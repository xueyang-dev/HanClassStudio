"""Deterministic teaching brief compiler for provider-neutral illustrations."""

from __future__ import annotations

from .models import IllustrationBrief, IllustrationRequest, IllustrationStyleProfile
from .presentation_theme import theme_by_id


SOFT_FLAT_EDUCATIONAL_V1 = IllustrationStyleProfile(
    description="modern educational illustration with natural human anatomy and poses",
    requirements=[
        "simple uncluttered scene",
        "clear central action",
        "soft but distinct colors",
        "suitable for classroom projection and learner worksheets",
    ],
    forbidden_content=[
        "embedded words or captions",
        "watermark",
        "poster layout",
        "user-interface layout",
        "infographic layout",
        "distorted anatomy",
        "cluttered background",
    ],
)


def compile_illustration_request(brief: IllustrationBrief, request_id: str) -> IllustrationRequest:
    """Compile the same validated brief into the same ordered prompt."""
    profile = SOFT_FLAT_EDUCATIONAL_V1
    theme = theme_by_id(brief.presentation_theme_id)
    treatment = theme.image_treatment
    prompt = "\n".join([
        f"Teaching concept: {brief.concept}.",
        f"Scene purpose: {brief.scene_purpose}.",
        f"Learners: ages {brief.learner_age_range}; language level {brief.learner_language_level}.",
        f"Visual subject: {brief.visual_subject}.",
        f"Action: {brief.action}.",
        f"Environment: {brief.environment}.",
        f"People: {brief.number_of_people}.",
        f"Cultural context: {brief.cultural_context}.",
        f"Emotional tone: {brief.emotional_tone}.",
        f"Visual hierarchy: {brief.visual_hierarchy}.",
        f"Composition: {'; '.join(brief.composition_guidance) or 'center the teaching action with generous clear space'}.",
        f"Accessibility and clarity: {'; '.join(brief.accessibility_requirements) or 'recognizable at classroom projection distance'}.",
        f"Text policy: {brief.text_policy}.",
        f"Presentation theme {theme.theme_id}@{theme.version}: {theme.visual_mood}; palette {'; '.join(treatment.palette_descriptors)}; anchors {'; '.join(treatment.palette_anchors)}; saturation {treatment.saturation}; contrast {treatment.contrast}; background complexity {treatment.background_complexity}; framing {treatment.framing}.",
        f"Style {profile.id}@{profile.version}: {profile.description}; {'; '.join(profile.requirements)}.",
    ])
    negative_constraints = _unique([
        *profile.forbidden_content,
        *brief.forbidden_content,
        "letters, words, or numbers" if brief.text_policy == "no_text" else "unrequested text",
    ])
    return IllustrationRequest(
        id=request_id,
        concept=brief.concept,
        scene_description=prompt,
        illustration_role=brief.scene_purpose,
        brief_version=brief.version,
        style_profile=profile.id,
        style_profile_version=profile.version,
        theme_id=theme.theme_id,
        theme_version=theme.version,
        aspect_ratio=brief.aspect_ratio,
        width=brief.width,
        height=brief.height,
        negative_constraints=negative_constraints,
        language_context={
            "learner_age_range": brief.learner_age_range,
            "learner_language_level": brief.learner_language_level,
            **brief.language_context,
        },
        source_trace=brief.source_trace,
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))
