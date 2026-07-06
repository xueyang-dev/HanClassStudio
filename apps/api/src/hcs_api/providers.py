from __future__ import annotations

import base64
import json
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


def _chat_completion(settings: LLMProviderSettings, messages: list[dict[str, str]]) -> str:
    if settings.provider == "ollama":
        base_url = settings.base_url.strip() or "http://127.0.0.1:11434"
        response = _post_json(
            f"{base_url.rstrip('/')}/api/chat",
            {"model": settings.model, "messages": messages, "format": "json", "stream": False},
            {},
            timeout=180,
        )
        content = response.get("message", {}).get("content")
    else:
        base_url = settings.base_url.strip()
        if settings.provider == "lm_studio" and not base_url:
            base_url = "http://127.0.0.1:1234/v1"
        response = _post_json(
            f"{base_url.rstrip('/')}/chat/completions",
            {
                "model": settings.model,
                "messages": messages,
                "temperature": 0.35,
                "response_format": {"type": "json_object"},
            },
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
- Return JSON only.

Source material excerpt:
{_source_excerpt(source)}
""".strip()


def _source_excerpt(source: SourceMaterial, limit: int = 7000) -> str:
    chunks: list[str] = [f"File: {source.original_filename}", f"Type: {source.source_type}"]
    for page in source.pages:
        chunks.append(f"\nPage {page.page_number}: {page.title}")
        chunks.extend(block.text for block in page.text_blocks if block.text.strip())
        if page.notes.strip():
            chunks.append(f"Notes: {page.notes}")
        if page.ocr_text.strip():
            chunks.append(f"OCR: {page.ocr_text}")
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
