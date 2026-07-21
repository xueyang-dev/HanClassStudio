# Provider Hub Phase 2A: Controlled FFmpeg Teaching Video Contract

Phase 2A adds one backend-only, offline path for turning approved local lesson
assets into a small dialogue video. It is a media compiler, not a video editor
and not a pedagogical decision maker.

```text
TeachingVideoPlan
→ validate asset references and probe real media
→ CompiledVideoExecutionPlan
→ fixed FFmpeg execution and ffprobe verification
→ VerifiedVideoArtifact + WebVTT
```

The existing provider-neutral `video_generation_requests.json` remains a
planning artifact. It is not automatically executed by this capability.

## Domain contracts

### TeachingVideoPlan

`TeachingVideoPlan` is the caller-facing contract. It contains a version, a
stable video ID, a title, an ordered list of segments, and a fixed output
recipe. Each `TeachingVideoSegment` identifies the speaker, Chinese line,
optional translation, visual and audio asset IDs and project-relative paths,
fit mode, subtitle mode, and padding policy.

```json
{
  "schema_version": 1,
  "video_id": "cafe-ordering-dialogue",
  "title": "在咖啡馆点餐",
  "segments": [
    {
      "segment_id": "cafe-1",
      "speaker_id": "customer",
      "chinese": "你好，我要一杯咖啡。",
      "translation": "Hello, I'd like a cup of coffee.",
      "audio_asset_id": "cafe-audio-1",
      "audio_path": "assets/audio/line-1.wav",
      "visual_asset_id": "cafe-visual-1",
      "visual_path": "assets/images/customer-wide.png",
      "fit_mode": "contain",
      "subtitle_mode": "bilingual",
      "duration_policy": "match_audio",
      "leading_padding_seconds": 0.05,
      "trailing_padding_seconds": 0.05
    }
  ],
  "output": {
    "recipe_id": "hcs_teaching_video_720p_v1",
    "transition": "hard_cut",
    "subtitles": {
      "format": "webvtt",
      "burn_in": true,
      "include_translation": true
    }
  }
}
```

Callers do not provide FFmpeg executables, arguments, filter graphs, codecs,
output paths, dimensions, or arbitrary durations.

### CompiledVideoExecutionPlan

The compiler resolves project-owned inputs, probes their metadata, hashes them,
calculates the segment and subtitle timelines, and emits a serializable typed
plan. The plan records only closed operations such as
`scale_contain_pad`, `scale_cover_crop`, `resample_delay_pad`, and
`render_segments_concat_burn_webvtt`. The executor derives its fixed argument
arrays from these enums.

The compiled plan has stable input ordering and two hashes:

- `source_plan_sha256` hashes normalized `TeachingVideoPlan` JSON;
- `plan_sha256` hashes the compiled structure, probed durations, ordered asset
  hashes, subtitle cues, recipe, and controlled output identities.

The executor rechecks the plan hash, timeline, provenance ordering, asset paths,
and source hashes before running.

### VerifiedVideoArtifact

Successful execution returns the video and subtitle paths, recipe, actual
duration, canvas, codecs, output hashes, plan hash, warnings, and full
`VideoArtifactProvenance`. Provenance includes:

- source plan and compiled plan SHA-256;
- every segment ID;
- every image/audio asset ID, project-relative path, size, and SHA-256;
- recipe ID and version;
- FFmpeg and ffprobe versions;
- output MP4 and WebVTT SHA-256;
- actual duration and 1280×720 canvas;
- verified video codec, audio codec, pixel format, and audio sample rate.

Stable provenance never uses an absolute machine path as an asset identity.

## Duration and timeline

Every Phase 2A segment requires audio and uses `duration_policy=match_audio`:

```text
ffprobe audio duration
+ leading padding (0–2 seconds)
+ trailing padding (0–2 seconds)
= segment duration
```

The caller cannot assert an unverified media duration. Empty, corrupt,
metadata-free, shorter-than-50ms, or longer-than-five-minute audio fails closed.
The compiled sum, including padding, cannot exceed 300 seconds. Segment audio
is normalized to 48 kHz stereo AAC, so input sample-rate and channel differences
do not change the output contract.

Subtitle cues cover the actual audio window: they start after leading padding
and end when the probed audio duration ends. Segment order defines both the
media and subtitle order.

## Image fit

Phase 2A supports two fit operations without distortion:

- `contain` scales the whole image inside 1280×720 and adds white padding;
- `cover` scales until the canvas is filled and center-crops overflow.

Landscape, portrait, and square fixture images are covered by the real sample.
`smart_crop` is represented in the request schema only so the compiler can
return the stable `unsupported_fit_mode` error; it is never silently downgraded.

## Subtitles

The compiler produces UTF-8 WebVTT, burns the same cue timeline into the MP4
through FFmpeg's `subtitles` filter, and publishes the `.vtt` beside the video.
Each cue contains the speaker ID, Chinese line, and optional English translation.

Subtitle safety is deliberately narrow:

