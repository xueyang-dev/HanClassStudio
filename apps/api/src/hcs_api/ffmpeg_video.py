"""Controlled FFmpeg compiler for small offline language-teaching videos.

Callers describe segments and project-owned assets. They never provide an
executable, argument list, filter graph, codec, or output path.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator


RECIPE_ID = "hcs_teaching_video_720p_v1"
RECIPE_VERSION = 1
MAX_DURATION_SECONDS = 300
MAX_SEGMENTS = 24
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 200 * 1024 * 1024
MAX_SUBTITLE_BYTES = 128 * 1024
PROCESS_TIMEOUT_SECONDS = 120
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
FRAME_RATE = 30
AUDIO_SAMPLE_RATE = 48_000
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_AUDIO_SUFFIXES = {".aac", ".m4a", ".mp3", ".ogg", ".wav"}
_REQUIRED_DECODERS = ("png", "mjpeg", "webp", "aac", "mp3", "vorbis", "opus", "pcm_s16le")
_SAFE_FONT_FAMILY = re.compile(r"^[\w .-]{1,100}$", re.UNICODE)

VideoErrorCode = Literal[
    "invalid_video_plan",
    "missing_visual_asset",
    "missing_audio_asset",
    "invalid_image",
    "invalid_audio",
    "unsupported_fit_mode",
    "unsupported_transition",
    "subtitle_validation_failed",
    "duration_limit_exceeded",
    "ffmpeg_failed",
    "ffprobe_failed",
    "artifact_verification_failed",
    "unsafe_path",
    "output_conflict",
    "cancelled",
    "internal_error",
]


class FfmpegVideoError(RuntimeError):
    def __init__(self, code: VideoErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class SubtitleFontCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str
    file: str
    file_name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: Literal["configured", "fontconfig"]
    redistribution_status: Literal["not_bundled_license_review_required"] = "not_bundled_license_review_required"


class FfmpegCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    executable: str | None = None
    probe_executable: str | None = None
    supported_operations: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    verified_decoders: list[str] = Field(default_factory=list)
    subtitle_font: SubtitleFontCapability | None = None


class TeachingSubtitleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["webvtt"] = "webvtt"
    burn_in: Literal[True] = True
    include_translation: bool = True


class TeachingVideoOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: Literal["hcs_teaching_video_720p_v1"] = RECIPE_ID
    transition: Literal["hard_cut", "short_crossfade"] = "hard_cut"
    subtitles: TeachingSubtitleSpec = Field(default_factory=TeachingSubtitleSpec)


class TeachingVideoSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    speaker_id: str
    chinese: str = Field(min_length=1, max_length=500)
    translation: str | None = Field(default=None, max_length=1000)
    audio_asset_id: str
    audio_path: str = Field(min_length=1, max_length=500)
    visual_asset_id: str
    visual_path: str = Field(min_length=1, max_length=500)
    fit_mode: Literal["contain", "cover", "smart_crop"] = "contain"
    subtitle_mode: Literal["bilingual", "chinese_only"] = "bilingual"
    duration_policy: Literal["match_audio"] = "match_audio"
    leading_padding_seconds: float = Field(default=0.15, ge=0, le=2)
    trailing_padding_seconds: float = Field(default=0.20, ge=0, le=2)

    @field_validator("segment_id", "speaker_id", "audio_asset_id", "visual_asset_id")
    @classmethod
    def _stable_id(cls, value: str) -> str:
        if not _ID_PATTERN.fullmatch(value):
            raise ValueError("stable IDs may contain only letters, numbers, underscores, or hyphens")
        return value

    @field_validator("chinese", "translation")
    @classmethod
    def _safe_subtitle_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            if info.field_name == "translation":
                return None
            raise ValueError("Chinese subtitle text cannot be blank")
        if _contains_forbidden_control(normalized):
            raise ValueError("subtitle text contains a forbidden control character")
        if _contains_webvtt_structure(normalized):
            raise ValueError("subtitle text contains forbidden WebVTT structure")
        if len(normalized.splitlines()) > 8:
            raise ValueError("subtitle text has too many lines")
        return normalized


class TeachingVideoPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    video_id: str
    title: str = Field(min_length=1, max_length=200)
    segments: list[TeachingVideoSegment] = Field(min_length=1, max_length=MAX_SEGMENTS)
    output: TeachingVideoOutputSpec = Field(default_factory=TeachingVideoOutputSpec)

    @field_validator("video_id")
    @classmethod
    def _safe_video_id(cls, value: str) -> str:
        if not _ID_PATTERN.fullmatch(value):
            raise ValueError("video_id may contain only letters, numbers, underscores, or hyphens")
        return value

    @model_validator(mode="after")
    def _unique_segments_and_assets(self) -> "TeachingVideoPlan":
        segment_ids = [segment.segment_id for segment in self.segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("segment IDs must be unique")
        asset_paths: dict[tuple[str, str], str] = {}
        for segment in self.segments:
            for kind, asset_id, path in (
                ("image", segment.visual_asset_id, segment.visual_path),
                ("audio", segment.audio_asset_id, segment.audio_path),
            ):
                key = (kind, asset_id)
                if key in asset_paths and asset_paths[key] != path:
                    raise ValueError("one asset ID cannot reference multiple paths")
                asset_paths[key] = path
        return self


class CompiledSubtitleCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    segment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    speaker_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    start_seconds: float
    end_seconds: float
    chinese: str = Field(min_length=1, max_length=500)
    translation: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _valid_timing(self) -> "CompiledSubtitleCue":
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("subtitle timing must be positive and ordered")
        return self


class SourceAssetProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    kind: Literal["image", "audio"]
    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)


class CompiledTeachingVideoSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    visual_asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    visual_path: str = Field(min_length=1, max_length=500)
    visual_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    audio_path: str = Field(min_length=1, max_length=500)
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fit_operation: Literal["scale_contain_pad", "scale_cover_crop"]
    audio_operation: Literal["resample_delay_pad"] = "resample_delay_pad"
    audio_duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS)
    leading_padding_seconds: float = Field(ge=0, le=2)
    trailing_padding_seconds: float = Field(ge=0, le=2)
    duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS)
    timeline_start_seconds: float = Field(ge=0, le=MAX_DURATION_SECONDS)
    timeline_end_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS)


class CompiledVideoExecutionPlan(BaseModel):
    """Serializable instructions; the executor derives a fixed argv internally."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    video_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    recipe_id: Literal["hcs_teaching_video_720p_v1"] = RECIPE_ID
    recipe_version: Literal[1] = RECIPE_VERSION
    executable: Literal["ffmpeg"] = "ffmpeg"
    probe_executable: Literal["ffprobe"] = "ffprobe"
    operation: Literal["render_segments_concat_burn_webvtt"] = "render_segments_concat_burn_webvtt"
    transition: Literal["hard_cut"] = "hard_cut"
    video_path: str = Field(min_length=1, max_length=500)
    subtitle_path: str = Field(min_length=1, max_length=500)
    total_duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS)
    source_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_assets: list[SourceAssetProvenance] = Field(min_length=2, max_length=MAX_SEGMENTS * 2)
    segments: list[CompiledTeachingVideoSegment] = Field(min_length=1, max_length=MAX_SEGMENTS)
    subtitle_cues: list[CompiledSubtitleCue] = Field(min_length=1, max_length=MAX_SEGMENTS)
    plan_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")


class VideoArtifactProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_plan_sha256: str
    source_assets: list[SourceAssetProvenance]
    recipe_id: Literal["hcs_teaching_video_720p_v1"] = RECIPE_ID
    recipe_version: Literal[1] = RECIPE_VERSION
    ffmpeg_version: str
    ffprobe_version: str
    video_sha256: str
    subtitle_sha256: str
    plan_sha256: str
    actual_duration_seconds: float
    canvas: dict[str, int]
    encoder_verification: dict[str, str | int]
    subtitle_font: SubtitleFontCapability
    warnings: list[str] = Field(default_factory=list)


class VerifiedVideoArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    video_path: str
    subtitle_path: str
    recipe_id: Literal["hcs_teaching_video_720p_v1"] = RECIPE_ID
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    video_sha256: str
    subtitle_sha256: str
    plan_sha256: str
    source_assets: list[SourceAssetProvenance]
    warnings: list[str] = Field(default_factory=list)
    provenance: VideoArtifactProvenance


def probe_ffmpeg() -> FfmpegCapability:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    blockers: list[str] = []
    if not ffmpeg:
        blockers.append("ffmpeg_not_found")
    if not ffprobe:
        blockers.append("ffprobe_not_found")
    if blockers:
        return FfmpegCapability(available=False, blockers=blockers)
    try:
        version_result = _run([ffmpeg, "-hide_banner", "-version"], timeout=5)
        probe_version_result = _run([ffprobe, "-hide_banner", "-version"], timeout=5)
        encoder_result = _run([ffmpeg, "-hide_banner", "-encoders"], timeout=5)
        decoder_result = _run([ffmpeg, "-hide_banner", "-decoders"], timeout=5)
        filter_result = _run([ffmpeg, "-hide_banner", "-filters"], timeout=5)
    except (OSError, subprocess.SubprocessError):
        return FfmpegCapability(available=False, executable=ffmpeg, probe_executable=ffprobe, blockers=["ffmpeg_probe_failed"])
    if any(result.returncode != 0 for result in (version_result, probe_version_result, encoder_result, decoder_result, filter_result)):
        return FfmpegCapability(available=False, executable=ffmpeg, probe_executable=ffprobe, blockers=["ffmpeg_probe_failed"])
    if "libx264" not in encoder_result.stdout:
        blockers.append("h264_encoder_missing")
    if not re.search(r"^\s*A.....\s+aac\s", encoder_result.stdout, re.MULTILINE):
        blockers.append("aac_encoder_missing")
    if not re.search(r"^\s*\.\.\.\s+subtitles\s", filter_result.stdout, re.MULTILINE):
        blockers.append("subtitles_filter_missing")
    verified_decoders = [name for name in _REQUIRED_DECODERS if _has_codec(decoder_result.stdout, name)]
    blockers.extend(f"decoder_missing:{name}" for name in _REQUIRED_DECODERS if name not in verified_decoders)
    subtitle_font, font_blocker = _probe_subtitle_font()
    if font_blocker:
        blockers.append(font_blocker)
    return FfmpegCapability(
        available=not blockers,
        ffmpeg_version=_version(version_result.stdout, "ffmpeg"),
        ffprobe_version=_version(probe_version_result.stdout, "ffprobe"),
        executable=ffmpeg,
        probe_executable=ffprobe,
        supported_operations=["teaching_dialogue_video_720p_v1"] if not blockers else [],
        blockers=blockers,
        verified_decoders=verified_decoders,
        subtitle_font=subtitle_font,
    )


