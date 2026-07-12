from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from typing import Any

from .models import (
    AudioProviderSettings,
    ImageProviderSettings,
    LLMProviderSettings,
    LessonBlueprint,
    LessonProfile,
    SourceMaterial,
)


class ProviderError(RuntimeError):
    pass


def generate_blueprint_with_llm(
    source: SourceMaterial,
    profile: LessonProfile,
    settings: LLMProviderSettings,
) -> LessonBlueprint | None:
    if not _llm_enabled(settings):
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "You design interactive HTML courseware for international Chinese teachers. "
                "Return only valid JSON matching the requested schema."
            ),
        },
        {"role": "user", "content": _blueprint_prompt(source, profile)},
    ]
    content = _chat_completion(settings, messages)
    data = _extract_json(content)
    if isinstance(data, dict) and "blueprint" in data:
        data = data["blueprint"]
    blueprint = LessonBlueprint.model_validate(data)
    if not blueprint.slides:
        raise ProviderError("LLM returned an empty lesson blueprint")
    return _normalize_blueprint(blueprint, profile)


def generate_openai_image(settings: ImageProviderSettings, prompt: str) -> bytes | None:
    if settings.provider != "openai_images" or not settings.api_key or not prompt.strip():
        return None
    url = _endpoint(settings.endpoint_url, "https://api.openai.com/v1/images/generations")
    payload = {
        "model": settings.model or "gpt-image-1",
        "prompt": prompt,
        "size": "1536x864",
        "n": 1,
    }
    data = _post_json(url, payload, _auth_headers(settings.api_key), timeout=120)
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        return _download_bytes(item["url"], timeout=120)
    raise ProviderError("Image provider returned no image data")


def generate_openai_tts(settings: AudioProviderSettings, text: str) -> bytes | None:
    if settings.provider != "openai_tts" or not settings.api_key or not text.strip():
        return None
    url = _endpoint(settings.endpoint_url, "https://api.openai.com/v1/audio/speech")
    payload = {
        "model": settings.model or "tts-1",
        "voice": settings.voice or "alloy",
        "input": text,
        "response_format": "mp3",
    }
    return _post_bytes(url, payload, _auth_headers(settings.api_key), timeout=120)


def _llm_enabled(settings: LLMProviderSettings) -> bool:
    provider = settings.provider
    if provider in {"ollama", "lm_studio"}:
        return bool(settings.model.strip())
    if provider in {"openai_compatible", "custom"}:
        return bool(settings.base_url.strip() and settings.model.strip() and settings.api_key.strip())
    return False


