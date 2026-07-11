from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from hcs_api.asset_review import (
    apply_review, raster_request_fingerprint, render_review_page, replace_with_teacher_image,
)
from hcs_api.media import generate_configured_media
from hcs_api.models import (
    ImageProviderSettings, IllustrationRequest, LessonBlueprint, LessonSlide,
    MediaRequirements, MediaReviewAction, ProviderSettings,
)
from hcs_api.raster_provider import ProviderImagePayload


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(output, format="PNG")
    return output.getvalue()


def _blueprint() -> LessonBlueprint:
    return LessonBlueprint(lesson_title="你好", slides=[LessonSlide(
        id=1, slide_type="CoverSlide", layout_variant="hero", title="你好",
        media_requirements=MediaRequirements(
            image_key="greeting", image_prompt="student greets teacher", media_kind="raster",
        ),
    )])


def _settings() -> ProviderSettings:
    return ProviderSettings(image=ImageProviderSettings(
        provider="experimental_openai_images", endpoint_url="https://provider.test/v1/images/generations",
        api_key="test-key", model="test-model",
    ))


def _payload(content: bytes, request_id: str) -> ProviderImagePayload:
    return ProviderImagePayload(
        image_bytes=content, mime_type="image/png", model="test-model",
        prompt="student greets teacher", revised_prompt=None, seed=7,
        retry_count=0, provider_request_id=request_id, warnings=[],
    )


def _save_manifest(root: Path, manifest) -> None:
    path = root / "assets" / "data" / "asset_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(), encoding="utf-8")


def test_accept_reject_fallback_and_candidate_history(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hcs_api.media.generate_experimental_raster_image",
        lambda *_args: _payload(_png((10, 20, 30)), "first"),
    )
    manifest = generate_configured_media(tmp_path, _blueprint(), _settings())
    asset = manifest.images[0]
    generated = next(item for item in asset.candidates if item.source == "generated")
    fallback = next(item for item in asset.candidates if item.source == "fallback")
    assert asset.review_state == "pending_review"

    apply_review(tmp_path, manifest, asset.id, MediaReviewAction(state="accepted", candidate_id=generated.id))
    assert asset.review_state == "accepted" and asset.path == generated.path
    apply_review(tmp_path, manifest, asset.id, MediaReviewAction(state="rejected", notes="pose unclear"))
    assert asset.review_state == "rejected" and asset.path == fallback.path
    assert generated in asset.candidates
    apply_review(tmp_path, manifest, asset.id, MediaReviewAction(state="fallback_accepted", candidate_id=fallback.id))
    assert asset.review_state == "fallback_accepted" and asset.fallback_used
    apply_review(tmp_path, manifest, asset.id, MediaReviewAction(state="regenerate_requested"))
    assert asset.review_state == "regenerate_requested" and asset.path == fallback.path
    assert [event.state for event in asset.review_history] == [
        "accepted", "rejected", "fallback_accepted", "regenerate_requested",
    ]
    page = render_review_page("project", manifest)
    assert generated.path in page and fallback.path in page
    assert "Teacher media review" in page


def test_teacher_replacement_wins_and_is_preserved(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def generate(*_args):
        nonlocal calls
        calls += 1
        return _payload(_png((10, 20, 30)), "generated")

    monkeypatch.setattr("hcs_api.media.generate_experimental_raster_image", generate)
    manifest = generate_configured_media(tmp_path, _blueprint(), _settings())
    replace_with_teacher_image(tmp_path, manifest, "greeting", _png((200, 100, 50)), "image/png", "teacher choice")
    replacement = manifest.images[0]
    assert replacement.review_state == "replaced_by_teacher"
    assert replacement.selected_candidate_id.startswith("teacher-")
    _save_manifest(tmp_path, manifest)

    reused = generate_configured_media(tmp_path, _blueprint(), _settings()).images[0]
    assert calls == 1
    assert reused.path == replacement.path and reused.review_state == "replaced_by_teacher"


def test_equivalent_request_reuses_and_force_regenerate_retains_prior(tmp_path: Path, monkeypatch) -> None:
    contents = iter([_png((10, 20, 30)), _png((40, 50, 60))])
    calls = 0

    def generate(*_args):
        nonlocal calls
        calls += 1
        return _payload(next(contents), f"request-{calls}")

    monkeypatch.setattr("hcs_api.media.generate_experimental_raster_image", generate)
    first = generate_configured_media(tmp_path, _blueprint(), _settings())
    _save_manifest(tmp_path, first)
    reused = generate_configured_media(tmp_path, _blueprint(), _settings())
    assert calls == 1 and reused.images[0].content_hash == first.images[0].content_hash
    _save_manifest(tmp_path, reused)

    regenerated = generate_configured_media(tmp_path, _blueprint(), _settings(), force_regenerate=True)
    assert calls == 2
    generated = [item for item in regenerated.images[0].candidates if item.source == "generated"]
    assert len(generated) == 2
    assert all((tmp_path / item.path).is_file() for item in generated)


def test_style_version_changes_request_fingerprint() -> None:
    settings = _settings().image
    first = IllustrationRequest(id="x", concept="你好", scene_description="student greets teacher")
    same = first.model_copy(update={"scene_description": "  student   greets teacher "})
    changed = first.model_copy(update={"style_profile_version": "2"})
    assert raster_request_fingerprint(first, settings) == raster_request_fingerprint(same, settings)
    assert raster_request_fingerprint(first, settings) != raster_request_fingerprint(changed, settings)
