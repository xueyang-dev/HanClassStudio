"""Shadow adapter from the canonical v2 presentation contract to the legacy shape."""

from __future__ import annotations

from .models import CanonicalPresentationBlueprint, ContentBlock, LessonBlueprint, LessonSlide, PresentationContentPlan, SlideComponent
from .presentation_content import content_item_is_complete


def adapt_canonical_presentation_blueprint(
    blueprint: CanonicalPresentationBlueprint,
    content_plan: PresentationContentPlan | None = None,
) -> LessonBlueprint:
    """Return a legacy-shaped projection without selecting or changing pedagogy.

    Teacher-only units intentionally have no legacy learner slide.  The legacy
    contract has no safe teacher channel, and this adapter is not a renderer.
    """
    learner_units = [unit for unit in blueprint.presentation_units if not unit.teacher_channel_reference]
    content_by_id = {item.id: item for item in (content_plan.content_items if content_plan else [])}
    slides = [
        LessonSlide(
            id=index,
            slide_type="PracticeSlide",
            layout_variant="canonical_shadow",
            title=blueprint.lesson_title,
            content_blocks=[
                ContentBlock(id=f"unit_{index}_content_{content_index}", text=content)
                for content_index, content in enumerate(_display_content(unit, content_by_id.get(unit.content_item_id or "")), start=1)
            ],
            components=_components_for_unit(index, unit, content_by_id.get(unit.content_item_id or ""), content_plan is not None),
        )
        for index, unit in enumerate(learner_units, start=1)
    ]
    vocabulary = list(dict.fromkeys(content for slide in slides for block in slide.content_blocks for content in [block.text]))
    return LessonBlueprint(
        lesson_title=blueprint.lesson_title,
        key_vocabulary=[{"word": item} for item in vocabulary],
        slides=slides,
    )


def _display_content(unit, content_item) -> list[str]:
    if content_item is None:
        return list(unit.learner_facing_content)
    return list(dict.fromkeys(value for value in [content_item.prompt, *content_item.learner_instructions, *content_item.display_items, content_item.learner_safe_hint] if value))


def _components_for_unit(index: int, unit, content_item, content_supplied: bool) -> list[SlideComponent]:
    if content_supplied and (content_item is None or not content_item_is_complete(content_item)):
        return []
    # This is renderer-safe provenance only.  It does not add pedagogical authority.
    trace = {**unit.trace.model_dump(mode="json"), "content_item_id": content_item.id if content_item else ""}
    if content_item and content_item.presentation_mode == "listening_choice":
        audio = next((item for item in content_item.audio_asset_refs if item.availability == "available"), None)
        if audio and content_item.options and content_item.accepted_responses:
            return [SlideComponent(
                id=f"unit_{index}_listen",
                component_type="ListenAndChoose",
                data={
                    "choices": [option.text for option in content_item.options],
                    "answer": content_item.accepted_responses[0].normalized_value,
                    "audio_key": audio.asset_id,
                    "_shadow_trace": trace,
                },
            )]
        return []
    if content_item and content_item.presentation_mode == "matching_response":
        if content_item.matching_pairs:
            return [SlideComponent(
                id=f"unit_{index}_match",
                component_type="MatchGame",
                data={
                    "pairs": [{"left": pair.left, "right": pair.right} for pair in content_item.matching_pairs],
                    "_shadow_trace": trace,
                },
            )]
        return []
    display_items = content_item.display_items if content_item else unit.learner_facing_content
    if content_item and content_item.presentation_mode == "choice_response":
        display_items = [option.text for option in content_item.options]
    return [SlideComponent(
        id=f"unit_{index}_trace",
        component_type="VocabularyFlipCard",
        data={
            "items": [{"word": content} for content in display_items],
            "_shadow_trace": trace,
        },
    )]
