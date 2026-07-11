# Greetings Pilot Review Checkpoint

Status: **Needs one focused revision** and teacher visual review. This is not a production-readiness claim.

## Real run

- Provider contract: `experimental_openai_images`
- Endpoint: `https://api.siliconflow.cn/v1/images/generations`
- Model: `Qwen/Qwen-Image`
- Raster calls: 4
- Raster stage latency: 110.54 seconds total
- Generation/download success: 4/4
- SVG fallback: 0/4
- Output: four local PNG files, each 1536×864
- Editable PPTX: four embedded raster media files
- ZIP/export: local assets present; no SiliconFlow asset URL retained
- Cost/free-credit usage: not exposed by the generation response; check the account ledger

## Human review required

- `teacher_greeting`: pending
- `polite_contrast`: pending; technical pre-check found that the peer-versus-teacher contrast is not visually explicit
- `morning_greeting`: pending
- `goodbye_scene`: pending; technical pre-check found that it can read as classroom hand-raising rather than goodbye

All four backgrounds should also be checked for faint pseudo-text marks.

## Courseware findings

- Chinese, pinyin, and English target strings are covered by a focused fixture test.
- Existing `VocabularyFlipCard`, `ListenAndChoose`, and `MatchGame` components are used; no new interaction mode was added.
- Desktop HTML at 1440px has 131px horizontal overflow.
- Mobile HTML at 390px retains a 1280px slide and clips content; mobile readability is not ready.
- Listening audio remains a placeholder tone and is not ready for a real self-study verdict.
- Teacher review/replacement can be completed through the project-local review endpoint without editing JSON or code.

## Local artifacts

After running the builder, inspect:

- `runtime/projects/greetings_raster_pilot/courseware/lesson.html`
- `runtime/projects/greetings_raster_pilot/assets/data/asset_manifest.json`
- `runtime/projects/greetings_raster_pilot/diagnostics/teacher_media_review/index.html`
- `runtime/projects/greetings_raster_pilot/diagnostics/pilot_report.json`
- the latest `.pptx` and `.zip` under `runtime/projects/greetings_raster_pilot/exports/`

The pilot must not merge until the four images receive explicit teacher review states and the focused mobile/audio issues are resolved or consciously accepted for the intended classroom-only scope.
