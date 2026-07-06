# Release Notes: HanClassStudio v0.1 Demo Ready

HanClassStudio v0.1 is a local-first, demo-ready version of an agent-compatible interactive courseware pipeline for international Chinese teaching.

## Demo-Ready Capabilities

- Upload PPTX/PDF source material.
- Parse source material into project artifacts.
- Confirm lesson profile before generation.
- Generate lesson spec, spec lock, blueprint, interaction plan, and media plan.
- Generate placeholder media for local demo use.
- Render slide-based offline `lesson.html`.
- Run a stateful quality gate.
- Export a ZIP package with HTML, assets, canonical data, quality report, and manifest.
- Generate Agent Handoff task/rules files.
- Validate external Agent artifact edits.
- Inspect artifacts from the frontend workbench.

## Completed Modules

- FastAPI backend.
- React workbench frontend.
- Artifact-first workspace.
- Lesson strategist and spec lock.
- Component registry.
- Blueprint/media/render pipeline.
- Quality gate and export policy.
- Offline HTML runtime.
- Agent Skill Layer.
- Agent Handoff panel and API.
- Golden sample and smoke tests.
- Portfolio/demo documentation.

## Known Limitations

- No real LLM provider is connected by default.
- No real ComfyUI/image provider is connected by default.
- No real TTS provider is connected by default.
- Video generation is not implemented in v0.1.
- Placeholder media is expected.
- Runtime themes are fixed.
- Project storage is local and development-oriented.
- Quality gate is demo-grade coverage.

## Next Version Plan

- Provider integrations for LLM, image, TTS, OCR, and video.
- Template discovery and multiple runtime themes.
- Better visual editing for blueprints and components.
- Streaming pipeline status.
- Stronger teacher review gates.
- Project versioning and recovery.
- More classroom interaction components.
- Export options for LMS-oriented delivery.