def compile_teaching_video_plan(
    project_root: Path,
    plan: TeachingVideoPlan | dict[str, Any],
) -> CompiledVideoExecutionPlan:
    """Validate assets, probe audio duration, and build a stable typed plan."""

    try:
        validated = plan if isinstance(plan, TeachingVideoPlan) else TeachingVideoPlan.model_validate(plan)
    except ValidationError as exc:
        raise FfmpegVideoError("invalid_video_plan", "TeachingVideoPlan failed schema validation") from exc
    if validated.output.transition == "short_crossfade":
        raise FfmpegVideoError("unsupported_transition", "short_crossfade is reserved but not implemented")

    project_root = _project_root(project_root)
    source_plan_sha256 = _stable_hash(validated.model_dump(mode="json"))
    compiled_segments: list[CompiledTeachingVideoSegment] = []
    source_assets: list[SourceAssetProvenance] = []
    cues: list[CompiledSubtitleCue] = []
    cursor = 0.0
    unique_sizes: dict[Path, int] = {}

    for index, segment in enumerate(validated.segments, start=1):
        if segment.fit_mode == "smart_crop":
            raise FfmpegVideoError("unsupported_fit_mode", "smart_crop is not implemented")
        visual = _resolve_asset(project_root, segment.visual_path, "image", segment.visual_asset_id)
        audio = _resolve_asset(project_root, segment.audio_path, "audio", segment.audio_asset_id)
        unique_sizes[visual] = visual.stat().st_size
        unique_sizes[audio] = audio.stat().st_size
        if sum(unique_sizes.values()) > MAX_TOTAL_INPUT_BYTES:
            raise FfmpegVideoError("invalid_video_plan", "total input size exceeds the controlled limit")
        image_metadata = _probe_asset(visual, "image", segment.visual_asset_id)
        audio_metadata = _probe_asset(audio, "audio", segment.audio_asset_id)
        if image_metadata["width"] <= 0 or image_metadata["height"] <= 0:
            raise FfmpegVideoError("invalid_image", f"visual asset {segment.visual_asset_id} has invalid dimensions")
        audio_duration = round(float(audio_metadata["duration"]), 6)
        duration = round(audio_duration + segment.leading_padding_seconds + segment.trailing_padding_seconds, 6)
        end = round(cursor + duration, 6)
        if duration > MAX_DURATION_SECONDS or end > MAX_DURATION_SECONDS:
            raise FfmpegVideoError("duration_limit_exceeded", f"compiled duration exceeds {MAX_DURATION_SECONDS} seconds")
        subtitle_start = round(cursor + segment.leading_padding_seconds, 6)
        subtitle_end = round(subtitle_start + audio_duration, 6)
        visual_hash = _sha256(visual)
        audio_hash = _sha256(audio)
        compiled_segments.append(CompiledTeachingVideoSegment(
            segment_id=segment.segment_id,
            visual_asset_id=segment.visual_asset_id,
            visual_path=segment.visual_path,
            visual_sha256=visual_hash,
            audio_asset_id=segment.audio_asset_id,
            audio_path=segment.audio_path,
            audio_sha256=audio_hash,
            fit_operation="scale_contain_pad" if segment.fit_mode == "contain" else "scale_cover_crop",
            audio_duration_seconds=audio_duration,
            leading_padding_seconds=segment.leading_padding_seconds,
            trailing_padding_seconds=segment.trailing_padding_seconds,
            duration_seconds=duration,
            timeline_start_seconds=cursor,
            timeline_end_seconds=end,
        ))
        source_assets.extend([
            SourceAssetProvenance(
                segment_id=segment.segment_id, asset_id=segment.visual_asset_id, kind="image",
                path=segment.visual_path, sha256=visual_hash, size_bytes=visual.stat().st_size,
            ),
            SourceAssetProvenance(
                segment_id=segment.segment_id, asset_id=segment.audio_asset_id, kind="audio",
                path=segment.audio_path, sha256=audio_hash, size_bytes=audio.stat().st_size,
            ),
        ])
        translation = segment.translation if (
            validated.output.subtitles.include_translation
            and segment.subtitle_mode == "bilingual"
            and segment.translation
        ) else None
        cues.append(CompiledSubtitleCue(
            index=index,
            segment_id=segment.segment_id,
            speaker_id=segment.speaker_id,
            start_seconds=subtitle_start,
            end_seconds=subtitle_end,
            chinese=segment.chinese,
            translation=translation,
        ))
        cursor = end

    if cursor > MAX_DURATION_SECONDS:
        raise FfmpegVideoError("duration_limit_exceeded", f"compiled duration exceeds {MAX_DURATION_SECONDS} seconds")
    subtitle_bytes = _webvtt_bytes(cues)
    if len(subtitle_bytes) > MAX_SUBTITLE_BYTES:
        raise FfmpegVideoError("subtitle_validation_failed", "compiled subtitles exceed the controlled size limit")

    compiled = CompiledVideoExecutionPlan(
        video_id=validated.video_id,
        video_path=f"assets/video/{validated.video_id}.mp4",
        subtitle_path=f"assets/video/{validated.video_id}.vtt",
        total_duration_seconds=cursor,
        source_plan_sha256=source_plan_sha256,
        source_assets=source_assets,
        segments=compiled_segments,
        subtitle_cues=cues,
    )
    compiled.plan_sha256 = _compiled_plan_hash(compiled)
    return compiled


