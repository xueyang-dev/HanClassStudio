from __future__ import annotations

import html
import math
import wave
from pathlib import Path

from .models import AssetFile, AssetManifest, LessonBlueprint, ProviderSettings
from .providers import ProviderError, generate_openai_image, generate_openai_tts


def generate_placeholder_media(project_root: Path, blueprint: LessonBlueprint) -> AssetManifest:
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
            path.write_text(_placeholder_svg(slide.media_requirements.image_prompt, slide.id), encoding="utf-8")
            images.append(
                AssetFile(
                    id=slide.media_requirements.image_key,
                    kind="image",
                    path=f"assets/images/{filename}",
                    prompt=slide.media_requirements.image_prompt,
                )
            )
        if slide.media_requirements.audio_key and slide.media_requirements.audio_text:
            _add_audio(audio, audio_dir, slide.media_requirements.audio_key, slide.media_requirements.audio_text, seen_audio)

        for component in slide.components:
            data = component.data
            if component.component_type == "VocabularyFlipCard":
                for item in data.get("items", []):
                    key = item.get("audio_key")
                    text = item.get("audio_text") or item.get("word")
                    if key and text:
                        _add_audio(audio, audio_dir, key, text, seen_audio)
            if component.component_type == "ListenAndChoose":
                key = data.get("audio_key")
                text = data.get("audio_text")
                if key and text:
                    _add_audio(audio, audio_dir, key, text, seen_audio)
            if component.component_type == "AudioButton":
                key = data.get("audio_key")
                text = data.get("audio_text") or data.get("label")
                if key and text:
                    _add_audio(audio, audio_dir, key, text, seen_audio)

    return AssetManifest(images=images, audio=audio)


def generate_configured_media(
    project_root: Path,
    blueprint: LessonBlueprint,
    settings: ProviderSettings,
) -> AssetManifest:
    manifest = generate_placeholder_media(project_root, blueprint)
    _replace_images_with_provider_assets(project_root, manifest, settings)
    _replace_audio_with_provider_assets(project_root, manifest, settings)
    return manifest


def _replace_images_with_provider_assets(
    project_root: Path,
    manifest: AssetManifest,
    settings: ProviderSettings,
) -> None:
    if settings.image.provider == "placeholder":
        return
    image_dir = project_root / "assets" / "images"
    for asset in manifest.images:
        try:
            image_bytes = generate_openai_image(settings.image, asset.prompt)
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


def _add_audio(audio: list[AssetFile], audio_dir: Path, key: str, text: str, seen: set[str]) -> None:
    if key in seen:
        return
    seen.add(key)
    filename = f"{key}.wav"
    path = audio_dir / filename
    _write_tone(path)
    audio.append(AssetFile(id=key, kind="audio", path=f"assets/audio/{filename}", text=text))


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
