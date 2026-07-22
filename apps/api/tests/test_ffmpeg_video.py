from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
import zlib
from pathlib import Path

import pytest
from pydantic import ValidationError

import hcs_api.ffmpeg_video as video
from hcs_api.ffmpeg_video import (
    CompiledSubtitleCue,
    CompiledVideoExecutionPlan,
    FfmpegCapability,
    FfmpegVideoError,
    TeachingVideoPlan,
    TeachingVideoSegment,
    compile_teaching_video_plan,
    execute_compiled_video_plan,
    probe_ffmpeg,
    render_teaching_video_plan,
)


CAFE_LINES = [
    ("customer", "你好，我要一杯咖啡。", "Hello, I'd like a cup of coffee."),
    ("clerk", "好的，您要热的还是冰的？", "Sure. Would you like it hot or iced?"),
    ("customer", "我要一杯热咖啡，谢谢。", "I'd like a hot coffee, thank you."),
    ("clerk", "好的，一共二十元。", "Okay, the total is twenty yuan."),
    ("customer", "给你。", "Here you are."),
    ("clerk", "谢谢，请稍等。", "Thank you. Please wait a moment."),
]


def _png(path: Path, width: int, height: int, color: tuple[int, int, int]) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    rows = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )


def _tone(path: Path, frequency: int, duration: float = 0.18, sample_rate: int = 8_000, channels: int = 1) -> None:
    frame_count = round(duration * sample_rate)
    frames = bytearray()
    for index in range(frame_count):
        sample = round(4000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<h", sample) * channels)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "assets/images").mkdir(parents=True)
    (tmp_path / "assets/audio").mkdir(parents=True)
    (tmp_path / "assets/video").mkdir(parents=True)
    return tmp_path


def _segment(
    index: int = 1,
    *,
    fit_mode: str = "contain",
    visual: str = "card.png",
    audio: str = "line.wav",
    leading: float = 0.1,
    trailing: float = 0.2,
) -> dict:
    return {
        "segment_id": f"segment-{index}",
        "speaker_id": "customer" if index % 2 else "clerk",
        "chinese": f"第{index}句\n中文",
        "translation": f"Line {index} in English.",
        "audio_asset_id": f"audio-{index}",
        "audio_path": f"assets/audio/{audio}",
        "visual_asset_id": f"visual-{index}",
        "visual_path": f"assets/images/{visual}",
        "fit_mode": fit_mode,
        "leading_padding_seconds": leading,
        "trailing_padding_seconds": trailing,
    }


def _plan(*segments: dict, transition: str = "hard_cut") -> dict:
    return {
        "schema_version": 1,
        "video_id": "cafe-ordering-dialogue",
        "title": "在咖啡馆点餐",
        "segments": list(segments) or [_segment()],
        "output": {
            "recipe_id": "hcs_teaching_video_720p_v1",
            "transition": transition,
            "subtitles": {"format": "webvtt", "burn_in": True, "include_translation": True},
        },
    }


def _dummy_assets(root: Path) -> None:
    (root / "assets/images/card.png").write_bytes(b"image fixture")
    (root / "assets/images/tall.png").write_bytes(b"tall image fixture")
    (root / "assets/audio/line.wav").write_bytes(b"audio fixture")


def _fake_probe(monkeypatch: pytest.MonkeyPatch, duration: float = 0.5) -> None:
    def probe(_path: Path, kind: str, _asset_id: str) -> dict[str, float | int]:
        return {"width": 640, "height": 360} if kind == "image" else {
            "duration": duration, "sample_rate": 16_000, "channels": 1,
        }

    monkeypatch.setattr(video, "_probe_asset", probe)


def _cafe_fixture(root: Path) -> TeachingVideoPlan:
    image_specs = [
        ("customer-wide.png", 640, 360, (65, 105, 180)),
        ("clerk-tall.png", 240, 480, (190, 95, 70)),
        ("counter-square.png", 360, 360, (80, 150, 110)),
    ]
    for name, width, height, color in image_specs:
        _png(root / f"assets/images/{name}", width, height, color)
    segments: list[TeachingVideoSegment] = []
    for index, (speaker, chinese, translation) in enumerate(CAFE_LINES, start=1):
        audio_name = f"line-{index}.wav"
        _tone(
            root / f"assets/audio/{audio_name}",
            260 + index * 55,
            duration=0.14 + index * 0.01,
            sample_rate=8_000 if index % 2 else 16_000,
            channels=1 if index % 2 else 2,
        )
        visual_name = image_specs[(index - 1) % len(image_specs)][0]
        segments.append(TeachingVideoSegment(
            segment_id=f"cafe-{index}",
            speaker_id=speaker,
            chinese=chinese,
            translation=translation,
            audio_asset_id=f"cafe-audio-{index}",
            audio_path=f"assets/audio/{audio_name}",
            visual_asset_id=f"cafe-visual-{(index - 1) % len(image_specs) + 1}",
            visual_path=f"assets/images/{visual_name}",
            fit_mode="contain" if index % 2 else "cover",
            leading_padding_seconds=0.05,
            trailing_padding_seconds=0.05,
        ))
    return TeachingVideoPlan(video_id="cafe-ordering-dialogue", title="在咖啡馆点餐", segments=segments)


def _require_ffmpeg() -> FfmpegCapability:
    capability = probe_ffmpeg()
    if not capability.available:
        pytest.skip("FFmpeg integration unavailable: " + ", ".join(capability.blockers))
    return capability


def test_plan_schema_defaults_and_rejects_duplicates_or_missing_references() -> None:
    plan = TeachingVideoPlan.model_validate(_plan())
    assert plan.schema_version == 1
    assert plan.segments[0].duration_policy == "match_audio"
    assert plan.segments[0].fit_mode == "contain"
    assert plan.output.recipe_id == "hcs_teaching_video_720p_v1"
    assert plan.output.transition == "hard_cut"

    with pytest.raises(ValidationError, match="segment IDs must be unique"):
        TeachingVideoPlan.model_validate(_plan(_segment(1), _segment(1)))
    missing = _segment()
    missing["audio_path"] = ""
    with pytest.raises(ValidationError):
        TeachingVideoPlan.model_validate(_plan(missing))


def test_subtitle_text_normalizes_newlines_and_rejects_control_characters() -> None:
    payload = _segment()
    payload["chinese"] = "你好\r\n我要咖啡"
    segment = TeachingVideoSegment.model_validate(payload)
    assert segment.chinese == "你好\n我要咖啡"
    payload["translation"] = "unsafe\x00text"
    with pytest.raises(ValidationError, match="control character"):
        TeachingVideoSegment.model_validate(payload)
    payload["translation"] = "unsafe\u0085text"
    with pytest.raises(ValidationError, match="control character"):
        TeachingVideoSegment.model_validate(payload)
    payload["translation"] = "unsafe\n\n00:00:00.000 --> 00:00:01.000"
    with pytest.raises(ValidationError, match="WebVTT structure"):
        TeachingVideoSegment.model_validate(payload)


def test_compiler_calculates_timeline_subtitles_fit_and_stable_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    _dummy_assets(root)
    _fake_probe(monkeypatch, duration=0.5)
    spec = _plan(
        _segment(1, fit_mode="contain", leading=0.1, trailing=0.2),
        _segment(2, fit_mode="cover", visual="tall.png", leading=0.2, trailing=0.1),
    )

    first = compile_teaching_video_plan(root, spec)
    second = compile_teaching_video_plan(root, spec)

    assert first.plan_sha256 == second.plan_sha256
    assert first.source_plan_sha256 == second.source_plan_sha256
    assert first.total_duration_seconds == 1.6
    assert [item.fit_operation for item in first.segments] == ["scale_contain_pad", "scale_cover_crop"]
    assert first.segments[0].timeline_start_seconds == 0
    assert first.segments[0].timeline_end_seconds == 0.8
    assert first.subtitle_cues[0].start_seconds == 0.1
    assert first.subtitle_cues[0].end_seconds == 0.6
    assert first.subtitle_cues[1].start_seconds == 1.0
    assert first.subtitle_cues[1].end_seconds == 1.5
    assert [(item.segment_id, item.kind) for item in first.source_assets] == [
        ("segment-1", "image"), ("segment-1", "audio"),
        ("segment-2", "image"), ("segment-2", "audio"),
    ]
    assert first.video_path == "assets/video/cafe-ordering-dialogue.mp4"
    assert first.subtitle_path == "assets/video/cafe-ordering-dialogue.vtt"


def test_compiler_rejects_smart_crop_crossfade_and_duration_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    _dummy_assets(root)
    _fake_probe(monkeypatch)
    with pytest.raises(FfmpegVideoError) as smart_crop:
        compile_teaching_video_plan(root, _plan(_segment(fit_mode="smart_crop")))
    assert smart_crop.value.code == "unsupported_fit_mode"
    with pytest.raises(FfmpegVideoError) as crossfade:
        compile_teaching_video_plan(root, _plan(_segment(), transition="short_crossfade"))
    assert crossfade.value.code == "unsupported_transition"

    _fake_probe(monkeypatch, duration=150)
    with pytest.raises(FfmpegVideoError) as overflow:
        compile_teaching_video_plan(root, _plan(_segment(1), _segment(2)))
    assert overflow.value.code == "duration_limit_exceeded"


def test_compiler_classifies_missing_and_unsafe_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path)
    _dummy_assets(root)
    _fake_probe(monkeypatch)
    missing = _segment()
    missing["visual_path"] = "assets/images/missing.png"
    with pytest.raises(FfmpegVideoError) as missing_error:
        compile_teaching_video_plan(root, _plan(missing))
    assert missing_error.value.code == "missing_visual_asset"

    unsafe = _segment()
    unsafe["audio_path"] = "assets/audio/../../outside.wav"
    with pytest.raises(FfmpegVideoError) as unsafe_error:
        compile_teaching_video_plan(root, _plan(unsafe))
    assert unsafe_error.value.code == "unsafe_path"
    assert str(tmp_path) not in str(unsafe_error.value)