- CRLF and CR are normalized to LF;
- invalid control characters and excessive line/text sizes are rejected;
- blank cue lines and the WebVTT timing delimiter are rejected inside text;
- cue ranges must be positive, ordered, and non-overlapping;
- WebVTT text is HTML-escaped;
- output size is capped at 128 KiB;
- subtitle paths are derived from the validated video ID;
- user text is written to a UTF-8 file and is never placed in a shell command or
  FFmpeg filter graph.

This is not an ASS styling editor.

## Fixed recipe

`hcs_teaching_video_720p_v1` fixes:

| Property | Value |
|---|---|
| Canvas | 1280×720 |
| Frame rate | 30 fps |
| Video | H.264 via `libx264`, CRF 20, medium preset |
| Pixel format | `yuv420p` |
| Audio | AAC 128 kbps, 48 kHz, stereo |
| Container | MP4 with `faststart` |
| Maximum duration | 300 seconds |
| Subtitle output | UTF-8 WebVTT and burn-in |
| Default transition | `hard_cut` |

`short_crossfade` is reserved in the domain enum but currently returns
`unsupported_transition`. It is not approximated with an unstable filter graph.

## Café dialogue fixture

The integration test generates a six-segment “在咖啡馆点餐” fixture:

1. 顾客：你好，我要一杯咖啡。
2. 店员：好的，您要热的还是冰的？
3. 顾客：我要一杯热咖啡，谢谢。
4. 店员：好的，一共二十元。
5. 顾客：给你。
6. 店员：谢谢，请稍等。

English translations are fixed test strings. Three tiny PNGs are generated in
landscape, portrait, and square ratios. Six WAV files use distinct synthetic
tones and mixed mono/stereo sample formats. They are test fixtures, not TTS,
AI images, a claim of natural speech, or final classroom-quality media. All
files live under pytest temporary directories and are removed after the test.

## Error model

The stable error codes are:

```text
invalid_video_plan
missing_visual_asset
missing_audio_asset
invalid_image
invalid_audio
unsupported_fit_mode
unsupported_transition
subtitle_validation_failed
duration_limit_exceeded
ffmpeg_failed
ffprobe_failed
artifact_verification_failed
unsafe_path
output_conflict
cancelled
internal_error
```

Errors identify a stage or asset ID without returning an argv array, user-
injected command, or unnecessary absolute path.

## Safety boundary

- `subprocess.run` receives argument arrays and uses the default `shell=False`.
- Executables are resolved locally with `shutil.which`; callers cannot select
  them.
- FFmpeg must expose `libx264`, AAC, and the libass-backed `subtitles` filter.
- Images are limited to 25 MiB each, audio to 50 MiB each, all unique inputs to
  200 MiB, subtitles to 128 KiB, and plans to 24 segments / 300 seconds.
- Inputs must resolve inside `assets/images/` or `assets/audio/`; absolute paths,
  traversal, unsupported extensions, and symlink escapes fail closed.
- After compile-time hashing, each source is copied to a private work directory
  and the copy is rehashed before FFmpeg opens it. This closes ordinary
  probe-to-execute replacement races. A hostile process with write access to
  the private work directory remains outside the current threat model.
- A per-output exclusive lock prevents concurrent generation of the same ID.
  A process crash may leave a conservative stale lock requiring manual removal.
- Intermediate media and subtitles live in one temporary directory and are
  removed on failure.
- Verified outputs are published with non-overwriting hard links. If the second
  publication fails, the first is removed.
- Existing outputs are never overwritten.
- No archive is accepted, downloaded, or unpacked; no runtime, model, provider
  script, or third-party media is fetched or executed.

## Verification and determinism

ffprobe verifies the final artifact has video and audio streams, H.264/AAC,
1280×720, 30 fps, `yuv420p`, 48 kHz stereo audio, a positive duration within
the recipe limit, and reasonable agreement with the compiled timeline. WebVTT
is independently decoded as UTF-8 and checked for cue count and timing syntax.

The normalized source and compiled plan hashes are deterministic for the same
plan, probed metadata, and asset bytes. Segment order and content structure are
reproducible. MP4 byte hashes are recorded for the produced artifact but are
not promised to match across FFmpeg builds, operating systems, or platforms.

Run the focused and complete backend checks from the repository root:

```bash
uv run --project apps/api pytest apps/api/tests/test_ffmpeg_video.py -q
uv run --project apps/api pytest apps/api/tests -q
```

If FFmpeg, ffprobe, required encoders, or the subtitle filter is unavailable,
real integration cases skip with the blocker named. A skip is not a successful
execution claim.

## Not implemented

Phase 2A does not implement UI, Provider Hub UI changes, asset-manifest
integration, lesson-plan automatic execution, external TTS, AI image generation,
lip synchronization, a multitrack editor, arbitrary filters, custom resolution,
real Provider installation, FFmpeg installation, ZIP/TAR input, ComfyUI, or
cross-platform byte-identical MP4 output.
