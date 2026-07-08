# HanClassStudio

**v0.2.2-alpha binding-layer MVP. Not production-ready.**

AI-powered interactive HTML courseware generator for international Chinese teaching.

专门用于国际中文教育课件制作的开源 skills、workflow 与互动课件生成 demo。

This implementation is a local-first portfolio demo. It runs a teacher-facing web app and a FastAPI backend that can parse PPTX/PDF materials, generate structured lesson artifacts, build a State-Evidence teaching kernel, render offline-ready HTML courseware, run quality checks, export a ZIP package, and generate an editable PPTX classroom version.

## Screenshots And GIF

Portfolio placeholders:

- Workbench upload/profile flow screenshot.
- Pipeline + Quality + Artifact Inspector screenshot.
- Slide-based `lesson.html` runtime GIF.
- Agent Handoff panel screenshot.
- Editable PPTX export screenshot.

## Current Status

HanClassStudio has moved beyond the original v0.1 export demo into a **State-first courseware pipeline**.

- **v0.1 demo loop**: verified local workbench, artifact pipeline, offline HTML export, editable PPTX export, Agent Handoff, and quality gates.
- **v0.2.1-alpha**: State-Evidence Kernel smoke-tested and closed with `70 passed, 1 warning`.
- **v0.2.2 white paper**: [State-Evidence Kernel architecture](docs/state-evidence-kernel-v0.2.2.md) defines the long-term teaching kernel model.
- **v0.2.2-alpha**: `presentation/activity_bindings.json` adds a formal activity/evidence/presentation contract between the kernel and HTML/PPTX renderers.

## v0.1 Demo Status

HanClassStudio v0.1 engineering pipeline is verified. Classroom/debug separation is complete; current demo blockers are now lesson-content quality issues rather than export-pipeline failures.

### Engineering Pipeline — Verified ✅

- WebUI workbench loop is complete.
- Agent Skill Layer and Agent Handoff are implemented.
- Artifact Inspector exposes project outputs, including `agent/` and `exports/`.
- `lesson.html` runtime is slide-based and offline-ready.
- Editable PPTX export is available as a second export target.
- Quality gate, export policy, and ZIP verification are covered by tests.
- Current test target: `npm test`.

### Classroom Mode Strictness — Completed ✅

Classroom mode rendering and export are fully separated from debug mode with final artifact hardening:

- **HTML classroom artifact**: dedicated `lesson_classroom.html` generated alongside debug `lesson.html` during pipeline. Embedded `lesson-data` JSON is sanitized — image_prompt, provider_required, and debug fields are redacted. Arabic text is separated from Chinese content. Slide-kicker DOM and debug footer are absent.
- **ZIP export**: classroom HTML included alongside debug HTML in the export bundle.
- **PPTX classroom mode**: `provider_required` text excluded; missing media shows lightweight decorator; classroom QA `blocked` prevents normal export (force export creates `Diagnostic` files).
- **Scaffold separation**: Chinese text and Arabic scaffold are strictly separated. Arabic Unicode ranges are stripped from Chinese content blocks.
- **Route-relevant filtering**: `greeting_lesson` grammar whitelisted; vocabulary filtered.
- **Tests**: 44 tests covering HTML sanitization, lesson-data redaction, Arabic separation, PPTX classroom QA, and pipeline integration.

### Lesson Strategist Upgrade — Completed ✅

The Lesson Strategist now uses Teaching Candidate Extraction (`analysis/teaching_candidates.json`)
to drive smarter blueprint generation:

- **Route hints**: `greeting_lesson`, `vocabulary_lesson`, `dialogue_lesson`, `character_lesson`,
  `grammar_pattern_lesson`, `mixed_lesson` — each produces a tailored slide structure.
- **Vocabulary classification**: core vocabulary, secondary vocabulary, and noise candidates
  based on frequency, position in dialogues, and pinyin proximity.
- **Grammar detection**: recognises "在+V+呢", "V+了", "sb.+喜欢+n/v" etc. from source patterns
  instead of hard-coded defaults.
- **Dialogue extraction**: detects "A：... B：..." structures from source text.
- **Content leak prevention**: vocabulary no longer contains noise words (stroke names, framework
  terms) or placeholder text. Arabic scaffolds are marked `provider_required` rather than forged.

See [architecture-overview.md](docs/architecture-overview.md) for details on the extraction
pipeline and [test-report-v0.1.md](docs/test-report-v0.1.md) for test coverage.

### Syllabus-Aware Comprehensible Input Engine — Completed ✅

