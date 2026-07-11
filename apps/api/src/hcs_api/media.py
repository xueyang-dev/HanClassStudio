from __future__ import annotations

import html
import json
import math
import wave
from pathlib import Path

from .models import AssetFile, AssetManifest, LessonBlueprint, ProviderSettings
from .providers import ProviderError, _llm_enabled, generate_openai_image, generate_openai_tts
from .svg_illustration import (
    BRAND_ACCENT, SvgContract, generate_svg_illustration, placeholder_svg,
    build_scene_spec_for_concept, render_scene_spec,
)


def generate_placeholder_media(project_root: Path, blueprint: LessonBlueprint, preserve_media_origin_trace: bool = False) -> AssetManifest:
    images: list[AssetFile] = []
    audio: list[AssetFile] = []
    image_dir = project_root / "assets" / "images"
    audio_dir = project_root / "assets" / "audio"
    image_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    seen_audio: set[str] = set()
    for slide in blueprint.slides:
        if slide.media_requirements.image_key and slide.media_requirements.image_prompt:
            filename = f"{slide.media_requirements.image_key}.svg"
            path = image_dir / filename
            if slide.media_requirements.media_kind == "svg_illustration":
                spec = build_scene_spec_for_concept(
                    slide.media_requirements.image_prompt or "", blueprint.lesson_title
                )
                path.write_text(render_scene_spec(spec), encoding="utf-8")
                path.with_suffix(".scene.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            else:
                path.write_text(_placeholder_svg(slide.media_requirements.image_prompt, slide.id), encoding="utf-8")
            images.append(
                AssetFile(
                    id=slide.media_requirements.image_key,
                    kind="image",
                    path=f"assets/images/{filename}",
                    prompt=slide.media_requirements.image_prompt,
                    origin_media_requirement_ids=[slide.media_requirements.image_key] if preserve_media_origin_trace else [],
                )
            )
        if slide.media_requirements.audio_key and slide.media_requirements.audio_text:
            _add_audio(audio, audio_dir, slide.media_requirements.audio_key, slide.media_requirements.audio_text, seen_audio, slide.media_requirements.audio_key if preserve_media_origin_trace else None)

        for component in slide.components:
            data = component.data
            if component.component_type == "VocabularyFlipCard":
                for item in data.get("items", []):
                    key = item.get("audio_key")
                    text = item.get("audio_text") or item.get("word")
                    if key and text:
                        _add_audio(audio, audio_dir, key, text, seen_audio, key if preserve_media_origin_trace else None)
            if component.component_type == "ListenAndChoose":
                key = data.get("audio_key")
                text = data.get("audio_text")
                if key and text:
                    _add_audio(audio, audio_dir, key, text, seen_audio, key if preserve_media_origin_trace else None)
            if component.component_type == "AudioButton":
                key = data.get("audio_key")
                text = data.get("audio_text") or data.get("label")
                if key and text:
                    _add_audio(audio, audio_dir, key, text, seen_audio, key if preserve_media_origin_trace else None)

    return AssetManifest(images=images, audio=audio)


def _read_spec_lock(project_root: Path) -> dict | None:
    spec_path = project_root / "specs" / "spec_lock.json"
    if spec_path.exists():
        try:
            return json.loads(spec_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _upgrade_svg_illustrations(
    project_root: Path,
    manifest: AssetManifest,
    blueprint: LessonBlueprint,
    settings: ProviderSettings,
    lesson_ctx: dict,
    svg_keys: set[str],
    offline_safe: bool,
) -> None:
    """Replace placeholder SVGs with locked-contract LLM illustrations where enabled."""
    image_dir = project_root / "assets" / "images"
    slide_by_key = {
        s.media_requirements.image_key: s
        for s in blueprint.slides
        if s.media_requirements.image_key
    }
    for asset in manifest.images:
        if asset.id not in svg_keys:
            continue
        slide = slide_by_key.get(asset.id)
        if slide is None:
            continue
        contract = SvgContract(
            asset_id=asset.id,
            lesson_title=blueprint.lesson_title,
            target_language="Chinese",
            scaffold_language=lesson_ctx.get("scaffolding_language", "English"),
            learner_level=lesson_ctx.get("learner_level", "zero_beginner"),
            slide_id=slide.id,
            brief=asset.prompt or slide.media_requirements.image_prompt or "",
            style=slide.media_requirements.svg_style or "flat",
            offline_safe=offline_safe,
        )
        svg, _report, spec = generate_svg_illustration(contract, settings.llm)
        (image_dir / f"{asset.id}.svg").write_text(svg, encoding="utf-8")
        (image_dir / f"{asset.id}.scene.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        asset.path = f"assets/images/{asset.id}.svg"


def generate_configured_media(
    project_root: Path,
    blueprint: LessonBlueprint,
    settings: ProviderSettings,
    preserve_media_origin_trace: bool = False,
) -> AssetManifest:
    manifest = generate_placeholder_media(project_root, blueprint, preserve_media_origin_trace)
    spec_lock = _read_spec_lock(project_root)
    media_cfg = (spec_lock or {}).get("media", {})
    svg_policy = media_cfg.get("svg_illustration_policy", "llm-or-placeholder")
    offline_safe = media_cfg.get("svg_offline_safe", True)
    lesson_ctx = (spec_lock or {}).get("lesson", {})

    raster_keys = {
        s.media_requirements.image_key
        for s in blueprint.slides
        if s.media_requirements.image_key and s.media_requirements.media_kind != "svg_illustration"
    }
    _replace_images_with_provider_assets(project_root, manifest, settings, allowed_keys=raster_keys)

    svg_keys = {
        s.media_requirements.image_key
        for s in blueprint.slides
        if s.media_requirements.image_key and s.media_requirements.media_kind == "svg_illustration"
    }
    if svg_keys and svg_policy != "disabled" and _llm_enabled(settings.llm):
        _upgrade_svg_illustrations(project_root, manifest, blueprint, settings, lesson_ctx, svg_keys, offline_safe)

    _replace_audio_with_provider_assets(project_root, manifest, settings)
    return manifest


def generate_raster_image(settings: ProviderSettings, prompt: str, aspect_ratio: str = "16:9") -> bytes | None:
    """Raster illustration provider seam.

    Single integration point for the *raster* media lane (character poses,
    scene/context art, classroom hero images). The deterministic SVG lane is
    handled separately by the SVG illustration pipeline and never reaches here.

    Currently backed by the OpenAI-compatible image API. To add a low-cost
    raster provider, implement the backend in ``providers.py`` (mirror
    ``generate_openai_image``) and point this function at it — the rest of the
    pipeline is untouched. Returns PNG bytes, or ``None`` to fall back to a
    deterministic placeholder.

    Args:
        settings: full provider settings (the image backend is ``settings.image``).
        prompt: the illustration prompt from ``MediaRequirements.image_prompt``.
        aspect_ratio: requested aspect (e.g. ``"16:9"`` / ``"1:1"``); honour it
            when the chosen backend supports it.
    """
    return generate_openai_image(settings.image, prompt)


def _replace_images_with_provider_assets(
    project_root: Path,
    manifest: AssetManifest,
    settings: ProviderSettings,
    allowed_keys: set[str] | None = None,
) -> None:
    if settings.image.provider == "placeholder":
        return
    image_dir = project_root / "assets" / "images"
    for asset in manifest.images:
        if allowed_keys is not None and asset.id not in allowed_keys:
            continue
        try:
            image_bytes = generate_raster_image(settings, asset.prompt)
        except ProviderError:
            image_bytes = None
        if not image_bytes:
            continue
        filename = f"{asset.id}.png"
        (image_dir / filename).write_bytes(image_bytes)
        asset.path = f"assets/images/{filename}"


def _replace_audio_with_provider_assets(
    project_root: Path,
    manifest: AssetManifest,
    settings: ProviderSettings,
) -> None:
    if settings.audio.provider == "placeholder":
        return
    audio_dir = project_root / "assets" / "audio"
    for asset in manifest.audio:
        try:
            audio_bytes = generate_openai_tts(settings.audio, asset.text)
        except ProviderError:
            audio_bytes = None
        if not audio_bytes:
            continue
        filename = f"{asset.id}.mp3"
        (audio_dir / filename).write_bytes(audio_bytes)
        asset.path = f"assets/audio/{filename}"


def _add_audio(audio: list[AssetFile], audio_dir: Path, key: str, text: str, seen: set[str], origin_requirement_id: str | None) -> None:
    if key in seen:
        existing = next(asset for asset in audio if asset.id == key)
        if origin_requirement_id and origin_requirement_id not in existing.origin_media_requirement_ids:
            existing.origin_media_requirement_ids.append(origin_requirement_id)
        return
    seen.add(key)
    filename = f"{key}.wav"
    path = audio_dir / filename
    _write_tone(path)
    audio.append(AssetFile(
        id=key, kind="audio", path=f"assets/audio/{filename}", text=text,
        origin_media_requirement_ids=[origin_requirement_id] if origin_requirement_id else [],
    ))


def _write_tone(path: Path) -> None:
    sample_rate = 16000
    duration = 0.45
    frequency = 660
    frames = int(sample_rate * duration)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(frames):
            amplitude = int(9000 * math.sin(2 * math.pi * frequency * i / sample_rate))
            wav.writeframesraw(amplitude.to_bytes(2, byteorder="little", signed=True))


def _placeholder_svg(prompt: str, slide_id: int) -> str:
    safe_prompt = html.escape(prompt[:120])
    hue = (slide_id * 41) % 360
    accent = f"hsl({hue}, 76%, 52%)"
    secondary = f"hsl({(hue + 120) % 360}, 62%, 60%)"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" role="img" aria-label="{safe_prompt}">
  <rect width="1200" height="675" fill="#F8FAF7"/>
  <circle cx="260" cy="210" r="132" fill="{accent}" opacity="0.22"/>
  <circle cx="930" cy="455" r="168" fill="{secondary}" opacity="0.24"/>
  <path d="M190 505 C330 360 440 430 560 332 C684 232 792 258 1010 140" fill="none" stroke="{accent}" stroke-width="24" stroke-linecap="round" opacity="0.82"/>
  <rect x="252" y="188" width="504" height="324" rx="8" fill="#FFFFFF" stroke="#DCE8E2" stroke-width="4"/>
  <rect x="312" y="248" width="168" height="24" rx="8" fill="{accent}" opacity="0.38"/>
  <rect x="312" y="306" width="356" height="18" rx="8" fill="#6F8D88" opacity="0.32"/>
  <rect x="312" y="356" width="292" height="18" rx="8" fill="#6F8D88" opacity="0.24"/>
  <rect x="800" y="220" width="148" height="148" rx="8" fill="{secondary}" opacity="0.48"/>
  <path d="M820 366 L874 300 L916 342 L948 306 L948 366 Z" fill="#FFFFFF" opacity="0.82"/>
  <circle cx="846" cy="260" r="20" fill="#FFFFFF" opacity="0.82"/>
</svg>"""
