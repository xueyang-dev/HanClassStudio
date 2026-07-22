from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
import zlib
from pathlib import Path

import pytest

import hcs_api.ffmpeg_video as ffmpeg_video
from hcs_api.ffmpeg_video import FfmpegCapability, TeachingVideoPlan, TeachingVideoSegment, probe_ffmpeg
from hcs_api.models import AssetManifest, GeneratedVideoAssetRecord, VideoGenerationFailureRecord
from hcs_api.video_generation import (
    approve_teaching_video_proposal,
    create_teaching_video_proposal,
    create_video_generation_request,
    execute_video_generation_request,
)


def _png(path: Path) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    width, height = 96, 54
    rows = b"".join(b"\x00" + bytes((55, 110, 175)) * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )


def _tone(path: Path, frequency: int = 440) -> None:
    sample_rate = 8_000
    frames = bytearray()
    for index in range(round(0.18 * sample_rate)):
        sample = round(4000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def _project(tmp_path: Path) -> Path:
    for relative in ("assets/images", "assets/audio", "assets/video", "assets/data"):
        (tmp_path / relative).mkdir(parents=True)
    _png(tmp_path / "assets/images/card.png")
    _tone(tmp_path / "assets/audio/line.wav")
    return tmp_path


def _plan() -> TeachingVideoPlan:
    return TeachingVideoPlan(
        video_id="approval-contract-video",
        title="咖啡馆对话",
        segments=[TeachingVideoSegment(
            segment_id="line-1",
            speaker_id="customer",
            chinese="你好，我要一杯咖啡。",
            translation="Hello, I would like a coffee.",
            audio_asset_id="audio-line-1",
            audio_path="assets/audio/line.wav",
            visual_asset_id="visual-card",
            visual_path="assets/images/card.png",
            leading_padding_seconds=0.05,
            trailing_padding_seconds=0.05,
        )],
    )


def _require_ffmpeg() -> FfmpegCapability:
    capability = probe_ffmpeg()
    if not capability.available:
        pytest.skip("FFmpeg integration unavailable: " + ", ".join(capability.blockers))
    return capability


@pytest.fixture
def controlled_media_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep approval-domain tests independent from the host media toolchain."""

    monkeypatch.setattr(ffmpeg_video, "_probe_asset", lambda _path, kind, _asset_id: (
        {"width": 96, "height": 54}
        if kind == "image"
        else {"duration": 0.18, "sample_rate": 8_000, "channels": 1}
    ))


def _approved_request(root: Path):
    proposal = create_teaching_video_proposal(
        root,
        _plan(),
        teaching_unit_id="unit-cafe",
        activity_id="activity-dialogue",
        media_requirement_id="media-dialogue-video",
    )
    approval = approve_teaching_video_proposal(proposal, teacher_id="teacher-li", notes="台词与画面已确认")
    return proposal, approval, create_video_generation_request(proposal, approval)


def test_execution_requires_explicit_teacher_approval(tmp_path: Path, controlled_media_probe: None) -> None:
    root = _project(tmp_path)
    proposal = create_teaching_video_proposal(root, _plan(), activity_id="activity-dialogue")

    result = execute_video_generation_request(root, create_video_generation_request(proposal))

    assert isinstance(result, VideoGenerationFailureRecord)
    assert result.code == "approval_required"
    assert result.stage == "approval"
    assert not (root / "assets/video/approval-contract-video.mp4").exists()


def test_changed_script_marks_hash_bound_approval_stale_without_execution(
    tmp_path: Path,
    controlled_media_probe: None,
) -> None:
    root = _project(tmp_path)
    proposal, approval, _request = _approved_request(root)
    changed_segment = proposal.plan.segments[0].model_copy(update={"chinese": "你好，我要两杯咖啡。"})
    changed_plan = proposal.plan.model_copy(update={"segments": [changed_segment]})
    changed_proposal = proposal.model_copy(update={"plan": changed_plan})

    result = execute_video_generation_request(root, create_video_generation_request(changed_proposal, approval))

    assert isinstance(result, VideoGenerationFailureRecord)
    assert result.code == "approval_stale"
    assert result.teacher_approval is not None
    assert result.teacher_approval.approval_status == "stale"
    assert result.teacher_approval.stale_reason == "proposal_plan_changed"
    assert not (root / "assets/video/approval-contract-video.mp4").exists()


def test_changed_input_asset_marks_approval_stale_without_execution(
    tmp_path: Path,
    controlled_media_probe: None,
) -> None:
    root = _project(tmp_path)
    proposal, approval, _request = _approved_request(root)
    _tone(root / "assets/audio/line.wav", frequency=880)

    result = execute_video_generation_request(root, create_video_generation_request(proposal, approval))

    assert isinstance(result, VideoGenerationFailureRecord)
    assert result.code == "approval_stale"
    assert result.teacher_approval is not None
    assert result.teacher_approval.approval_status == "stale"
    assert not (root / "assets/video/approval-contract-video.mp4").exists()


def test_approved_generation_registers_complete_manifest_and_reuses_exact_match(tmp_path: Path) -> None:
    capability = _require_ffmpeg()
    root = _project(tmp_path)
    proposal, approval, request = _approved_request(root)

    generated = execute_video_generation_request(root, request)

    assert isinstance(generated, GeneratedVideoAssetRecord)
    assert generated.generation_status == "generated"
    assert generated.plan_sha256 == approval.approved_plan_sha256 == proposal.plan_sha256
    assert generated.asset_id == "approval-contract-video"
    assert generated.video_path == "assets/video/approval-contract-video.mp4"
    assert generated.subtitle_path == "assets/video/approval-contract-video.vtt"
    assert generated.recipe_id == "hcs_teaching_video_720p_v1"
    assert generated.recipe_version == 1
    assert generated.video_codec == "h264"
    assert generated.audio_codec == "aac"
    assert (generated.width, generated.height) == (1280, 720)
    assert generated.teaching_unit_id == "unit-cafe"
    assert generated.activity_id == "activity-dialogue"
    assert generated.media_requirement_id == "media-dialogue-video"
    assert {(item.kind, item.asset_id) for item in generated.input_assets} == {
        ("image", "visual-card"), ("audio", "audio-line-1"),
    }
    assert generated.subtitle_font_family == capability.subtitle_font.family  # type: ignore[union-attr]
    assert generated.subtitle_font_sha256 == capability.subtitle_font.sha256  # type: ignore[union-attr]

    manifest_path = root / "assets/data/asset_manifest.json"
    manifest = AssetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest.video) == 1
    assert manifest.video[0].placeholder is False
    assert manifest.video[0].content_hash == generated.artifact_sha256
    assert manifest.video[0].video_generation == generated
    provenance_path = root / generated.provenance_ref
    assert provenance_path.is_file()
    assert hashlib.sha256(provenance_path.read_bytes()).hexdigest() == generated.provenance_sha256
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["teacher_approval"]["approval_id"] == approval.approval_id
    assert provenance["artifact"]["provenance"]["subtitle_font"]["sha256"] == generated.subtitle_font_sha256

    reused = execute_video_generation_request(root, create_video_generation_request(proposal, approval))
    assert isinstance(reused, GeneratedVideoAssetRecord)
    assert reused.generation_status == "reused"
    assert reused.artifact_sha256 == generated.artifact_sha256
    unchanged = AssetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert len(unchanged.video) == 1


def test_corrupt_matching_artifact_requires_explicit_regeneration(tmp_path: Path) -> None:
    _require_ffmpeg()
    root = _project(tmp_path)
    proposal, approval, request = _approved_request(root)
    generated = execute_video_generation_request(root, request)
    assert isinstance(generated, GeneratedVideoAssetRecord)
    (root / generated.video_path).write_bytes(b"corrupt")

    result = execute_video_generation_request(root, create_video_generation_request(proposal, approval))

    assert isinstance(result, VideoGenerationFailureRecord)
    assert result.code == "regeneration_required"
    manifest = AssetManifest.model_validate_json((root / "assets/data/asset_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest.video) == 1


def test_capability_probe_verifies_decoders_subtitle_filter_and_cjk_font() -> None:
    capability = _require_ffmpeg()

    assert set(("png", "mjpeg", "webp", "aac", "mp3", "vorbis", "opus", "pcm_s16le")) <= set(capability.verified_decoders)
    assert capability.subtitle_font is not None
    assert Path(capability.subtitle_font.file).is_file()
    assert len(capability.subtitle_font.sha256) == 64
    assert capability.subtitle_font.redistribution_status == "not_bundled_license_review_required"


def test_missing_configured_cjk_font_returns_stable_blocker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HCS_CJK_FONT_PATH", str(tmp_path / "missing-font.ttf"))
    monkeypatch.setenv("HCS_CJK_FONT_FAMILY", "Missing CJK Font")

    font, blocker = ffmpeg_video._probe_subtitle_font()

    assert font is None
    assert blocker == "cjk_font_not_found"