The Syllabus Engine puts textbook scope + learner level + i+1 at the center of generation:

- **SourceLessonProfile**: extracts structured units (dialogue, vocabulary, grammar, exercise, teacher instruction, noise) from source material.
- **DifficultyProfile**: infers lesson difficulty from source content (greeting signals, pinyin presence, character count) mapped to standard schemes (HSK1, etc.).
- **LanguageInventory**: classifies items into known, target, support, off-level, teacher-only, excluded — only target items enter learner-facing text.
- **AllowedTextPlan**: per-slide allowed/forbidden target text, max new items, teacher-only zones.
- **OffLevelReport**: checks final HTML/PPTX for unknown items, off-level items, unsupported new items, teacher text leaks, and missing scaffolds.
- **i+1 for zero_beginner**: max 1 new target item per slide, no "我会说"/"朋友之间" templates, no output before input.
- **Tests**: 58 tests covering syllabus extraction, difficulty inference, allowed text planning, off-level detection, and pipeline integration.

### State-Evidence Kernel — v0.2.1-alpha Verified ✅

The State-Evidence Kernel makes the teaching logic explicit before presentation rendering:

```text
Source
  -> Learning State Plan
  -> Evidence Plan
  -> Activity Plan
  -> Evidence Alignment Report
  -> Presentation / HTML / PPTX
```

Current generated artifacts:

- `learning/learning_state_plan.json`: state DAG, learning goals, and transitions.
- `learning/evidence_plan.json`: evidence specs for state transitions.
- `learning/activity_plan.json`: learning activities that collect evidence.
- `quality/evidence_alignment_report.json`: Goal-Evidence-Activity alignment gate.

Alignment `blocked` now stops classroom render/export and writes a kernel diagnostic ZIP. See [smoke-test-v0.2.1.md](docs/smoke-test-v0.2.1.md) for the latest validation report.

### What Works Today

- PPTX/PDF upload and parsing.
- Course profile confirmation.
- Artifact-first spec/blueprint/media/render pipeline.
- Component registry-backed interactive runtime.
- HTML ZIP export for offline interactive courseware.
- Editable PPTX export for editable classroom display material.
- State-Evidence Kernel artifacts and alignment gate.
- Evidence-aware classroom HTML data and PPTX deck speaker notes.
- Agent Handoff task/rules generation and validation.
- Quality gate with `pass`, `warning`, and `blocked` states.

## What Is Placeholder Or In Progress

- LLM generation can fall back to deterministic local blueprint generation.
- Images use local placeholder SVGs unless a provider is configured later.
- Audio uses local demo tones unless a TTS provider is configured later.
- Video is planning/fallback only.
- Editable PPTX converts interactions into static classroom activity pages.
- Evidence-to-slide fallback matching is centralized in `presentation/activity_bindings.json`; low-confidence bindings still need future teacher confirmation UX.
- Real PPTX speaker-note XML inspection is not yet part of the smoke test.

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

The main output is an interactive HTML ZIP. Each generated ZIP contains:

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

Editable PPTX export creates:

```text
exports/HanClassStudio_Editable_<timestamp>.pptx
exports/pptx_export_manifest.json
quality/pptx_quality_report.json
```

The PPTX version is editable classroom display material. HTML interactions are converted into static classroom activity pages.

## Demo Documentation

- [v0.1 demo guide](docs/demo-v0.1.md)
- [Architecture overview](docs/architecture-overview.md)
- [State-Evidence Kernel white paper](docs/state-evidence-kernel-v0.2.2.md)
- [Presentation bindings v0.2.2](docs/presentation-bindings-v0.2.2.md)
- [v0.2.1 smoke test report](docs/smoke-test-v0.2.1.md)
- [Agent workflow](docs/agent-workflow.md)
- [3-5 minute demo script](docs/demo-script.md)
- [Portfolio copy](docs/portfolio-copy.md)
- [Screenshot checklist](docs/screenshot-checklist.md)
- [Demo recording checklist](docs/demo-recording-checklist.md)
- [v0.1 release notes](docs/release-notes-v0.1.md)
- [Release checklist](docs/release-checklist.md)
- [GitHub Releases](https://github.com/xueyang-dev/HanClassStudio/releases)

## Current Limitations

- Real LLM, image, TTS, OCR, and video providers are not connected by default.
- Placeholder media is expected in the v0.1 demo.
- Runtime themes are fixed templates, not user-authored CSS.
- Quality checks now include State-Evidence alignment and presentation binding; low-confidence binding review is still being hardened.
- Existing `runtime/projects` data is treated as disposable development output.