def _chat_completion(settings: LLMProviderSettings, messages: list[dict[str, str]], json_mode: bool = True) -> str:
    if settings.provider == "ollama":
        base_url = settings.base_url.strip() or "http://127.0.0.1:11434"
        payload: dict[str, Any] = {"model": settings.model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"
        response = _post_json(
            f"{base_url.rstrip('/')}/api/chat",
            payload,
            {},
            timeout=180,
        )
        content = response.get("message", {}).get("content")
    else:
        base_url = settings.base_url.strip()
        if settings.provider == "lm_studio" and not base_url:
            base_url = "http://127.0.0.1:1234/v1"
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "temperature": 0.35,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = _post_json(
            f"{base_url.rstrip('/')}/chat/completions",
            payload,
            _auth_headers(settings.api_key),
            timeout=180,
        )
        choices = response.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("LLM provider returned an empty response")
    return content


def _blueprint_prompt(source: SourceMaterial, profile: LessonProfile) -> str:
    return f"""
Create a complete LessonBlueprint JSON object for HanClassStudio.

Required JSON shape:
{{
  "lesson_title": string,
  "objectives": [string],
  "key_vocabulary": [{{"word": string, "pinyin": string, "meaning": string}}],
  "grammar_points": [string],
  "slides": [
    {{
      "id": number,
      "slide_type": string,
      "layout_variant": string,
      "title": string,
      "content_blocks": [{{"id": string, "block_type": string, "text": string, "scaffolding_text": string}}],
      "components": [
        {{"id": string, "component_type": string, "title": string, "data": object}}
      ],
      "media_requirements": {{
        "image_prompt": string | null,
        "image_key": string | null,
        "media_kind": "raster" | "svg_illustration",
        "svg_style": string | null,
        "audio_text": string | null,
        "audio_key": string | null,
        "video_scene_prompt": null,
        "video_key": null
      }}
    }}
  ]
}}

Use only these interaction component_type values when useful:
VocabularyFlipCard, SentenceDragBuilder, ListenAndChoose, MatchGame.

Lesson profile:
{json.dumps(profile.model_dump(mode="json"), ensure_ascii=False)}

Generation rules:
- Keep the lesson appropriate for {profile.learner_level} learners.
- Use Chinese for core classroom language.
- Use concise {profile.scaffolding_language} scaffolding_text and hints.
- Make 6 to 10 slides unless faithful mode requires fewer.
- Include image prompts for visual slides and audio keys/text for vocabulary or listening items.
- For scene/context illustrations that should be offline-safe vector art, set "media_kind": "svg_illustration" (and optionally "svg_style": "flat"|"mascot"|"diagram"|"scene"); use "raster" only when a photographic image is essential.
- Return JSON only.

Source material excerpt:
{_source_excerpt(source)}
""".strip()


def _source_excerpt(source: SourceMaterial, limit: int = 7000) -> str:
    chunks: list[str] = [f"File: {source.original_filename}", f"Type: {source.source_type}"]
    for page in source.pages:
        chunks.append(f"\nPage {page.page_number}: {page.title}")
        content = page.content_text()
        if content:
            chunks.append(content)
        if page.notes.strip():
            chunks.append(f"Notes: {page.notes}")
    text = "\n".join(chunks)
    return text[:limit]


def _normalize_blueprint(blueprint: LessonBlueprint, profile: LessonProfile) -> LessonBlueprint:
    blueprint.lesson_title = blueprint.lesson_title.strip() or profile.lesson_title
    for index, slide in enumerate(blueprint.slides, start=1):
        slide.id = index
        slide.title = slide.title.strip() or f"第 {index} 页"
        if slide.media_requirements.image_key and not slide.media_requirements.image_prompt:
            slide.media_requirements.image_key = None
        if slide.media_requirements.audio_key and not slide.media_requirements.audio_text:
            slide.media_requirements.audio_key = None
    return blueprint


def _extract_json(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
            return data
        except json.JSONDecodeError:
            continue
    raise ProviderError("LLM response did not contain valid JSON")


def _endpoint(configured: str, default: str) -> str:
    value = configured.strip()
    if not value:
        return default
    if value.rstrip("/").endswith("/v1"):
        if default.endswith("/images/generations"):
            return f"{value.rstrip('/')}/images/generations"
        if default.endswith("/audio/speech"):
            return f"{value.rstrip('/')}/audio/speech"
    return value


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProviderError(str(exc)) from exc


def _post_bytes(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(str(exc)) from exc


def _download_bytes(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(str(exc)) from exc


# ── Illustration scene-spec generation (LLM plans, renderer composes) ──

_SCENE_SPEC_SYSTEM_PROMPT = (
    "You are a SCENE PLANNER for offline teaching illustrations in international "
    "Chinese courseware. You do NOT write SVG. You output a strict JSON "
    "IllustrationSceneSpec that a deterministic renderer assembles from a "
    "registered component library.\n"
    "Return ONLY JSON. Required fields and rules:\n"
    "- concept: the word/phrase being taught.\n"
    "- illustration_level: 'icon' (vocab card, no background, few elements) or "
    "'scene' (classroom projection with one clear visual centre).\n"
    "- scene_type: one of sleep|eat|drink|study|read|write|greet|order|generic.\n"
    "- setting: bedroom|classroom|restaurant|outdoor|neutral.\n"
    "- subjects[]: each has id, role, object_type (MUST be one of the registered "
    "components: PersonStanding, PersonSitting, PersonLying, PersonReading, "
    "PersonWriting, PersonEating, PersonDrinking, TeacherStanding, StudentSitting, "
    "SleepingInBed), "
    "action (sleep|eat|drink|study|read|write|greet|order), relative_scale (0.35-0.65), "
    "position_zone (center|left|right|top_left|top_right|bottom_center|lower_left|lower_right).\n"
    "- For scene_type 'sleep' you MUST use the single composite subject "
    "'SleepingInBed' (it draws bed + pillow + person + blanket with correct contact). "
    "Do NOT emit separate Bed/Pillow/Blanket/PersonLying objects — that pattern is "
    "rejected by the quality gate. SleepingInBed should have relative_scale >= 0.50.\n"
    "- objects[]: each has id, object_type (Bed, Pillow, Blanket, Table, Chair, Book, "
    "Notebook, Cup, Bowl, Chopsticks, SchoolDesk, SimpleWindow, Moon, Sun, Stars, "
    "SleepMarks, SoundWaves, SpeechBubble, MotionLines, AttentionMark), relative_scale, "
    "position_zone. Decorative objects (Moon, Stars, SleepMarks) may set \"decor\": true "
    "so they are auto-hidden on small 1:1 / thumbnail compositions.\n"
    "- text_policy: 'no_text' (vocab default) | 'semantic_symbols_only' (short symbol like "
    "a Z or a <=8-char greeting) | 'short_environment_label'. Do NOT put the word, pinyin, "
    "or translation into the illustration; teaching text belongs to the courseware layer.\n"
    "- style_token: always 'soft_flat_educational_v1'.\n"
    "FORBIDDEN: SVG paths/coordinates, colours/hex, font sizes, DOM ids, slide_id, "
    "component_id, teaching objectives, evidence. Describe WHAT to draw and HOW to compose, "
    "never the low-level SVG."
)

_SCENE_SPEC_USER_TEMPLATE = (
    "Lesson: {lesson}\n"
    "Target language: Chinese; scaffolding: {scaffold}; learner level: {level}.\n"
    "Concept to illustrate: {intent}\n"
    "Output the IllustrationSceneSpec JSON now."
)


def _scene_spec_user_prompt(brief: dict[str, Any]) -> str:
    base = _SCENE_SPEC_USER_TEMPLATE.format(
        lesson=brief.get("lesson_title", ""),
        scaffold=brief.get("scaffold_language", "English"),
        level=brief.get("learner_level", "zero_beginner"),
        intent=brief.get("brief", ""),
    )
    prior = brief.get("prior_errors")
    if prior:
        base += "\nThe previous spec was rejected. Fix exactly:\n- " + "\n- ".join(str(p) for p in prior)
    return base


def generate_scene_spec(settings: LLMProviderSettings, brief: dict[str, Any]) -> dict | None:
    """Ask the LLM to plan a scene as JSON. Returns the dict, or None on failure.

    The caller (svg_illustration.generate_svg_illustration) validates it against
    the SceneSpec schema and renders it via the component library.
    """
    if not _llm_enabled(settings):
        return None
    messages = [
        {"role": "system", "content": _SCENE_SPEC_SYSTEM_PROMPT},
        {"role": "user", "content": _scene_spec_user_prompt(brief)},
    ]
    try:
        content = _chat_completion(settings, messages, json_mode=True)
    except ProviderError:
        return None
    data = _extract_json(content)
    if isinstance(data, dict):
        return data
    return None
