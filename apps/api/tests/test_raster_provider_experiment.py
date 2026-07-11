from __future__ import annotations

import base64
import json
from email.message import Message
from hashlib import sha256
from pathlib import Path

import pytest

from hcs_api.media import generate_configured_media, generate_placeholder_media, generate_raster_image
from hcs_api.models import (
    ContentBlock,
    EvidenceSpec,
    GeneratedImage,
    IllustrationRequest,
    ImageProviderSettings,
    LearningActivity,
    LearningGoal,
    LessonBlueprint,
    LessonSlide,
    MediaRequirements,
    PresentationContentItem,
    PresentationMediaRequest,
    ProviderSettings,
)
from hcs_api.raster_provider import EXPERIMENTAL_PROVIDER, RasterProviderError, generate_experimental_raster_image
from hcs_api.raster_provider_benchmark import BENCHMARK_CONCEPTS, create_raster_provider_ab_gallery


PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x03\x08\x06\x00\x00\x00"


class _Response:
    def __init__(self, body: bytes, content_type: str = "application/json", request_id: str | None = None):
        self._body = body
        self.headers = Message()
        self.headers.add_header("Content-Type", content_type)
        if request_id:
            self.headers["x-request-id"] = request_id

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _request() -> IllustrationRequest:
    return IllustrationRequest(
        id="sleep",
        concept="睡觉",
        scene_description="A Chinese learner sleeping in a bed, no text.",
        aspect_ratio="16:9",
        source_trace=["test"],
    )


def _settings(**changes) -> ProviderSettings:
    values = {
        "provider": EXPERIMENTAL_PROVIDER,
        "endpoint_url": "https://provider.test/images",
        "api_key": "test-key",
        "model": "low-cost-test-model",
    }
    values.update(changes)
    return ProviderSettings(image=ImageProviderSettings(**values))


def _blueprint() -> LessonBlueprint:
    return LessonBlueprint(
        lesson_title="Test",
        slides=[LessonSlide(
            id=1, slide_type="Visual", layout_variant="full", title="睡觉",
            content_blocks=[ContentBlock(id="c", text="睡觉")],
            media_requirements=MediaRequirements(image_key="sleep", image_prompt="sleeping in bed", media_kind="raster"),
        )],
    )


def _mock_generation(monkeypatch, item: dict, *, download: bytes | None = None, mime_type: str = "image/png", collection: str = "data") -> None:
    def urlopen(request, timeout, **_kwargs):
        if request.get_method() == "POST":
            return _Response(json.dumps({"id": "req_123", collection: [item]}).encode(), request_id="header_456")
        assert download is not None
        return _Response(download, mime_type, request_id="download_789")
    monkeypatch.setattr("hcs_api.raster_provider.urllib.request.urlopen", urlopen)


def test_neutral_request_and_result_serialization() -> None:
    request = _request()
    result = GeneratedImage(
        provider=EXPERIMENTAL_PROVIDER, model="m", local_path="assets/images/sleep.png", mime_type="image/png",
        prompt=request.scene_description, content_hash="a" * 64, source_trace=request.source_trace,
    )
    assert IllustrationRequest.model_validate(request.model_dump(mode="json")).concept == "睡觉"
    assert GeneratedImage.model_validate(result.model_dump(mode="json")).local_path.endswith(".png")


def test_provider_is_disabled_by_default_and_missing_key_is_safe() -> None:
    assert generate_raster_image(ProviderSettings(), "sleep") is None
    with pytest.raises(RasterProviderError, match="disabled"):
        generate_experimental_raster_image(ProviderSettings().image, _request())
    settings = _settings(api_key="")
    assert generate_raster_image(settings, "sleep") is None
    with pytest.raises(RasterProviderError, match="no API key"):
        generate_experimental_raster_image(settings.image, _request())


def test_timeout_http_and_invalid_mime_each_keep_svg_fallback(tmp_path: Path, monkeypatch) -> None:
    cases = [
        TimeoutError("timed out"),
        __import__("urllib.error").error.HTTPError("https://provider.test", 502, "bad gateway", {}, None),
        None,
    ]
    for number, failure in enumerate(cases):
        root = tmp_path / str(number)
        expected = generate_placeholder_media(root, _blueprint()).images[0]
        expected_bytes = (root / expected.path).read_bytes()
        if failure is None:
            _mock_generation(monkeypatch, {"url": "https://temporary.test/image.png"}, download=PNG, mime_type="text/html")
        else:
            def urlopen(_request, timeout, failure=failure, **_kwargs):
                raise failure
            monkeypatch.setattr("hcs_api.raster_provider.urllib.request.urlopen", urlopen)
        manifest = generate_configured_media(root, _blueprint(), _settings())
        asset = manifest.images[0]
        assert asset.path.endswith(".svg")
        assert asset.fallback_used is True
        assert asset.fallback_reason
        assert (root / asset.path).exists()
        assert (root / asset.path).read_bytes() == expected_bytes


