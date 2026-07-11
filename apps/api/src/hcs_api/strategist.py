from __future__ import annotations

from typing import Any

from .components import supported_component_types
from .models import LessonBlueprint, LessonProfile, SourceMaterial


def route_for_generation_mode(generation_mode: str) -> str:
    if generation_mode == "faithful":
        return "faithful-enhance"
    return "main-generation"


def build_spec_lock(project_id: str, source: SourceMaterial, profile: LessonProfile) -> dict[str, Any]:
    route = route_for_generation_mode(profile.generation_mode)
    return {
        "schema": "hanclassstudio.spec_lock.v1",
        "project_id": project_id,
        "route": route,
        "generation_mode": profile.generation_mode,
        "lesson": {
            "title": profile.lesson_title,
            "learner_level": profile.learner_level,
            "target_students": profile.target_students,
            "duration": profile.estimated_duration,
            "lesson_type": profile.lesson_type,
            "subject": profile.subject,
            "scaffolding_language": profile.scaffolding_language,
            "source_type": source.source_type,
            "source_filename": source.original_filename,
        },
        "templates": {
            "brand": None,
            "pedagogy": "task_based_beginner",
            "runtime": "fresh_classroom",
            "courseware": None,
        },
        "runtime": {
            "offline_required": True,
            "keyboard_required": True,
            "language_modes": ["zh", "scaffold", "bilingual"],
            "preview_mode": "iframe",
        },
        "components": {
            "allowed": sorted(supported_component_types(include_experimental=False)),
            "experimental_allowed": False,
        },
        "media": {
            "image_policy": "placeholder-or-provider",
            "svg_illustration_policy": "llm-or-placeholder",
            "svg_offline_safe": True,
            "audio_policy": "placeholder-or-provider",
            "video_policy": "optional",
            "keep_source_images": True,
        },
        "quality": {
            "block_on_missing_files": True,
            "block_on_missing_interaction_answers": True,
            "warn_on_placeholder_media": True,
            "allow_forced_export": True,
            "force_export_label": "demo",
        },
        "project_policy": {
            "backup_before_regenerate": True,
            "write_quality_into_zip": True,
        },
    }


def build_lesson_spec(source: SourceMaterial, profile: LessonProfile, spec_lock: dict[str, Any]) -> str:
    route = spec_lock["route"]
    method = "reimagined" if profile.generation_mode == "reimagined" else profile.generation_mode
    return f"""# Lesson Spec

## Source Summary

- Source file: `{source.original_filename}`
- Source type: `{source.source_type}`
- Parsed pages: {len(source.pages)}

## Audience

- Learner level: {profile.learner_level}
- Target students: {profile.target_students}
- Scaffolding language: {profile.scaffolding_language}

## Teaching Goal

Create an interactive international Chinese lesson titled **{profile.lesson_title}**.

## Generation Route

- Route: `{route}`
- Method: `{method}`

## Lesson Flow

The lesson should introduce goals, warm up learners, present vocabulary and grammar,
provide interactive practice, and end with a short classroom summary.

## Language Scaffolding

Core classroom language stays in Chinese. Scaffolding uses {profile.scaffolding_language}
for meaning, instructions, and feedback.

## Interaction Design

Allowed components come from `courseware/components/registry.json` and are locked in
`specs/spec_lock.json`.

## Media Strategy

Use placeholder media unless configured providers return real image or audio assets.

## Quality Policy

Run the full quality gate before export. Blocked reports prevent normal export.
"""


def build_interaction_plan(blueprint: LessonBlueprint) -> dict[str, Any]:
    interactions = []
    for slide in blueprint.slides:
        for component in slide.components:
            interactions.append(
                {
                    "slide_id": slide.id,
                    "component_id": component.id,
                    "component_type": component.component_type,
                    "requires_answer": component.component_type in {"SentenceDragBuilder", "ListenAndChoose"},
                    "requires_audio": component.component_type in {"ListenAndChoose", "AudioButton"},
                }
            )
    return {"schema": "hanclassstudio.interaction_plan.v1", "interactions": interactions}


def build_media_plan(blueprint: LessonBlueprint) -> dict[str, Any]:
    images = []
    audio = []
    for slide in blueprint.slides:
        media = slide.media_requirements
        if media.image_key and media.image_prompt:
            images.append(
                {
                    "id": media.image_key,
                    "slide_id": slide.id,
                    "prompt": media.image_prompt,
                    "media_kind": media.media_kind,
                    "svg_style": media.svg_style,
                    "aspect_ratio": "16:9",
                    "required": True,
                }
            )
        if media.audio_key and media.audio_text:
            audio.append({"id": media.audio_key, "slide_id": slide.id, "text": media.audio_text, "required": True})
        for component in slide.components:
            if component.component_type == "VocabularyFlipCard":
                for item in component.data.get("items", []):
                    key = item.get("audio_key")
                    text = item.get("audio_text") or item.get("word")
                    if key and text:
                        audio.append({"id": key, "slide_id": slide.id, "text": text, "required": True})
            if component.component_type == "ListenAndChoose":
                key = component.data.get("audio_key")
                text = component.data.get("audio_text")
                if key and text:
                    audio.append({"id": key, "slide_id": slide.id, "text": text, "required": True})
            if component.component_type == "AudioButton":
                key = component.data.get("audio_key")
                text = component.data.get("audio_text") or component.data.get("label")
                if key and text:
                    audio.append({"id": key, "slide_id": slide.id, "text": text, "required": True})
    return {"schema": "hanclassstudio.media_plan.v1", "images": images, "audio": audio, "video": []}
