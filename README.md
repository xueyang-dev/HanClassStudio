# HanClassStudio

AI-powered interactive HTML courseware generator for international Chinese teaching.

This v0.1 implementation is a local-first portfolio demo. It runs a teacher-facing web app and a FastAPI backend that can parse PPTX/PDF materials, generate a structured lesson blueprint with placeholder AI providers, render offline-ready HTML courseware, run quality checks, and export a ZIP package.

## v0.1 Demo Status

HanClassStudio v0.1 is demo ready:

- WebUI workbench loop is complete.
- Agent Skill Layer and Agent Handoff are implemented.
- Artifact Inspector exposes project outputs, including `agent/`.
- `lesson.html` runtime is slide-based and offline-ready.
- Quality gate, export policy, and ZIP verification are covered by tests.
- Current test target: `npm test`.

## Quick Start

```bash
npm install
npm run install:web
uv sync --project apps/api
```

Run the backend:

```bash
npm run dev:api
```

Run the frontend in another terminal:

```bash
npm run dev:web
```

Open the Vite URL, upload a PPTX, and follow the five-step workflow.

## Local Commands

Backend:

```bash
npm run dev:api
```

Frontend:

```bash
npm run dev:web
```

Tests and build:

```bash
npm test
```

## Scripts

- `npm run dev:api` starts FastAPI at `http://localhost:8000`.
- `npm run dev:web` starts the authoring app at `http://localhost:5173`.
- `npm run test:api` runs backend tests.
- `npm run build:web` type-checks and builds the React app.
- `npm test` runs the backend test suite and frontend build.

## Output Package

Each generated ZIP contains:

```text
lesson.html
assets/
  images/
  audio/
  video/
  fonts/
  data/
    lesson_profile.json
    source_material.json
    lesson_blueprint.json
    interaction_plan.json
    media_plan.json
    asset_manifest.json
    quality_report.json
    attribution.json
quality_summary.md
export_manifest.json
```

The exported `lesson.html` is designed to open offline after unzipping.

## Demo Documentation

- [v0.1 demo guide](docs/demo-v0.1.md)
- [Architecture overview](docs/architecture-overview.md)
- [Agent workflow](docs/agent-workflow.md)
- [3-5 minute demo script](docs/demo-script.md)
- [Portfolio copy](docs/portfolio-copy.md)
- [Screenshot checklist](docs/screenshot-checklist.md)
- [Demo recording checklist](docs/demo-recording-checklist.md)
- [v0.1 release notes](docs/release-notes-v0.1.md)

## Current Limitations

- Real LLM, image, TTS, OCR, and video providers are not connected by default.
- Placeholder media is expected in the v0.1 demo.
- Runtime themes are fixed templates, not user-authored CSS.
- Quality checks are practical v0.1 gates, not a full instructional design review.
- Existing `runtime/projects` data is treated as disposable development output.
