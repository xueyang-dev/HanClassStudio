from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image
from pptx import Presentation

from hcs_api import storage
from hcs_api.media import generate_configured_media
from hcs_api.models import (
    AssetManifest, ContentBlock, ImageProviderSettings, LessonBlueprint,
    LessonProfile, LessonSlide, MediaRequirements, ProviderSettings, QualityReport,
)
from hcs_api.pptx_exporter import export_editable_pptx
from hcs_api.raster_provider import ProviderImagePayload, RasterProviderError
from hcs_api.renderer import render_lesson


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 36), (88, 166, 194)).save(output, format="PNG")
    return output.getvalue()


def _blueprint() -> LessonBlueprint:
    return LessonBlueprint(
        lesson_title="你好",
        slides=[LessonSlide(
            id=1,
            slide_type="CoverSlide",
            layout_variant="hero",
            title="你好",
            content_blocks=[ContentBlock(id="hello", text="你好", scaffolding_text="Hello")],
            media_requirements=MediaRequirements(
                image_key="greeting_scene",
                image_prompt="one student greeting a teacher",
                media_kind="raster",
            ),
        )],
    )


def _settings() -> ProviderSettings:
    return ProviderSettings(image=ImageProviderSettings(
        provider="experimental_openai_images",
        endpoint_url="https://provider.test/images/generations",
        api_key="test-key",
        model="test-image-model",
    ))


def _project(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    project_id = "opt_in_raster"
    root = storage.ensure_project(project_id)
    return project_id, root


def _mock_success(monkeypatch, image_bytes: bytes) -> None:
    monkeypatch.setattr(
        "hcs_api.media.generate_experimental_raster_image",
        lambda _settings, request: ProviderImagePayload(
            image_bytes=image_bytes,
            mime_type="image/png",
            model="test-image-model",
            prompt=request.scene_description,
            revised_prompt=None,
            seed=17,
            retry_count=0,
            provider_request_id="request-17",
            warnings=[],
        ),
    )


def test_opt_in_raster_survives_html_pptx_and_zip(tmp_path: Path, monkeypatch) -> None:
    project_id, root = _project(tmp_path, monkeypatch)
    blueprint = _blueprint()
    profile = LessonProfile(lesson_title="你好", learner_level="zero_beginner", scaffolding_language="English")
    image_bytes = _png()
    _mock_success(monkeypatch, image_bytes)

    manifest = generate_configured_media(root, blueprint, _settings())
    raster = manifest.images[0]
    assert raster.path == "assets/images/greeting_scene.png"
    assert raster.generation and raster.generation.provider == "experimental_openai_images"

    storage.write_model(project_id, "lesson_blueprint.json", blueprint)
    storage.write_model(project_id, "lesson_profile.json", profile)
    storage.write_model(project_id, "asset_manifest.json", manifest)
    storage.write_model(project_id, "quality_report.json", QualityReport(state="pass"))
    for relative in (
        "quality/evidence_alignment_report.json",
        "quality/presentation_readiness_report.json",
        "presentation/binding_quality_report.json",
    ):
        storage.write_json(project_id, relative, {"state": "pass"})
    html_path = render_lesson(root, profile, blueprint, manifest, QualityReport(state="pass"))
    html = html_path.read_text(encoding="utf-8")
    assert '../assets/images/greeting_scene.png' in html

    pptx_path = export_editable_pptx(project_id, force=True)
    presentation = Presentation(pptx_path)
    assert presentation.slides
    with zipfile.ZipFile(pptx_path) as pptx_zip:
        assert any(name.startswith("ppt/media/") for name in pptx_zip.namelist())

    (root / "diagnostics" / "must-not-export.json").write_text("{}", encoding="utf-8")
    zip_path = storage.zip_output(project_id, force=True)
    with zipfile.ZipFile(zip_path) as courseware_zip:
        names = courseware_zip.namelist()
        assert "assets/images/greeting_scene.png" in names
        assert "lesson.html" in names
        assert not any(name.startswith("diagnostics/") for name in names)
        assert courseware_zip.read("assets/images/greeting_scene.png") == image_bytes
        assert b"http://" not in courseware_zip.read("lesson.html")
        assert b"https://" not in courseware_zip.read("lesson.html")


def test_default_and_failure_paths_remain_svg(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path, monkeypatch)
    default_manifest = generate_configured_media(tmp_path / "default", _blueprint(), ProviderSettings())
    assert default_manifest.images[0].path.endswith(".svg")

    monkeypatch.setattr(
        "hcs_api.media.generate_experimental_raster_image",
        lambda *_args: (_ for _ in ()).throw(RasterProviderError(
            "http", "download denied", stage="remote_asset_download", category="download_forbidden", status_code=451,
        )),
    )
    failed = generate_configured_media(tmp_path / "failed", _blueprint(), _settings()).images[0]
    assert failed.path.endswith(".svg") and failed.fallback_used
    assert failed.generation_failure and failed.generation_failure.status_code == 451


def test_old_manifest_deserializes_without_raster_provenance() -> None:
    manifest = AssetManifest.model_validate({
        "images": [{"id": "legacy", "kind": "image", "path": "assets/images/legacy.svg"}],
    })
    assert manifest.images[0].generation is None
    assert manifest.images[0].generation_failure is None
    assert manifest.images[0].fallback_used is False