def execute_compiled_video_plan(project_root: Path, plan: CompiledVideoExecutionPlan) -> VerifiedVideoArtifact:
    """Execute a compiler-produced plan and publish verified artifacts atomically."""

    project_root = _project_root(project_root)
    if plan.plan_sha256 != _compiled_plan_hash(plan):
        raise FfmpegVideoError("invalid_video_plan", "compiled plan hash does not match its structure")
    expected_video = f"assets/video/{plan.video_id}.mp4"
    expected_subtitle = f"assets/video/{plan.video_id}.vtt"
    if plan.video_path != expected_video or plan.subtitle_path != expected_subtitle:
        raise FfmpegVideoError("unsafe_path", "compiled output path is outside the controlled video lane")
    _validate_compiled_plan(plan)
    capability = probe_ffmpeg()
    if (
        not capability.available
        or not capability.executable
        or not capability.probe_executable
        or not capability.ffmpeg_version
        or not capability.ffprobe_version
        or not capability.subtitle_font
    ):
        raise FfmpegVideoError("ffmpeg_failed", ", ".join(capability.blockers) or "FFmpeg is unavailable")

    output_dir = project_root / "assets" / "video"
    output_dir.mkdir(parents=True, exist_ok=True)
    video_output = project_root / plan.video_path
    subtitle_output = project_root / plan.subtitle_path
    if video_output.exists() or subtitle_output.exists():
        raise FfmpegVideoError("output_conflict", f"output {plan.video_id} already exists")
    lock_path = output_dir / f".{plan.video_id}.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise FfmpegVideoError("output_conflict", f"output {plan.video_id} is already being generated") from exc
    os.close(lock_fd)

    published: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix=f".{plan.video_id}-", dir=output_dir) as temp_name:
            workdir = Path(temp_name)
            _stage_subtitle_font(workdir, capability.subtitle_font)
            copied = _copy_verified_inputs(project_root, workdir, plan)
            segment_files: list[str] = []
            for index, segment in enumerate(plan.segments):
                segment_name = f"segment-{index:03d}.mp4"
                segment_files.append(segment_name)
                _render_segment(capability.executable, workdir, segment, copied[index], segment_name)
            concat_path = workdir / "concat.txt"
            concat_path.write_text("".join(f"file '{name}'\n" for name in segment_files), encoding="utf-8")
            _run_ffmpeg_checked(capability.executable, [
                "-f", "concat", "-safe", "1", "-i", "concat.txt",
                "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-movflags", "+faststart", "joined.mp4",
            ], workdir, "concat")
            subtitle_stage = workdir / "dialogue.vtt"
            subtitle_stage.write_bytes(_webvtt_bytes(plan.subtitle_cues))
            _verify_webvtt(subtitle_stage, len(plan.subtitle_cues))
            _run_ffmpeg_checked(capability.executable, [
                "-i", "joined.mp4", "-map", "0:v:0", "-map", "0:a:0",
                "-vf", (
                    "subtitles=filename=dialogue.vtt:fontsdir=fonts:charenc=UTF-8:"
                    f"force_style='FontName={capability.subtitle_font.family}'"
                ),
                "-r", str(FRAME_RATE), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", str(AUDIO_SAMPLE_RATE),
                "-ac", "2", "-map_metadata", "-1", "-movflags", "+faststart", "verified.mp4",
            ], workdir, "subtitle_burn")
            video_stage = workdir / "verified.mp4"
            metadata = _verify_video(video_stage, plan.total_duration_seconds, capability.probe_executable)
            video_sha256 = _sha256(video_stage)
            subtitle_sha256 = _sha256(subtitle_stage)
            try:
                os.link(subtitle_stage, subtitle_output)
                published.append(subtitle_output)
                os.link(video_stage, video_output)
                published.append(video_output)
            except FileExistsError as exc:
                raise FfmpegVideoError("output_conflict", f"output {plan.video_id} was created concurrently") from exc

        provenance = VideoArtifactProvenance(
            source_plan_sha256=plan.source_plan_sha256,
            source_assets=plan.source_assets,
            ffmpeg_version=capability.ffmpeg_version,
            ffprobe_version=capability.ffprobe_version,
            video_sha256=video_sha256,
            subtitle_sha256=subtitle_sha256,
            plan_sha256=plan.plan_sha256,
            actual_duration_seconds=metadata["duration"],
            canvas={"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT},
            encoder_verification={
                "video_codec": metadata["video_codec"],
                "audio_codec": metadata["audio_codec"],
                "pixel_format": metadata["pixel_format"],
                "audio_sample_rate": metadata["audio_sample_rate"],
            },
            subtitle_font=capability.subtitle_font,
        )
        return VerifiedVideoArtifact(
            artifact_id=plan.video_id,
            video_path=plan.video_path,
            subtitle_path=plan.subtitle_path,
            duration_seconds=metadata["duration"],
            width=metadata["width"],
            height=metadata["height"],
            video_codec=metadata["video_codec"],
            audio_codec=metadata["audio_codec"],
            video_sha256=video_sha256,
            subtitle_sha256=subtitle_sha256,
            plan_sha256=plan.plan_sha256,
            source_assets=plan.source_assets,
            provenance=provenance,
        )
    except FfmpegVideoError:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        for path in published:
            path.unlink(missing_ok=True)
        raise FfmpegVideoError("internal_error", "controlled video execution failed internally") from exc
    finally:
        lock_path.unlink(missing_ok=True)


def render_teaching_video_plan(
    project_root: Path,
    plan: TeachingVideoPlan | dict[str, Any],
) -> VerifiedVideoArtifact:
    compiled = compile_teaching_video_plan(project_root, plan)
    return execute_compiled_video_plan(project_root, compiled)


def _project_root(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FfmpegVideoError("unsafe_path", "project root does not exist") from exc


def _resolve_asset(project_root: Path, relative_path: str, kind: Literal["image", "audio"], asset_id: str) -> Path:
    folder = "assets/images" if kind == "image" else "assets/audio"
    suffixes = _IMAGE_SUFFIXES if kind == "image" else _AUDIO_SUFFIXES
    missing_code: VideoErrorCode = "missing_visual_asset" if kind == "image" else "missing_audio_asset"
    invalid_code: VideoErrorCode = "invalid_image" if kind == "image" else "invalid_audio"
    requested = Path(relative_path)
    if requested.is_absolute() or ".." in requested.parts:
        raise FfmpegVideoError("unsafe_path", f"asset {asset_id} must use a project-relative path")
    allowed_root = (project_root / folder).resolve()
    candidate = (project_root / requested).resolve(strict=False)
    try:
        candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise FfmpegVideoError("unsafe_path", f"asset {asset_id} escapes {folder}") from exc
    if not candidate.exists():
        raise FfmpegVideoError(missing_code, f"asset {asset_id} is missing")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(allowed_root)
    except (FileNotFoundError, ValueError) as exc:
        raise FfmpegVideoError("unsafe_path", f"asset {asset_id} resolves outside {folder}") from exc
    if not resolved.is_file() or resolved.suffix.lower() not in suffixes:
        raise FfmpegVideoError(invalid_code, f"asset {asset_id} has an unsupported file type")
    size_limit = MAX_IMAGE_BYTES if kind == "image" else MAX_AUDIO_BYTES
    if resolved.stat().st_size <= 0 or resolved.stat().st_size > size_limit:
        raise FfmpegVideoError(invalid_code, f"asset {asset_id} violates the file-size limit")
    return resolved


def _probe_asset(path: Path, kind: Literal["image", "audio"], asset_id: str) -> dict[str, float | int]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FfmpegVideoError("ffprobe_failed", "ffprobe is unavailable")
    try:
        result = _run([
            ffprobe, "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,duration,width,height,sample_rate,channels",
            "-of", "json", str(path),
        ], timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FfmpegVideoError("ffprobe_failed", f"ffprobe could not inspect asset {asset_id}") from exc
    invalid_code: VideoErrorCode = "invalid_image" if kind == "image" else "invalid_audio"
    if result.returncode != 0:
        raise FfmpegVideoError(invalid_code, f"asset {asset_id} is not valid {kind} media")
    try:
        payload = json.loads(result.stdout)
        streams = payload.get("streams", [])
        if kind == "image":
            stream = next(item for item in streams if item.get("codec_type") == "video")
            width = int(stream["width"])
            height = int(stream["height"])
            return {"width": width, "height": height}
        stream = next(item for item in streams if item.get("codec_type") == "audio")
        duration_value = payload.get("format", {}).get("duration") or stream.get("duration")
        duration = float(duration_value)
        sample_rate = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FfmpegVideoError(invalid_code, f"asset {asset_id} has incomplete media metadata") from exc
    if not math.isfinite(duration) or duration < 0.05 or duration > MAX_DURATION_SECONDS or sample_rate <= 0 or channels <= 0:
        raise FfmpegVideoError("invalid_audio", f"audio asset {asset_id} has abnormal duration or stream metadata")
    return {"duration": duration, "sample_rate": sample_rate, "channels": channels}


def _copy_verified_inputs(
    project_root: Path,
    workdir: Path,
    plan: CompiledVideoExecutionPlan,
) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []
    for index, segment in enumerate(plan.segments):
        visual = _resolve_asset(project_root, segment.visual_path, "image", segment.visual_asset_id)
        audio = _resolve_asset(project_root, segment.audio_path, "audio", segment.audio_asset_id)
        visual_record, audio_record = plan.source_assets[index * 2:index * 2 + 2]
        if visual.stat().st_size != visual_record.size_bytes or audio.stat().st_size != audio_record.size_bytes:
            raise FfmpegVideoError("unsafe_path", f"source asset size changed after compilation for segment {segment.segment_id}")
        visual_name = f"input-{index:03d}-visual{visual.suffix.lower()}"
        audio_name = f"input-{index:03d}-audio{audio.suffix.lower()}"
        shutil.copyfile(visual, workdir / visual_name)
        shutil.copyfile(audio, workdir / audio_name)
        if _sha256(workdir / visual_name) != segment.visual_sha256 or _sha256(workdir / audio_name) != segment.audio_sha256:
            raise FfmpegVideoError("unsafe_path", f"source asset changed after compilation for segment {segment.segment_id}")
        copied.append((visual_name, audio_name))
    return copied


def _stage_subtitle_font(workdir: Path, font: SubtitleFontCapability) -> None:
    source = Path(font.file)
    suffix = source.suffix.lower()
    if suffix not in {".otf", ".ttf", ".ttc"}:
        raise FfmpegVideoError("ffmpeg_failed", "selected CJK subtitle font has an unsupported file type")
    font_dir = workdir / "fonts"
    font_dir.mkdir()
    staged = font_dir / f"subtitle-font{suffix}"
    try:
        shutil.copyfile(source, staged)
    except OSError as exc:
        raise FfmpegVideoError("ffmpeg_failed", "selected CJK subtitle font cannot be staged") from exc
    if _sha256(staged) != font.sha256:
        raise FfmpegVideoError("ffmpeg_failed", "selected CJK subtitle font changed after capability probing")


def _validate_compiled_plan(plan: CompiledVideoExecutionPlan) -> None:
    """Fail closed when a caller constructs a typed plan instead of using the compiler."""

    if len(plan.segments) != len(plan.subtitle_cues) or len(plan.source_assets) != len(plan.segments) * 2:
        raise FfmpegVideoError("invalid_video_plan", "compiled segment, subtitle, and provenance counts differ")
    cursor = 0.0
    expected_assets: list[tuple[str, str, str, str, str]] = []
    for segment, cue in zip(plan.segments, plan.subtitle_cues, strict=True):
        calculated_duration = round(
            segment.audio_duration_seconds + segment.leading_padding_seconds + segment.trailing_padding_seconds,
            6,
        )
        if (
            abs(segment.timeline_start_seconds - cursor) > 0.001
            or abs(segment.duration_seconds - calculated_duration) > 0.001
            or abs(segment.timeline_end_seconds - (cursor + calculated_duration)) > 0.001
            or cue.segment_id != segment.segment_id
            or cue.start_seconds < segment.timeline_start_seconds
            or cue.end_seconds > segment.timeline_end_seconds + 0.001
        ):
            raise FfmpegVideoError("invalid_video_plan", f"compiled timeline is invalid for segment {segment.segment_id}")
        expected_assets.extend([
            (segment.segment_id, "image", segment.visual_asset_id, segment.visual_path, segment.visual_sha256),
            (segment.segment_id, "audio", segment.audio_asset_id, segment.audio_path, segment.audio_sha256),
        ])
        cursor = segment.timeline_end_seconds
    actual_assets = [(item.segment_id, item.kind, item.asset_id, item.path, item.sha256) for item in plan.source_assets]
    if actual_assets != expected_assets or abs(plan.total_duration_seconds - cursor) > 0.001:
        raise FfmpegVideoError("invalid_video_plan", "compiled provenance or total duration is inconsistent")
    _webvtt_bytes(plan.subtitle_cues)


def _render_segment(
    executable: str,
    workdir: Path,
    segment: CompiledTeachingVideoSegment,
    inputs: tuple[str, str],
    output_name: str,
) -> None:
    visual_filter = {
        "scale_contain_pad": (
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=white,format=yuv420p"
        ),
        "scale_cover_crop": (
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},format=yuv420p"
        ),
    }[segment.fit_operation]
    delay_ms = round(segment.leading_padding_seconds * 1000)
    audio_filter = (
        f"aresample={AUDIO_SAMPLE_RATE},adelay={delay_ms}:all=1,"
        f"apad=pad_dur={segment.trailing_padding_seconds:.6f}"
    )
    _run_ffmpeg_checked(executable, [
        "-loop", "1", "-framerate", str(FRAME_RATE), "-i", inputs[0], "-i", inputs[1],
        "-map", "0:v:0", "-map", "1:a:0", "-vf", visual_filter, "-af", audio_filter,
        "-t", f"{segment.duration_seconds:.6f}", "-r", str(FRAME_RATE),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
        "-map_metadata", "-1", "-movflags", "+faststart", output_name,
    ], workdir, f"segment:{segment.segment_id}")


def _run_ffmpeg_checked(executable: str, arguments: list[str], workdir: Path, stage: str) -> None:
    command = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *arguments]
    try:
        result = _run(command, timeout=PROCESS_TIMEOUT_SECONDS, cwd=workdir)
    except subprocess.TimeoutExpired as exc:
        raise FfmpegVideoError("ffmpeg_failed", f"FFmpeg timed out during {stage}") from exc
    if result.returncode != 0:
        detail = _safe_process_detail(result.stderr, workdir)
        raise FfmpegVideoError("ffmpeg_failed", f"FFmpeg failed during {stage}: {detail}")


def _verify_video(path: Path, planned_duration: float, ffprobe: str) -> dict[str, int | float | str]:
    try:
        result = _run([
            ffprobe, "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,pix_fmt,sample_rate,channels,r_frame_rate",
            "-of", "json", str(path),
        ], timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FfmpegVideoError("ffprobe_failed", "ffprobe could not verify the generated artifact") from exc
    if result.returncode != 0:
        raise FfmpegVideoError("ffprobe_failed", "ffprobe rejected the generated artifact")
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next(item for item in streams if item.get("codec_type") == "audio")
        duration = float(payload["format"]["duration"])
        width = int(video["width"])
        height = int(video["height"])
        sample_rate = int(audio["sample_rate"])
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FfmpegVideoError("artifact_verification_failed", "generated video metadata is incomplete") from exc
    valid = (
        video.get("codec_name") == "h264"
        and audio.get("codec_name") == "aac"
        and video.get("pix_fmt") == "yuv420p"
        and video.get("r_frame_rate") == f"{FRAME_RATE}/1"
        and width == VIDEO_WIDTH
        and height == VIDEO_HEIGHT
        and sample_rate == AUDIO_SAMPLE_RATE
        and int(audio.get("channels") or 0) == 2
        and 0 < duration <= MAX_DURATION_SECONDS + 0.25
        and abs(duration - planned_duration) <= 0.75
    )
    if not valid:
        raise FfmpegVideoError("artifact_verification_failed", "generated video violates the fixed recipe")
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": "h264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
        "audio_sample_rate": sample_rate,
    }


def _webvtt_bytes(cues: list[CompiledSubtitleCue]) -> bytes:
    lines = ["WEBVTT", ""]
    previous_end = 0.0
    for cue in cues:
        if cue.start_seconds < 0 or cue.end_seconds <= cue.start_seconds or cue.start_seconds < previous_end:
            raise FfmpegVideoError("subtitle_validation_failed", "subtitle cue timing is invalid")
        if any(_contains_forbidden_control(value) for value in (cue.speaker_id, cue.chinese, cue.translation or "")):
            raise FfmpegVideoError("subtitle_validation_failed", "subtitle text contains a forbidden control character")
        if any(_contains_webvtt_structure(value) for value in (cue.chinese, cue.translation or "")):
            raise FfmpegVideoError("subtitle_validation_failed", "subtitle text contains forbidden WebVTT structure")
        text_lines = [f"{html.escape(cue.speaker_id)}：{html.escape(cue.chinese)}"]
        if cue.translation:
            text_lines.append(html.escape(cue.translation))
        lines.extend([
            str(cue.index),
            f"{_vtt_time(cue.start_seconds)} --> {_vtt_time(cue.end_seconds)}",
            *text_lines,
            "",
        ])
        previous_end = cue.end_seconds
    payload = "\n".join(lines).encode("utf-8")
    if len(payload) > MAX_SUBTITLE_BYTES:
        raise FfmpegVideoError("subtitle_validation_failed", "subtitle output exceeds the controlled size limit")
    return payload


def _verify_webvtt(path: Path, expected_cues: int) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FfmpegVideoError("subtitle_validation_failed", "subtitle output is not valid UTF-8") from exc
    timings = re.findall(r"^(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3})$", text, re.MULTILINE)
    if not text.startswith("WEBVTT\n") or len(timings) != expected_cues:
        raise FfmpegVideoError("subtitle_validation_failed", "subtitle output is not valid WebVTT")


def _vtt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _contains_forbidden_control(value: str) -> bool:
    return bool(_CONTROL_PATTERN.search(value)) or any(
        unicodedata.category(character) in {"Cc", "Cs"} and character not in {"\n", "\t"}
        for character in value
    )


def _contains_webvtt_structure(value: str) -> bool:
    return "-->" in value or any(not line.strip() for line in value.splitlines())


def _compiled_plan_hash(plan: CompiledVideoExecutionPlan) -> str:
    return _stable_hash(plan.model_dump(mode="json", exclude={"plan_sha256"}))


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _version(output: str, executable: str) -> str:
    first_line = output.splitlines()[0] if output else ""
    match = re.search(rf"{executable} version\s+([^\s]+)", first_line)
    return match.group(1) if match else "unknown"


def _has_codec(output: str, codec: str) -> bool:
    return bool(re.search(rf"^\s*\S{{6}}\s+{re.escape(codec)}\s", output, re.MULTILINE))


def _probe_subtitle_font() -> tuple[SubtitleFontCapability | None, str | None]:
    configured_path = os.environ.get("HCS_CJK_FONT_PATH", "").strip()
    configured_family = os.environ.get("HCS_CJK_FONT_FAMILY", "").strip()
    if configured_path:
        font_path = Path(configured_path).expanduser()
        family = configured_family or font_path.stem
        selection: Literal["configured", "fontconfig"] = "configured"
    else:
        fontconfig = shutil.which("fc-match")
        if not fontconfig:
            return None, "cjk_font_probe_unavailable"
        try:
            result = _run(
                [fontconfig, "--format", "%{family[0]}|%{file}\n", ":charset=4e2d"],
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None, "cjk_font_probe_failed"
        if result.returncode != 0 or not result.stdout.strip() or "|" not in result.stdout:
            return None, "cjk_font_not_found"
        family, raw_path = result.stdout.splitlines()[0].split("|", 1)
        font_path = Path(raw_path)
        selection = "fontconfig"
    if not family or not _SAFE_FONT_FAMILY.fullmatch(family):
        return None, "cjk_font_family_unsupported"
    try:
        resolved = font_path.resolve(strict=True)
    except (OSError, FileNotFoundError):
        return None, "cjk_font_not_found"
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        return None, "cjk_font_not_found"
    return SubtitleFontCapability(
        family=family,
        file=str(resolved),
        file_name=resolved.name,
        sha256=_sha256(resolved),
        selection=selection,
    ), None


def _safe_process_detail(stderr: str, workdir: Path) -> str:
    detail = (stderr or "no diagnostic output")[-2000:]
    return detail.replace(str(workdir), "<workdir>").replace("\n", " ")


def _run(
    command: list[str],
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
