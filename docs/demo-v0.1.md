# HanClassStudio v0.1 Demo

HanClassStudio is an AI-assisted interactive courseware generation system for international Chinese teaching. It turns source lesson material into a structured, inspectable project workspace, then renders slide-based offline HTML courseware with interaction components, language scaffolding, quality checks, and ZIP export.

The v0.1 demo is local-first and portfolio-oriented. It proves the product workflow and architecture without connecting real LLM, image, TTS, or video providers.

## What v0.1 Can Do

- Upload PPTX or PDF teaching material.
- Parse source pages into `sources/source_material.json`.
- Confirm a course profile for learner level, target students, lesson mode, and scaffolding language.
- Generate `lesson_spec.md`, `spec_lock.json`, `lesson_blueprint.json`, `interaction_plan.json`, and `media_plan.json`.
- Render a slide-based `courseware/lesson.html` runtime.
- Support interactive components:
  - `AudioButton`
  - `VocabularyFlipCard`
  - `SentenceDragBuilder`
  - `ListenAndChoose`
  - `MatchGame`
  - `CharacterFormation`
- Switch runtime language display between Chinese, scaffolding hints, and bilingual mode.
- Run a quality gate before export.
- Export an offline ZIP package with HTML, assets, data artifacts, quality report, and export manifest.
- Export an Editable PPTX classroom version where HTML interactions are converted into static editable activity pages.
- Generate Agent Handoff files for Claude Code, Codex, Hermes, or Cursor Agent.
- Validate external Agent artifact edits before render/export.

## Demo Flow

1. Start the backend and frontend:

   ```bash
   npm run dev:api
   npm run dev:web
   ```

2. Open the web workbench at `http://localhost:5173`.
3. Upload a PPTX or PDF.
4. Review and save the course profile.
5. Choose the generation mode and scaffolding language.
6. Click "一键生成课件".
7. Inspect:
   - route badge
   - pipeline phases
   - quality panel
   - Spec Lock Summary
   - Artifact Inspector
8. Open the rendered preview and demonstrate:
   - slide navigation
   - keyboard left/right navigation
   - fullscreen
   - language mode toggle
   - interactive components
9. Generate an Agent Handoff package.
10. Show `agent/AGENT_TASK.md` and `agent/AGENT_RULES.md`.
11. Explain that an external Agent may edit canonical artifacts, then HanClassStudio validates, renders, runs quality, and exports.
12. Download the ZIP and open `lesson.html` offline.
13. Export Editable PPTX and show that it opens as editable classroom slides.

## Export Targets

HanClassStudio v0.1 has two export targets:

- HTML ZIP: the main interactive output. It keeps the slide-based runtime, navigation, language mode toggle, and browser interactions.
- Editable PPTX: a secondary classroom display output. It uses `python-pptx` to generate native PowerPoint text boxes, shapes, image placeholders, and activity pages from the same artifacts.

Editable PPTX does not preserve HTML runtime interactions. Components are pedagogically downgraded:

- flip cards become editable vocabulary cards
- drag builders become word-order practice pages
- listen-and-choose becomes a static choice activity with audio text prompt
- matching games become pair-matching activity pages
- character formation becomes a parts-to-character diagram

## Current Boundaries

- Real LLM providers are not wired into the demo path by default.
- Image generation uses placeholder SVGs unless provider code is explicitly configured later.
- Audio uses placeholder demo tones unless a TTS provider is added later.
- Video is represented by planning/fallback only.
- The runtime is a fixed template; Agents should not generate custom CSS or edit `courseware/lesson.html`.
- Editable PPTX is a deterministic derived export; Agents should not edit generated `.pptx` files directly.
- Existing projects under `runtime/projects` are development artifacts and are not migrated.
- Quality gate is pragmatic v0.1 coverage, not a full pedagogical review engine.

## Roadmap

This list records the v0.1 planning context. It is not the current delivery order. See [the canonical roadmap](roadmap.md) for Phase 2B/2C status, real-lesson pilots, and cutover sequencing.

- v0.2 Provider layer for configurable LLM, image, TTS, OCR, and video services.
- Template discovery and richer runtime themes.
- Streaming pipeline progress through SSE or WebSocket.
- Deeper interaction authoring UI.
- More classroom activity components.
- Teacher review checkpoints for Agent changes.
- Export variants for LMS packages or SCORM-like delivery.
- Persistent project library and version history.