def test_webvtt_is_utf8_bilingual_escaped_and_timing_checked() -> None:
    cue = CompiledSubtitleCue(
        index=1, segment_id="s1", speaker_id="customer", start_seconds=0.1, end_seconds=0.7,
        chinese="你好\n我要 <咖啡>", translation="Hello & coffee",
    )
    payload = video._webvtt_bytes([cue])
    text = payload.decode("utf-8")
    assert "customer：你好\n我要 &lt;咖啡&gt;" in text
    assert "Hello &amp; coffee" in text
    assert "00:00:00.100 --> 00:00:00.700" in text

    bad = cue.model_copy(update={"end_seconds": 0.05})
    with pytest.raises(FfmpegVideoError) as error:
        video._webvtt_bytes([bad])
    assert error.value.code == "subtitle_validation_failed"


def test_compiled_plan_forbids_arbitrary_executable_arguments_and_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    _dummy_assets(root)
    _fake_probe(monkeypatch)
    compiled = compile_teaching_video_plan(root, _plan())
    payload = compiled.model_dump(mode="json")
    payload["executable"] = "/bin/sh"
    with pytest.raises(ValidationError):
        CompiledVideoExecutionPlan.model_validate(payload)
    payload = compiled.model_dump(mode="json")
    payload["video_id"] = "../../escape"
    with pytest.raises(ValidationError):
        CompiledVideoExecutionPlan.model_validate(payload)
    payload = compiled.model_dump(mode="json")
    payload["arguments"] = ["-f", "lavfi"]
    with pytest.raises(ValidationError):
        CompiledVideoExecutionPlan.model_validate(payload)

    compiled.video_path = "../../unsafe.mp4"
    compiled.plan_sha256 = video._compiled_plan_hash(compiled)
    with pytest.raises(FfmpegVideoError) as error:
        execute_compiled_video_plan(root, compiled)
    assert error.value.code == "unsafe_path"


