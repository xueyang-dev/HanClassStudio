from __future__ import annotations

import html
import json
import math
import wave
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .asset_review import (
    fallback_candidate, previous_assets, raster_request_fingerprint,
    retain_candidate, reusable_asset,
)
from .models import (
    AssetCandidate, AssetFile, AssetManifest, GeneratedImage, GeneratedImageFailure,
    IllustrationRequest, LessonBlueprint, PresentationTheme, ProviderSettings,
)
from .presentation_theme import (
    THEME_DECISION_PATH, THEME_SELECTION_PATH, persist_theme_decision,
    resolve_presentation_theme,
)
from .providers import ProviderError, _llm_enabled, generate_openai_image, generate_openai_tts
from .raster_provider import (
    ProviderImagePayload, RasterProviderError,
    generate_experimental_raster_image,
    image_dimensions,
)
from .svg_illustration import (
    BRAND_ACCENT, SvgContract, generate_svg_illustration, placeholder_svg,
    build_scene_spec_for_concept, render_scene_spec,
)


def generate_placeholder_media(
    project_root: Path,
    blueprint: LessonBlueprint,
    preserve_media_origin_trace: bool = False,
    theme: PresentationTheme | None = None,
) -> AssetManifest:
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
                path.write_text(render_scene_spec(spec, presentation_theme=theme), encoding="utf-8")
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
    theme: PresentationTheme | None,
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
        svg, _report, spec = generate_svg_illustration(contract, settings.llm, presentation_theme=theme)
        (image_dir / f"{asset.id}.svg").write_text(svg, encoding="utf-8")
        (image_dir / f"{asset.id}.scene.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        asset.path = f"assets/images/{asset.id}.svg"


def generate_configured_media(
    project_root: Path,
    blueprint: LessonBlueprint,
    settings: ProviderSettings,
    preserve_media_origin_trace: bool = False,
    force_regenerate: bool = False,
    strict_provider: bool = False,
) -> AssetManifest:
    previous = previous_assets(project_root)
    raster_keys = {
        slide.media_requirements.image_key
        for slide in blueprint.slides
        if slide.media_requirements.image_key and slide.media_requirements.media_kind != "svg_illustration"
    }
    # Raster art and presentation chrome must resolve the same project theme
    # before provider prompts are created; otherwise the exporter defaults to
    # blue while an unthemed provider is free to choose an unrelated palette.
    theme_requested = (
        bool(raster_keys)
        or (project_root / THEME_SELECTION_PATH).is_file()
        or (project_root / THEME_DECISION_PATH).is_file()
    )
    decision = None
    theme = None
    if theme_requested:
        previous_manifest = AssetManifest(images=list(previous.values()))
        decision = resolve_presentation_theme(
            project_root, lesson_title=blueprint.lesson_title, manifest=previous_manifest,
        )
        theme = decision.theme
    manifest = generate_placeholder_media(project_root, blueprint, preserve_media_origin_trace, theme=theme)
    if decision is not None:
        persist_theme_decision(project_root, decision, manifest)
    spec_lock = _read_spec_lock(project_root)
    media_cfg = (spec_lock or {}).get("media", {})
    svg_policy = media_cfg.get("svg_illustration_policy", "llm-or-placeholder")
    offline_safe = media_cfg.get("svg_offline_safe", True)
    lesson_ctx = (spec_lock or {}).get("lesson", {})

    if settings.image.provider == "codex_image":
        _replace_images_with_codex_bridge(
            project_root, manifest, settings, allowed_keys=raster_keys,
            previous=previous, force_regenerate=force_regenerate, theme=theme,
        )
    else:
        _replace_images_with_provider_assets(
            project_root, manifest, settings, allowed_keys=raster_keys,
            previous=previous, force_regenerate=force_regenerate, theme=theme,
        )

    svg_keys = {
        s.media_requirements.image_key
        for s in blueprint.slides
        if s.media_requirements.image_key and s.media_requirements.media_kind == "svg_illustration"
    }
    if svg_keys and svg_policy != "disabled" and _llm_enabled(settings.llm):
        _upgrade_svg_illustrations(project_root, manifest, blueprint, settings, lesson_ctx, svg_keys, offline_safe, theme)

    _replace_audio_with_provider_assets(project_root, manifest, settings)
    if strict_provider:
        _assert_provider_media_success(manifest, settings, raster_keys)
    if decision is not None:
        persist_theme_decision(project_root, decision, manifest)
    return manifest


def _assert_provider_media_success(
    manifest: AssetManifest,
    settings: ProviderSettings,
    raster_keys: set[str],
) -> None:
    """Reject provider failures on production routes instead of hiding them.

    The non-strict media helper remains useful for diagnostic/unit fixtures that
    intentionally inspect a retained SVG fallback.  Production workflow calls
    pass ``strict_provider=True`` so a selected external provider cannot report
    success while leaving a placeholder asset behind.
    """

    if settings.image.provider != "placeholder":
        failed = [
            asset for asset in manifest.images
            if asset.id in raster_keys and (
                asset.fallback_used or asset.generation_failure or asset.path.endswith(".svg")
            )
        ]
        if failed:
            reason = failed[0].fallback_reason or (
                failed[0].generation_failure.message if failed[0].generation_failure else "Provider returned no usable image"
            )
            raise ProviderError(f"Image provider {settings.image.provider} did not produce a usable asset: {reason}")


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
    request = IllustrationRequest(
        id="compatibility-raster-request",
        concept=prompt,
        scene_description=prompt,
        aspect_ratio=aspect_ratio,
        source_trace=["generate_raster_image compatibility facade"],
    )
    try:
        return generate_experimental_raster_image(settings.image, request).image_bytes
    except RasterProviderError as exc:
        # The experimental adapter alone owns provider selection.  Retain the
        # legacy backend only when no experimental provider was selected; an
        # experimental failure must never silently fall through to a billable
        # legacy provider.
        if exc.kind != "disabled":
            return None
    return generate_openai_image(settings.image, prompt)


def _replace_images_with_provider_assets(
    project_root: Path,
    manifest: AssetManifest,
    settings: ProviderSettings,
    allowed_keys: set[str] | None = None,
    previous: dict[str, AssetFile] | None = None,
    force_regenerate: bool = False,
    theme: PresentationTheme | None = None,
) -> None:
    if settings.image.provider == "placeholder":
        return
    image_dir = project_root / "assets" / "images"
    diagnostic_records: list[dict] = []
    for index, asset in enumerate(manifest.images):
        if allowed_keys is not None and asset.id not in allowed_keys:
            continue
        request = IllustrationRequest(
            id=asset.id,
            concept=asset.prompt,
            scene_description=_theme_aware_prompt(asset.prompt, theme),
            aspect_ratio="16:9",
            style_profile=theme.image_treatment.illustration_style if theme else "legacy_unspecified",
            style_profile_version="1" if theme else "0",
            theme_id=theme.theme_id if theme else None,
            theme_version=theme.version if theme else None,
            source_trace=[f"legacy_media_requirement:{asset.id}"],
        )
        fingerprint = raster_request_fingerprint(request, settings.image)
        prior = (previous or {}).get(asset.id)
        if not force_regenerate:
            cached = reusable_asset(project_root, prior, fingerprint)
            if cached:
                manifest.images[index] = cached
                diagnostic_records.append(_raster_diagnostic_record(cached, request, "reused"))
                continue
        if prior:
            asset.candidates = [item.model_copy(deep=True) for item in prior.candidates]
            asset.review_history = [item.model_copy(deep=True) for item in prior.review_history]
        asset.request_fingerprint = fingerprint
        try:
            payload = generate_experimental_raster_image(settings.image, request)
        except RasterProviderError as exc:
            if exc.kind != "disabled":
                _record_raster_fallback(project_root, asset, request, settings, exc)
                diagnostic_records.append(_raster_diagnostic_record(asset, request, "fallback"))
                continue
        else:
            try:
                _persist_raster_asset(image_dir, asset, request, settings, payload)
            except RasterProviderError as exc:
                _record_raster_fallback(project_root, asset, request, settings, exc)
                diagnostic_records.append(_raster_diagnostic_record(asset, request, "fallback"))
                continue
            diagnostic_records.append(_raster_diagnostic_record(asset, request, "generated"))
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

    if diagnostic_records:
        diagnostics_path = project_root / "diagnostics" / "raster_provider_generation.json"
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_path.write_text(json.dumps({
            "schema": "hanclassstudio.raster_provider_generation.v1",
            "experimental": True,
            "records": diagnostic_records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")


def _replace_images_with_codex_bridge(
    project_root: Path,
    manifest: AssetManifest,
    settings: ProviderSettings,
    allowed_keys: set[str],
    previous: dict[str, AssetFile],
    force_regenerate: bool,
    theme: PresentationTheme | None,
) -> None:
    from .codex_bridge import CodexBridgeActionRequired, completed_image, request_job

    image_dir = project_root / "assets" / "images"
    pending: list[str] = []
    for index, asset in enumerate(manifest.images):
        if asset.id not in allowed_keys:
            continue
        request = IllustrationRequest(
            id=asset.id,
            concept=asset.prompt,
            scene_description=_theme_aware_prompt(asset.prompt, theme),
            aspect_ratio="16:9",
            style_profile=theme.image_treatment.illustration_style if theme else "legacy_unspecified",
            style_profile_version="1" if theme else "0",
            theme_id=theme.theme_id if theme else None,
            theme_version=theme.version if theme else None,
            source_trace=[f"legacy_media_requirement:{asset.id}"],
        )
        fingerprint = raster_request_fingerprint(request, settings.image)
        prior = previous.get(asset.id)
        if not force_regenerate:
            cached = reusable_asset(project_root, prior, fingerprint)
            if cached:
                manifest.images[index] = cached
                continue
        if prior:
            asset.candidates = [item.model_copy(deep=True) for item in prior.candidates]
            asset.review_history = [item.model_copy(deep=True) for item in prior.review_history]
        asset.request_fingerprint = fingerprint
        job = request_job(project_root.name, "image", "image", {
            "asset_id": asset.id,
            "illustration_request": request.model_dump(mode="json"),
            "accepted_mime_types": ["image/png", "image/jpeg", "image/webp"],
            "generation_attempt": sum(item.source == "generated" for item in asset.candidates) if force_regenerate else 0,
        })
        result = completed_image(job)
        if result is None:
            pending.append(job.job_id)
            continue
        content, mime_type = result
        payload = ProviderImagePayload(
            image_bytes=content,
            mime_type=mime_type,
            model=settings.image.model or "codex-image",
            prompt=request.scene_description,
            revised_prompt=None,
            seed=None,
            retry_count=0,
            provider_request_id=job.job_id,
            warnings=[],
        )
        _persist_raster_asset(image_dir, asset, request, settings, payload)
    if pending:
        raise CodexBridgeActionRequired(pending)


def _extension_for_mime(mime_type: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]


def _persist_raster_asset(image_dir, asset, request, settings, payload) -> None:
    content_hash = sha256(payload.image_bytes).hexdigest()
    extension = _extension_for_mime(payload.mime_type)
    filename = f"{asset.id}{extension}"
    local_path = image_dir / filename
    if local_path.exists() and sha256(local_path.read_bytes()).hexdigest() != content_hash:
        filename = f"{asset.id}-{content_hash[:12]}{extension}"
        local_path = image_dir / filename
    try:
        _write_raster_bytes(local_path, payload.image_bytes)
    except OSError as exc:
        local_path.unlink(missing_ok=True)
        raise RasterProviderError(
            "local_write", f"Could not persist raster asset: {exc}",
            stage="local_persist", category="local_write",
            provider_request_id=payload.provider_request_id,
        ) from exc

    relative_path = f"assets/images/{filename}"
    width, height = image_dimensions(payload.image_bytes, payload.mime_type)
    try:
        generation = GeneratedImage(
            provider=settings.image.provider,
            model=payload.model,
            local_path=relative_path,
            mime_type=payload.mime_type,
            width=width,
            height=height,
            prompt=payload.prompt,
            revised_prompt=payload.revised_prompt,
            brief_version=request.brief_version,
            style_profile=request.style_profile,
            style_profile_version=request.style_profile_version,
            theme_id=request.theme_id,
            theme_version=request.theme_version,
            seed=payload.seed,
            retry_count=payload.retry_count,
            content_hash=content_hash,
            generated_at=datetime.now(timezone.utc).isoformat(),
            provider_request_id=payload.provider_request_id,
            source_trace=request.source_trace,
            warnings=payload.warnings,
        )
    except Exception as exc:  # pragma: no cover - defensive manifest boundary
        local_path.unlink(missing_ok=True)
        raise RasterProviderError(
            "manifest", f"Could not record raster manifest provenance: {exc}",
            stage="manifest_record", category="unknown",
            provider_request_id=payload.provider_request_id,
        ) from exc

    asset.path = relative_path
    asset.mime_type = payload.mime_type
    asset.content_hash = content_hash
    asset.fallback_used = False
    asset.fallback_reason = None
    asset.generation = generation
    asset.generation_failure = None
    asset.presentation_theme_id = request.theme_id
    asset.presentation_theme_version = request.theme_version
    asset.review_state = "pending_review"
    generated = AssetCandidate(
        id=f"generated-{content_hash[:12]}", path=relative_path,
        mime_type=payload.mime_type, content_hash=content_hash,
        source="generated", generation=generation,
    )
    retain_candidate(asset, generated)
    fallback = fallback_candidate(image_dir.parent.parent, asset)
    if fallback:
        retain_candidate(asset, fallback)
    asset.selected_candidate_id = generated.id


def _write_raster_bytes(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _record_raster_fallback(project_root, asset, request, settings, exc: RasterProviderError) -> None:
    # The deterministic local SVG was created before the provider pass.
    asset.fallback_used = True
    asset.fallback_reason = f"{exc.category}: {exc}"
    asset.mime_type = "image/svg+xml"
    asset.generation = None
    asset.generation_failure = GeneratedImageFailure(
        provider=settings.image.provider,
        model=settings.image.model,
        stage=exc.stage,
        category=exc.category,
        message=str(exc),
        status_code=exc.status_code,
        retry_count=exc.retry_count,
        provider_request_id=exc.provider_request_id,
        source_trace=request.source_trace,
    )
    asset.review_state = "pending_review"
    fallback = fallback_candidate(project_root, asset)
    if fallback:
        retain_candidate(asset, fallback)
        asset.selected_candidate_id = fallback.id
        asset.content_hash = fallback.content_hash


def _theme_aware_prompt(prompt: str, theme: PresentationTheme | None) -> str:
    if theme is None:
        return prompt
    treatment = theme.image_treatment
    return " ".join([
        prompt.strip(),
        f"Presentation theme {theme.theme_id}@{theme.version}: {theme.visual_mood}.",
        "Color authority: the presentation theme below overrides any conflicting palette or color-temperature wording earlier in the brief; make its first palette descriptors and anchors dominant across the environment, wardrobe accents, and props while keeping skin tones natural.",
        f"Palette guidance: {', '.join(treatment.palette_descriptors)}; anchors {', '.join(treatment.palette_anchors)}.",
        f"Use {treatment.saturation} saturation, {treatment.contrast} contrast, {treatment.background_complexity} background complexity, and {treatment.framing} framing.",
        "Do not embed words, letters, captions, logos, or watermarks.",
    ])


def _raster_diagnostic_record(asset: AssetFile, request: IllustrationRequest, status: str) -> dict:
    return {
        "request": request.model_dump(mode="json"),
        "status": status,
        "asset_path": asset.path,
        "mime_type": asset.mime_type,
        "content_hash": asset.content_hash,
        "fallback_used": asset.fallback_used,
        "fallback_reason": asset.fallback_reason,
        "generation": asset.generation.model_dump(mode="json") if asset.generation else None,
        "generation_failure": asset.generation_failure.model_dump(mode="json") if asset.generation_failure else None,
    }


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
        except ProviderError as exc:
            raise ProviderError(f"TTS provider {settings.audio.provider} failed: {exc}") from exc
        if not audio_bytes:
            raise ProviderError(f"TTS provider {settings.audio.provider} returned no audio")
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
