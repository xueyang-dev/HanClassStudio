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
import hcs_api.video_generation as video_generation
from hcs_api.ffmpeg_video import (
    FfmpegCapability,
    SubtitleFontCapability,
    TeachingVideoPlan,
    TeachingVideoSegment,
    probe_ffmpeg,
)
from hcs_api.models import AssetManifest, VideoArtifactRecord, VideoGenerationFailureRecord
from hcs_api.video_generation import (
    VideoPublicationTransaction,
    approve_teaching_video_proposal,
    create_teaching_video_proposal,
    create_video_generation_request,
    execute_video_generation_request,
    recover_video_publication_transactions,
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
    capability = FfmpegCapability(
        available=True,
        ffmpeg_version="controlled-ffmpeg",
        ffprobe_version="controlled-ffprobe",
        executable="ffmpeg",
        probe_executable="ffprobe",
        subtitle_font=SubtitleFontCapability(
            family="Controlled CJK",
            file="/controlled/font.ttf",
            file_name="font.ttf",
            sha256="1" * 64,
            selection="configured",
            source="user",
            license_status="local_only",
        ),
    )
    monkeypatch.setattr(video_generation, "probe_ffmpeg", lambda: capability)


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


def test_changed_font_hash_marks_approval_stale(
    tmp_path: Path,
    controlled_media_probe: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    proposal, approval, _request = _approved_request(root)
    changed = FfmpegCapability(
        available=True,
        ffmpeg_version="controlled-ffmpeg",
        ffprobe_version="controlled-ffprobe",
        executable="ffmpeg",
        probe_executable="ffprobe",
        subtitle_font=SubtitleFontCapability(
            family="Controlled CJK",
            file="/controlled/font.ttf",
            file_name="font.ttf",
            sha256="2" * 64,
            selection="configured",
            source="user",
            license_status="local_only",
        ),
    )
    monkeypatch.setattr(video_generation, "probe_ffmpeg", lambda: changed)

    result = execute_video_generation_request(root, create_video_generation_request(proposal, approval))

    assert isinstance(result, VideoGenerationFailureRecord)
    assert result.code == "approval_stale"
    assert result.teacher_approval is not None
    assert result.teacher_approval.stale_reason == "rendering_environment_changed"


def test_approved_generation_registers_complete_manifest_and_reuses_exact_match(tmp_path: Path) -> None:
    capability = _require_ffmpeg()
    root = _project(tmp_path)
    proposal, approval, request = _approved_request(root)

    generated = execute_video_generation_request(root, request)

    assert isinstance(generated, VideoArtifactRecord)
    assert generated.generation_status == "generated"
    assert generated.plan_sha256 == approval.approved_plan_sha256 == proposal.plan_sha256
    assert generated.artifact_id == "approval-contract-video"
    assert generated.video_path == "assets/video/approval-contract-video.mp4"
    assert generated.subtitle_path == "assets/video/approval-contract-video.vtt"
    assert generated.recipe_id == "hcs_teaching_video_720p_v1"
    assert generated.recipe_version == 1
    assert generated.video_codec == "h264"
    assert generated.audio_codec == "aac"
    assert (generated.width, generated.height) == (1280, 720)
    assert {(item.kind, item.asset_id) for item in generated.input_assets} == {
        ("image", "visual-card"), ("audio", "audio-line-1"),
    }
    assert generated.rendering_environment.subtitle_font.family == capability.subtitle_font.family  # type: ignore[union-attr]
    assert generated.rendering_environment.subtitle_font.sha256 == capability.subtitle_font.sha256  # type: ignore[union-attr]

    manifest_path = root / "assets/data/asset_manifest.json"
    manifest = AssetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest.video) == 1
    assert manifest.video[0].placeholder is False
    assert manifest.video[0].content_hash == generated.artifact_sha256
    assert manifest.video[0].video_artifact == generated
    assert len(manifest.video_approvals) == 1
    assert len(manifest.video_references) == 1
    assert manifest.video_references[0].unit_id == "unit-cafe"
    assert manifest.video_references[0].activity_id == "activity-dialogue"
    assert manifest.video_references[0].media_requirement_id == "media-dialogue-video"
    provenance_path = root / generated.provenance_ref
    assert provenance_path.is_file()
    assert hashlib.sha256(provenance_path.read_bytes()).hexdigest() == generated.provenance_sha256
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["schema_version"] == 2
    assert provenance["artifact"]["provenance"]["subtitle_font"]["sha256"] == generated.rendering_environment.subtitle_font.sha256
    assert "file" not in provenance["artifact"]["provenance"]["subtitle_font"]

    journal_path = next((root / "assets/data/video_transactions").glob("*.json"))
    transaction = VideoPublicationTransaction.model_validate_json(journal_path.read_text(encoding="utf-8"))
    assert transaction.phase == "completed"
    assert transaction.expected_hashes == {
        "video": generated.artifact_sha256,
        "subtitle": generated.subtitle_sha256,
        "provenance": generated.provenance_sha256,
    }
    video_generation._write_transaction(root, transaction.model_copy(update={"phase": "provenance_published"}))
    recovered = recover_video_publication_transactions(root, capability=capability)
    assert recovered[0].phase == "completed"
    assert recovered[0].recovery_action == "registered"

    reused = execute_video_generation_request(root, create_video_generation_request(proposal, approval))
    assert isinstance(reused, VideoArtifactRecord)
    assert reused.generation_status == "reused"
    assert reused.artifact_sha256 == generated.artifact_sha256
    unchanged = AssetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert len(unchanged.video) == 1


def test_binary_reuse_adds_distinct_teaching_reference(tmp_path: Path) -> None:
    _require_ffmpeg()
    root = _project(tmp_path)
    proposal, _approval, request = _approved_request(root)
    generated = execute_video_generation_request(root, request)
    assert isinstance(generated, VideoArtifactRecord)
    second_proposal = proposal.model_copy(update={
        "teaching_unit_id": "unit-review",
        "activity_id": "activity-review",
        "media_requirement_id": "media-review-video",
    })
    second_approval = approve_teaching_video_proposal(second_proposal, teacher_id="teacher-li")

    reused = execute_video_generation_request(
        root,
        create_video_generation_request(second_proposal, second_approval),
    )

    assert isinstance(reused, VideoArtifactRecord)
    assert reused.generation_status == "reused"
    manifest = AssetManifest.model_validate_json((root / "assets/data/asset_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest.video) == 1
    assert len(manifest.video_approvals) == 2
    assert len(manifest.video_references) == 2
    assert {reference.activity_id for reference in manifest.video_references} == {
        "activity-dialogue", "activity-review",
    }


def test_corrupt_matching_artifact_requires_explicit_regeneration(tmp_path: Path) -> None:
    capability = _require_ffmpeg()
    root = _project(tmp_path)
    proposal, approval, request = _approved_request(root)
    generated = execute_video_generation_request(root, request)
    assert isinstance(generated, VideoArtifactRecord)
    (root / generated.video_path).write_bytes(b"corrupt")
    journal_path = next((root / "assets/data/video_transactions").glob("*.json"))
    transaction = VideoPublicationTransaction.model_validate_json(journal_path.read_text(encoding="utf-8"))
    video_generation._write_transaction(root, transaction.model_copy(update={"phase": "manifest_committed"}))

    recovered = recover_video_publication_transactions(root, capability=capability)

    assert recovered[0].phase == "completed"
    assert recovered[0].recovery_action == "regeneration_required"

    result = execute_video_generation_request(root, create_video_generation_request(proposal, approval))

    assert isinstance(result, VideoGenerationFailureRecord)
    assert result.code == "regeneration_required"
    manifest = AssetManifest.model_validate_json((root / "assets/data/asset_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest.video) == 1


def test_reuse_semantically_revalidates_media_subtitles_provenance_and_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _require_ffmpeg()
    root = _project(tmp_path)
    _proposal, _approval, request = _approved_request(root)
    generated = execute_video_generation_request(root, request)
    assert isinstance(generated, VideoArtifactRecord)
    manifest = AssetManifest.model_validate_json((root / "assets/data/asset_manifest.json").read_text(encoding="utf-8"))
    asset = manifest.video[0]
    calls = {"video": 0, "vtt": 0}
    real_video_verify = video_generation._verify_video
    real_vtt_verify = video_generation._verify_webvtt

    def verify_video(*args, **kwargs):
        calls["video"] += 1
        return real_video_verify(*args, **kwargs)

    def verify_vtt(*args, **kwargs):
        calls["vtt"] += 1
        return real_vtt_verify(*args, **kwargs)

    monkeypatch.setattr(video_generation, "_verify_video", verify_video)
    monkeypatch.setattr(video_generation, "_verify_webvtt", verify_vtt)
    assert video_generation._registered_artifact_is_valid(root, asset, generated, capability)
    assert calls == {"video": 1, "vtt": 1}
    assert not video_generation._registered_artifact_is_valid(
        root,
        asset,
        generated.model_copy(update={"recipe_version": 99}),
        capability,
    )
    provenance_path = root / generated.provenance_ref
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["schema_version"] = 99
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    changed_provenance = generated.model_copy(update={
        "provenance_sha256": hashlib.sha256(provenance_path.read_bytes()).hexdigest(),
    })
    assert not video_generation._registered_artifact_is_valid(root, asset, changed_provenance, capability)


def test_prepared_transaction_recovery_cleans_partial_files_idempotently(tmp_path: Path) -> None:
    root = _project(tmp_path)
    video_path = root / "assets/video/orphan.mp4"
    video_path.write_bytes(b"partial")
    staging = root / "assets/video/.orphan-video-txn-fixed-work"
    staging.mkdir()
    transaction = VideoPublicationTransaction(
        transaction_id="video-txn-fixed",
        asset_id="orphan",
        plan_sha256="1" * 64,
        staging_paths=["assets/video/.orphan-video-txn-fixed-*"],
        final_paths=["assets/video/orphan.mp4", "assets/video/orphan.vtt", "assets/data/video/orphan.provenance.json"],
        expected_hashes={"video": None, "subtitle": None, "provenance": None},
    )
    video_generation._write_transaction(root, transaction)

    recovered = recover_video_publication_transactions(root)
    repeated = recover_video_publication_transactions(root)

    assert recovered[0].phase == "completed"
    assert recovered[0].recovery_action == "cleaned"
    assert repeated == []
    assert not video_path.exists()
    assert not staging.exists()


def test_unjournaled_output_is_reported_as_orphan_not_output_conflict(
    tmp_path: Path,
    controlled_media_probe: None,
) -> None:
    root = _project(tmp_path)
    proposal, approval, _request = _approved_request(root)
    (root / "assets/video/approval-contract-video.mp4").write_bytes(b"unregistered")

    result = execute_video_generation_request(root, create_video_generation_request(proposal, approval))

    assert isinstance(result, VideoGenerationFailureRecord)
    assert result.code == "orphan_detected"


def test_capability_probe_verifies_decoders_subtitle_filter_and_cjk_font() -> None:
    capability = _require_ffmpeg()

    assert set(("png", "mjpeg", "webp", "aac", "mp3", "vorbis", "opus", "pcm_s16le")) <= set(capability.verified_decoders)
    assert capability.subtitle_font is not None
    assert Path(capability.subtitle_font.file).is_file()
    assert len(capability.subtitle_font.sha256) == 64
    assert capability.subtitle_font.source in {"system", "user"}
    assert capability.subtitle_font.license_status == "local_only"


def test_missing_configured_cjk_font_returns_stable_blocker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HCS_CJK_FONT_PATH", str(tmp_path / "missing-font.ttf"))
    monkeypatch.setenv("HCS_CJK_FONT_FAMILY", "Missing CJK Font")

    font, blocker = ffmpeg_video._probe_subtitle_font()

    assert font is None
    assert blocker == "cjk_font_not_found"


def test_project_bundled_font_requires_approved_license(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    font_path = tmp_path / "project-font.ttf"
    font_path.write_bytes(b"font fixture")
    monkeypatch.setenv("HCS_CJK_FONT_PATH", str(font_path))
    monkeypatch.setenv("HCS_CJK_FONT_FAMILY", "Project CJK")
    monkeypatch.setenv("HCS_CJK_FONT_SOURCE", "project_bundled")
    monkeypatch.setenv("HCS_CJK_FONT_LICENSE_STATUS", "unknown")

    font, blocker = ffmpeg_video._probe_subtitle_font()

    assert font is None
    assert blocker == "project_font_license_not_approved"


def test_approved_project_bundled_font_has_stable_redistribution_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    font_path = tmp_path / "project-font.ttf"
    font_path.write_bytes(b"font fixture")
    monkeypatch.setenv("HCS_CJK_FONT_PATH", str(font_path))
    monkeypatch.setenv("HCS_CJK_FONT_FAMILY", "Project CJK")
    monkeypatch.setenv("HCS_CJK_FONT_SOURCE", "project_bundled")
    monkeypatch.setenv("HCS_CJK_FONT_LICENSE_STATUS", "approved")

    font, blocker = ffmpeg_video._probe_subtitle_font()

    assert blocker is None
    assert font is not None
    assert font.source == "project_bundled"
    assert font.license_status == "approved"
    assert font.file_name == "project-font.ttf"
    assert len(font.sha256) == 64