def test_real_cafe_dialogue_generates_verified_mp4_vtt_and_provenance(tmp_path: Path) -> None:
    capability = _require_ffmpeg()
    root = _project(tmp_path)
    plan = _cafe_fixture(root)

    compiled = compile_teaching_video_plan(root, plan)
    repeated = compile_teaching_video_plan(root, plan)
    artifact = execute_compiled_video_plan(root, compiled)

    assert len(plan.segments) == 6
    assert {segment.speaker_id for segment in plan.segments} == {"customer", "clerk"}
    assert len({segment.audio_path for segment in plan.segments}) == 6
    assert len({segment.visual_path for segment in plan.segments}) == 3
    assert {segment.fit_operation for segment in compiled.segments} == {"scale_contain_pad", "scale_cover_crop"}
    assert compiled.plan_sha256 == repeated.plan_sha256
    assert artifact.recipe_id == "hcs_teaching_video_720p_v1"
    assert artifact.video_codec == "h264"
    assert artifact.audio_codec == "aac"
    assert (artifact.width, artifact.height) == (1280, 720)
    assert abs(artifact.duration_seconds - compiled.total_duration_seconds) <= 0.75
    assert len(artifact.video_sha256) == len(artifact.subtitle_sha256) == len(artifact.plan_sha256) == 64
    assert len(artifact.provenance.source_assets) == 12
    assert all(len(source.sha256) == 64 for source in artifact.provenance.source_assets)
    assert artifact.provenance.source_plan_sha256 == compiled.source_plan_sha256
    assert artifact.provenance.ffmpeg_version == capability.ffmpeg_version
    assert artifact.provenance.ffprobe_version == capability.ffprobe_version

    video_path = root / artifact.video_path
    subtitle_path = root / artifact.subtitle_path
    assert video_path.is_file() and subtitle_path.is_file()
    subtitle = subtitle_path.read_text(encoding="utf-8")
    assert subtitle.startswith("WEBVTT\n")
    assert subtitle.count(" --> ") == 6
    for _speaker, chinese, translation in CAFE_LINES:
        assert chinese in subtitle
        assert translation.replace("'", "&#x27;") in subtitle

    probe = subprocess.run([
        capability.probe_executable or "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(video_path),
    ], capture_output=True, text=True, check=False)
    assert probe.returncode == 0
    metadata = json.loads(probe.stdout)
    assert {stream["codec_name"] for stream in metadata["streams"]} == {"h264", "aac"}
    assert any(stream.get("width") == 1280 and stream.get("height") == 720 for stream in metadata["streams"])
    cue = compiled.subtitle_cues[0]
    burned_frame = subprocess.run([
        capability.executable or "ffmpeg", "-v", "error", "-i", str(video_path),
        "-ss", f"{cue.start_seconds + 0.03:.3f}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], capture_output=True, check=False)
    clear_frame = subprocess.run([
        capability.executable or "ffmpeg", "-v", "error", "-i", str(video_path),
        "-ss", f"{cue.end_seconds + 0.02:.3f}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], capture_output=True, check=False)
    assert burned_frame.returncode == clear_frame.returncode == 0
    assert len(burned_frame.stdout) == len(clear_frame.stdout) == 1280 * 720 * 3
    assert burned_frame.stdout != clear_frame.stdout
    assert not list((root / "assets/video").glob(".cafe-ordering-dialogue-*"))
    assert not (root / "assets/video/.cafe-ordering-dialogue.lock").exists()


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [("image", "invalid_image"), ("audio", "invalid_audio")],
)
def test_real_probe_rejects_corrupt_inputs(tmp_path: Path, kind: str, expected_code: str) -> None:
    _require_ffmpeg()
    root = _project(tmp_path)
    _png(root / "assets/images/card.png", 64, 64, (50, 100, 150))
    _tone(root / "assets/audio/line.wav", 440)
    target = root / ("assets/images/card.png" if kind == "image" else "assets/audio/line.wav")
    target.write_bytes(b"not valid media")

    with pytest.raises(FfmpegVideoError) as error:
        compile_teaching_video_plan(root, _plan())

    assert error.value.code == expected_code
    assert not (root / "assets/video/cafe-ordering-dialogue.mp4").exists()


def test_real_probe_rejects_missing_file_and_duration_limit(tmp_path: Path) -> None:
    _require_ffmpeg()
    missing_root = _project(tmp_path / "missing")
    _tone(missing_root / "assets/audio/line.wav", 440)
    with pytest.raises(FfmpegVideoError) as missing:
        compile_teaching_video_plan(missing_root, _plan())
    assert missing.value.code == "missing_visual_asset"

    long_root = _project(tmp_path / "long")
    _png(long_root / "assets/images/card.png", 64, 64, (50, 100, 150))
    _tone(long_root / "assets/audio/line.wav", 220, duration=150, sample_rate=8_000)
    with pytest.raises(FfmpegVideoError) as duration:
        compile_teaching_video_plan(long_root, _plan(_segment(1), _segment(2)))
    assert duration.value.code == "duration_limit_exceeded"


def test_ffmpeg_failure_cleans_all_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _require_ffmpeg()
    root = _project(tmp_path)
    full_plan = _cafe_fixture(root)
    plan = full_plan.model_copy(update={"segments": full_plan.segments[:1]})
    compiled = compile_teaching_video_plan(root, plan)
    false_executable = shutil.which("false")
    assert false_executable
    monkeypatch.setattr(video, "probe_ffmpeg", lambda: capability.model_copy(update={"executable": false_executable}))

    with pytest.raises(FfmpegVideoError) as error:
        execute_compiled_video_plan(root, compiled)

    assert error.value.code == "ffmpeg_failed"
    assert not (root / compiled.video_path).exists()
    assert not (root / compiled.subtitle_path).exists()
    assert not list((root / "assets/video").glob(f".{plan.video_id}-*"))


def test_ffprobe_verification_failure_cleans_all_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_ffmpeg()
    root = _project(tmp_path)
    full_plan = _cafe_fixture(root)
    plan = full_plan.model_copy(update={"segments": full_plan.segments[:1]})
    compiled = compile_teaching_video_plan(root, plan)

    def fail_verification(_path: Path, _duration: float, _ffprobe: str) -> dict:
        raise FfmpegVideoError("ffprobe_failed", "forced verification failure")

    monkeypatch.setattr(video, "_verify_video", fail_verification)
    with pytest.raises(FfmpegVideoError) as error:
        execute_compiled_video_plan(root, compiled)

    assert error.value.code == "ffprobe_failed"
    assert not (root / compiled.video_path).exists()
    assert not (root / compiled.subtitle_path).exists()
    assert not list((root / "assets/video").glob(f".{plan.video_id}-*"))


def test_output_conflict_and_changed_source_fail_closed(tmp_path: Path) -> None:
    _require_ffmpeg()
    conflict_root = _project(tmp_path / "conflict")
    conflict_plan = _cafe_fixture(conflict_root)
    compiled = compile_teaching_video_plan(conflict_root, conflict_plan)
    conflict_path = conflict_root / compiled.video_path
    conflict_path.write_bytes(b"teacher-owned sentinel")
    with pytest.raises(FfmpegVideoError) as conflict:
        execute_compiled_video_plan(conflict_root, compiled)
    assert conflict.value.code == "output_conflict"
    assert conflict_path.read_bytes() == b"teacher-owned sentinel"
    assert not (conflict_root / compiled.subtitle_path).exists()

    locked_root = _project(tmp_path / "locked")
    locked_plan = _cafe_fixture(locked_root)
    locked_compiled = compile_teaching_video_plan(locked_root, locked_plan)
    lock_path = locked_root / "assets/video/.cafe-ordering-dialogue.lock"
    lock_path.write_text("concurrent fixture", encoding="utf-8")
    with pytest.raises(FfmpegVideoError) as locked:
        execute_compiled_video_plan(locked_root, locked_compiled)
    assert locked.value.code == "output_conflict"
    assert not (locked_root / locked_compiled.video_path).exists()
    assert not (locked_root / locked_compiled.subtitle_path).exists()

    changed_root = _project(tmp_path / "changed")
    changed_plan = _cafe_fixture(changed_root)
    one_segment = changed_plan.model_copy(update={"segments": changed_plan.segments[:1]})
    changed_compiled = compile_teaching_video_plan(changed_root, one_segment)
    _tone(changed_root / one_segment.segments[0].audio_path, 900)
    with pytest.raises(FfmpegVideoError) as changed:
        execute_compiled_video_plan(changed_root, changed_compiled)
    assert changed.value.code == "unsafe_path"
    assert not (changed_root / changed_compiled.video_path).exists()
    assert not (changed_root / changed_compiled.subtitle_path).exists()


def test_render_facade_compiles_and_executes(tmp_path: Path) -> None:
    _require_ffmpeg()
    root = _project(tmp_path)
    full_plan = _cafe_fixture(root)
    one_segment = full_plan.model_copy(update={"video_id": "cafe-short", "segments": full_plan.segments[:1]})

    artifact = render_teaching_video_plan(root, one_segment)

    assert artifact.artifact_id == "cafe-short"
    assert (root / artifact.video_path).is_file()
    assert (root / artifact.subtitle_path).is_file()