def test_temporary_url_is_downloaded_locally_and_manifest_has_no_remote_url(tmp_path: Path, monkeypatch) -> None:
    url = "https://temporary.test/image.png?signature=short-lived"
    _mock_generation(monkeypatch, {"url": url}, download=PNG)
    manifest = generate_configured_media(tmp_path, _blueprint(), _settings())
    asset = manifest.images[0]
    assert asset.path == "assets/images/sleep.png"
    assert (tmp_path / asset.path).read_bytes() == PNG
    dumped = json.dumps(manifest.model_dump(mode="json"))
    assert url not in dumped
    assert asset.mime_type == "image/png"
    assert asset.content_hash == sha256(PNG).hexdigest()
    assert asset.generation and asset.generation.provider_request_id == "header_456"
    assert asset.generation.model == "low-cost-test-model"
    assert asset.generation.prompt == "sleeping in bed"


def test_octet_stream_download_is_verified_by_image_signature(tmp_path: Path, monkeypatch) -> None:
    _mock_generation(monkeypatch, {"url": "https://temporary.test/image"}, download=PNG, mime_type="application/octet-stream")
    asset = generate_configured_media(tmp_path, _blueprint(), _settings()).images[0]
    assert asset.path.endswith(".png")
    assert asset.mime_type == "image/png"


def test_siliconflow_images_url_response_shape_is_supported(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    def urlopen(request, timeout, **_kwargs):
        if request.get_method() == "POST":
            captured.update(json.loads(request.data.decode()))
            return _Response(json.dumps({
                "images": [{"url": "https://temporary.test/image.png"}],
                "seed": 42,
            }).encode(), request_id="silicon-trace-123")
        return _Response(PNG, "image/png")

    monkeypatch.setattr("hcs_api.raster_provider.urllib.request.urlopen", urlopen)
    asset = generate_configured_media(tmp_path, _blueprint(), _settings()).images[0]
    assert asset.path == "assets/images/sleep.png"
    assert asset.fallback_used is False
    assert captured["image_size"] == "1536x864"
    assert captured["batch_size"] == 1
    assert "size" not in captured and "n" not in captured
    assert asset.generation and asset.generation.seed == 42
    assert asset.generation.provider_request_id == "silicon-trace-123"


def test_content_hash_is_deterministic_and_extension_tracks_mime(tmp_path: Path, monkeypatch) -> None:
    encoded = base64.b64encode(PNG).decode()
    _mock_generation(monkeypatch, {"b64_json": encoded, "mime_type": "image/webp", "revised_prompt": "revised"})
    first = generate_configured_media(tmp_path / "first", _blueprint(), _settings()).images[0]
    _mock_generation(monkeypatch, {"b64_json": encoded, "mime_type": "image/webp", "revised_prompt": "revised"})
    second = generate_configured_media(tmp_path / "second", _blueprint(), _settings()).images[0]
    assert first.content_hash == second.content_hash == sha256(PNG).hexdigest()
    assert first.path.endswith(".webp") and first.mime_type == "image/webp"
    assert first.generation and first.generation.revised_prompt == "revised"


def test_existing_facade_callers_stay_compatible(monkeypatch) -> None:
    settings = ProviderSettings(image=ImageProviderSettings(provider="openai_images", api_key="key"))
    monkeypatch.setattr("hcs_api.media.generate_openai_image", lambda image_settings, prompt: b"legacy-bytes")
    assert generate_raster_image(settings, "legacy prompt") == b"legacy-bytes"


def test_default_production_media_behavior_and_gallery_are_diagnostic_only(tmp_path: Path) -> None:
    root = tmp_path / "project"
    manifest = generate_configured_media(root, _blueprint(), ProviderSettings())
    assert manifest.images[0].path.endswith(".svg")
    assert not (root / "diagnostics" / "raster_provider_generation.json").exists()

    index = create_raster_provider_ab_gallery(root, ProviderSettings())
    results = json.loads((index.parent / "results.json").read_text(encoding="utf-8"))
    assert index == root / "diagnostics" / "raster_provider_ab" / "index.html"
    assert len(results["records"]) == len(BENCHMARK_CONCEPTS)
    assert all(record["fallback_used"] for record in results["records"])
    assert not (root / "courseware" / "lesson.html").exists()
    assert not (root / "assets" / "data" / "asset_manifest.json").exists()


def test_state_evidence_and_presentation_models_have_no_provider_fields() -> None:
    for model in (LearningGoal, EvidenceSpec, LearningActivity, PresentationContentItem, PresentationMediaRequest):
        assert "provider" not in model.model_fields
        assert "model" not in model.model_fields
        assert "api_key" not in model.model_fields
