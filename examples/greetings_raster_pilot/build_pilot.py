"""Build the zero-beginner greetings pilot through the existing project pipeline."""

from __future__ import annotations

import argparse
import json
import os
import time
import zipfile
from pathlib import Path

from pptx import Presentation

from hcs_api import storage
from hcs_api.asset_review import render_review_page
from hcs_api.media import generate_configured_media
from hcs_api.models import (
    AssetManifest, ContentBlock, ImageProviderSettings, LessonBlueprint, LessonProfile, LessonSlide,
    MediaRequirements, ProviderSettings, QualityReport, SlideComponent, SourceMaterial,
    SourcePage, TextBlock,
)
from hcs_api.pipeline import run_full_pipeline, write_blueprint_artifacts
from hcs_api.presentation_theme import presentation_theme_for_project
from hcs_api.pptx_exporter import export_editable_pptx
from hcs_api.quality import check_quality
from hcs_api.renderer import render_lesson


PROJECT_ID = "greetings_raster_pilot"
RASTER_KEYS = {"teacher_greeting", "polite_contrast", "morning_greeting", "goodbye_scene"}


def build_pilot(real_raster: bool = False) -> Path:
    root = storage.ensure_project(PROJECT_ID)
    manifest_path = root / "assets" / "data" / "asset_manifest.json"
    previous_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
    prior_assets = AssetManifest.model_validate_json(previous_manifest) if previous_manifest else None
    source = _source()
    profile = _profile()
    storage.write_model(PROJECT_ID, "source_material.json", source)
    storage.write_model(PROJECT_ID, "lesson_profile.json", profile)

    # Produce the authoritative learning/evidence/activity/presentation artifacts first.
    run_full_pipeline(
        PROJECT_ID, root, ProviderSettings(), force_export=True,
        enable_presentation_parity_shadow=True,
        enable_presentation_adapter_assessment=True,
        enable_presentation_content_shadow=True,
        enable_presentation_asset_reconciliation_shadow=True,
        enable_presentation_media_request_shadow=True,
        enable_presentation_media_projection_shadow=True,
    )
    # The kernel pass uses placeholder settings. Restore any reviewed/generated
    # manifest before the real media pass so a repeat build can reuse local assets.
    if previous_manifest is not None:
        manifest_path.write_bytes(previous_manifest)
    # Keep the user-reviewed raster visuals and choose the closest
    # master-derived presentation theme from their local palette.  No provider
    # call is needed for this path.
    storage.write_json(PROJECT_ID, "presentation/theme_selection.json", {
        "decision_source": "inherited_from_existing_assets",
    })

    blueprint = _blueprint()
    write_blueprint_artifacts(PROJECT_ID, blueprint)
    settings = _provider_settings(real_raster)
    started = time.perf_counter()
    manifest = generate_configured_media(root, blueprint, settings, preserve_media_origin_trace=True)
    if prior_assets is not None:
        _reuse_pilot_rasters(root, manifest, prior_assets)
    generation_ms = round((time.perf_counter() - started) * 1000, 1)
    storage.write_model(PROJECT_ID, "asset_manifest.json", manifest)

    render_lesson(root, profile, blueprint, manifest, QualityReport(state="pass"))
    quality = check_quality(root, blueprint, manifest)
    storage.write_model(PROJECT_ID, "quality_report.json", quality)
    html_path = render_lesson(root, profile, blueprint, manifest, quality)
    pptx_path = export_editable_pptx(PROJECT_ID, force=True)
    zip_path = storage.zip_output(PROJECT_ID, force=True)

    raster_assets = [asset for asset in manifest.images if asset.id in RASTER_KEYS]
    report = _pilot_report(root, raster_assets, generation_ms, html_path, pptx_path, zip_path)
    diagnostics = root / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    (diagnostics / "pilot_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    review_html = render_review_page(PROJECT_ID, manifest).replace(
        f"/runtime/projects/{PROJECT_ID}/", "../../",
    )
    review_dir = diagnostics / "teacher_media_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "index.html").write_text(review_html, encoding="utf-8")
    theme = presentation_theme_for_project(root)
    theme_decision = root / "presentation" / "presentation_theme.json"
    (diagnostics / "theme_decision_report.json").write_text(json.dumps({
        "schema": "hanclassstudio.greetings_raster_theme_review.v1",
        "selected_theme": theme.model_dump(mode="json"),
        "decision_source": "inherited_from_existing_assets",
        "decision": json.loads(theme_decision.read_text(encoding="utf-8")) if theme_decision.exists() else None,
        "reused_raster_hashes": {asset.id: asset.content_hash for asset in manifest.images if asset.id in RASTER_KEYS},
        "human_review_required": True,
        "notes": ["Theme selection analyses local accepted/generated raster pixels only.", "No automatic aesthetic verdict is made."],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def _reuse_pilot_rasters(root: Path, manifest: AssetManifest, prior: AssetManifest) -> None:
    """Reuse valid local candidates rather than re-requesting reviewed raster art."""
    from hashlib import sha256

    prior_by_id = {asset.id: asset for asset in prior.images}
    for index, asset in enumerate(manifest.images):
        previous = prior_by_id.get(asset.id)
        if asset.id not in RASTER_KEYS or previous is None or not previous.path.lower().endswith(".png"):
            continue
        path = root / previous.path
        if not path.is_file() or not previous.content_hash:
            continue
        if sha256(path.read_bytes()).hexdigest() != previous.content_hash:
            continue
        reused = previous.model_copy(deep=True)
        reused.presentation_theme_id = manifest.presentation_theme_id
        reused.presentation_theme_version = manifest.presentation_theme_version
        if reused.generation:
            reused.generation.theme_id = manifest.presentation_theme_id
            reused.generation.theme_version = manifest.presentation_theme_version
        manifest.images[index] = reused


def _provider_settings(real_raster: bool) -> ProviderSettings:
    if not real_raster:
        return ProviderSettings()
    if not os.environ.get("HCS_EXPERIMENTAL_RASTER_API_KEY", "").strip():
        raise RuntimeError("HCS_EXPERIMENTAL_RASTER_API_KEY is required for --real-raster")
    return ProviderSettings(image=ImageProviderSettings(
        provider="experimental_openai_images",
        endpoint_url=os.environ.get(
            "HCS_EXPERIMENTAL_RASTER_ENDPOINT", "https://api.siliconflow.cn/v1/images/generations",
        ),
        model=os.environ.get("HCS_EXPERIMENTAL_RASTER_MODEL", "Qwen/Qwen-Image"),
    ))


def _source() -> SourceMaterial:
    return SourceMaterial(
        source_type="unknown", original_filename="greetings_pilot_source.txt",
        pages=[SourcePage(page_number=1, title="Greetings and polite address", text_blocks=[TextBlock(
            id="targets", kind="body",
            text="你好 nǐ hǎo hello\n您好 nín hǎo polite hello\n老师好 lǎoshī hǎo hello teacher\n早上好 zǎoshang hǎo good morning\n再见 zàijiàn goodbye",
        )])],
    )


def _profile() -> LessonProfile:
    return LessonProfile(
        lesson_title="问候与礼貌称呼", learner_level="zero_beginner",
        target_students="English-speaking zero beginners",
        scaffolding_language="English", lesson_type="New lesson",
        generation_mode="guided_redesign", estimated_duration="20 minutes",
    )


def _scene(key: str, action: str) -> MediaRequirements:
    prompt = (
        f"{action}. One unmistakable central action for English-speaking zero-beginner Chinese learners; "
        "natural human anatomy and poses; 16:9 composition; no embedded words, letters, captions, watermark, "
        "logo, poster, UI, or infographic layout."
    )
    return MediaRequirements(image_key=key, image_prompt=prompt, media_kind="raster", text_policy="no_text")


def _blueprint() -> LessonBlueprint:
    vocabulary = [
        {"word": "你好", "pinyin": "nǐ hǎo", "meaning": "hello"},
        {"word": "您好", "pinyin": "nín hǎo", "meaning": "hello (polite)"},
        {"word": "老师好", "pinyin": "lǎoshī hǎo", "meaning": "hello, teacher"},
        {"word": "早上好", "pinyin": "zǎoshang hǎo", "meaning": "good morning"},
        {"word": "再见", "pinyin": "zàijiàn", "meaning": "goodbye"},
    ]
    return LessonBlueprint(
        lesson_title="问候与礼貌称呼",
        objectives=["Recognize five common greetings", "Choose a polite greeting for a teacher", "Match greetings with meanings"],
        key_vocabulary=vocabulary,
        slides=[
            LessonSlide(id=1, slide_type="CoverSlide", layout_variant="hero", title="老师好！", content_blocks=[
                ContentBlock(id="cover", text="老师好", scaffolding_text="lǎoshī hǎo · Hello, teacher"),
            ], media_requirements=_scene("teacher_greeting", "One school-age student politely greets one teacher at a bright classroom doorway")),
            LessonSlide(id=2, slide_type="VocabularySlide", layout_variant="cards", title="五个问候语", components=[SlideComponent(
                id="greeting_cards", component_type="VocabularyFlipCard", data={"items": vocabulary},
            )], media_requirements=MediaRequirements(
                image_key="greeting_symbols", image_prompt="simple semantic greeting sequence", media_kind="svg_illustration",
                illustration_level="icon", text_policy="no_text", scene_type="diagram",
            )),
            LessonSlide(id=3, slide_type="DialogueSlide", layout_variant="contrast", title="你好 / 您好", content_blocks=[
                ContentBlock(id="nihao", text="你好！", scaffolding_text="nǐ hǎo · Hello!"),
                ContentBlock(id="ninhao", text="您好！", scaffolding_text="nín hǎo · Polite hello!"),
            ], media_requirements=_scene("polite_contrast", "Two clear greeting moments side by side: a learner greets a peer, and a learner politely greets an older teacher")),
            LessonSlide(id=4, slide_type="VocabularySlide", layout_variant="hero", title="早上好", content_blocks=[
                ContentBlock(id="morning", text="早上好！", scaffolding_text="zǎoshang hǎo · Good morning!"),
            ], media_requirements=_scene("morning_greeting", "Two learners greet each other in the morning outside a school, with gentle early sunlight")),
            LessonSlide(id=5, slide_type="PracticeSlide", layout_variant="listen_choose", title="听一听，选一选", content_blocks=[
                ContentBlock(id="listen_instruction", text="听一听，选出你听到的问候语。", scaffolding_text="Listen and choose the greeting you hear."),
            ], components=[SlideComponent(id="listen_greeting", component_type="ListenAndChoose", data={
                "audio_key": "audio_ninhao", "audio_text": "您好", "choices": ["你好", "您好", "再见"], "answer": "您好",
            })]),
            LessonSlide(id=6, slide_type="PracticeSlide", layout_variant="matching", title="连一连", content_blocks=[
                ContentBlock(id="match_instruction", text="把中文问候语和英文意思连起来。", scaffolding_text="Match each Chinese greeting with its English meaning."),
            ], components=[SlideComponent(id="match_greetings", component_type="MatchGame", data={"pairs": [
                {"left": "你好", "right": "hello"}, {"left": "您好", "right": "hello (polite)"},
                {"left": "早上好", "right": "good morning"}, {"left": "再见", "right": "goodbye"},
            ]})]),
            LessonSlide(id=7, slide_type="DialogueSlide", layout_variant="hero", title="再见！", content_blocks=[
                ContentBlock(id="goodbye", text="再见！", scaffolding_text="zàijiàn · Goodbye!"),
            ], media_requirements=_scene("goodbye_scene", "A teacher and two learners wave goodbye naturally as class ends, with friendly expressions")),
            LessonSlide(id=8, slide_type="SummarySlide", layout_variant="cards", title="今天会说", content_blocks=[
                ContentBlock(id="summary", text="你好 · 您好 · 老师好 · 早上好 · 再见", scaffolding_text="Choose the greeting that fits the person and time."),
            ]),
        ],
    )


def _pilot_report(root: Path, raster_assets, generation_ms: float, html_path: Path, pptx_path: Path, zip_path: Path) -> dict:
    with zipfile.ZipFile(pptx_path) as archive:
        pptx_media = [name for name in archive.namelist() if name.startswith("ppt/media/")]
    with zipfile.ZipFile(zip_path) as archive:
        remote_urls = any(
            b"images.siliconflow" in archive.read(name)
            for name in archive.namelist() if name.endswith((".html", ".json"))
        )
    generated = [asset for asset in raster_assets if asset.generation]
    return {
        "schema": "hanclassstudio.greetings_raster_pilot.v1",
        "verdict": "pending_teacher_visual_review",
        "teacher_visual_review_required": True,
        "total_generation_time_ms": generation_ms,
        "provider_calls": len(generated),
        "first_pass_usable_images": None,
        "regeneration_count": 0,
        "fallback_count": sum(asset.fallback_used for asset in raster_assets),
        "teacher_replacements": sum(asset.review_state == "replaced_by_teacher" for asset in raster_assets),
        "teacher_had_to_edit_json_or_code": False,
        "html_projection_quality": "pending_human_review",
        "mobile_readability": "pending_human_review",
        "pptx_image_quality": "pending_human_review",
        "artifacts": {"root": str(root), "html": str(html_path), "pptx": str(pptx_path), "zip": str(zip_path)},
        "pptx_embedded_media_count": len(pptx_media),
        "remote_provider_url_in_export": remote_urls,
        "assets": [asset.model_dump(mode="json") for asset in raster_assets],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-raster", action="store_true")
    args = parser.parse_args()
    print(build_pilot(real_raster=args.real_raster))
