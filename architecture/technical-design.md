# Technical Design

## Product Positioning

HanClassStudio is a local-first AI courseware generation system for international Chinese teaching.

It should accept source materials such as PPTX, PDF, text, Markdown, URLs, or topic briefs, then produce a teacher-facing interactive HTML lesson package:

- can be previewed locally
- can run offline after export
- contains editable structured lesson artifacts
- includes generated or imported images/audio/video/fonts
- records quality checks and generation decisions

The product is not just "PPT to HTML". It is a teaching-design pipeline.

## Design Philosophy

AI is the lesson designer and production assistant, not the final authority.

The system should generate a strong teaching draft:

- clear lesson objectives
- level-appropriate vocabulary and grammar
- meaningful classroom interactions
- scaffolding language for learners
- media assets that support learning
- export package a teacher can inspect and adjust

The source of truth must remain inspectable files, not opaque chat memory.

## Target System Architecture

```text
User Input
  PPTX / PDF / Markdown / text / URL / topic
        |
        v
Source Intake
  parse text, page structure, images, notes, tables, media candidates
        |
        v
Project Workspace
  uploads/ sources/ analysis/ assets/ specs/ blueprints/
        |
        v
Lesson Strategist
  profile, teaching route, lesson spec, interaction plan, media plan
        |
        v
Spec Lock
  locked JSON contract for route, level, language, templates, components, quality rules
        |
        v
Media Planner / Generator
  images, audio, video, fonts, attribution and manifest
        |
        v
Courseware Executor
  render interactive HTML runtime from blueprint + assets + runtime template
        |
        v
Quality Gate
  pedagogy, interaction, media, accessibility, offline integrity
        |
        v
Export
  preview URL + offline ZIP + delivery manifest
```

## Pipeline Phases

### 1. Source Intake

Input formats:

| Source | Intake result |
|---|---|
| PPTX | text, slide order, images, notes, rough layout facts |
| PDF | text, page boundaries, extracted images where available |
| Markdown/text | direct normalized source |
| URL | fetched article/source text and image candidates |
| Topic only | research notes become source material before generation |

Target artifacts:

- `sources/source_material.json`
- `sources/source.md`
- `analysis/source_profile.json`
- `analysis/image_inventory.json`
- `analysis/teaching_candidates.json`

### 2. Lesson Strategist

The strategist turns source facts into a teaching design.

Outputs:

- `specs/lesson_spec.md`
- `specs/spec_lock.json`
- `blueprints/lesson_blueprint.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`

Responsibilities:

- decide route: faithful, guided redesign, reimagined, template fill, enhancement
- infer or confirm learner level
- choose scaffolding language
- define objectives and classroom sequence
- choose activity types
- choose visual/runtime theme
- decide what media is needed and why

### 3. Spec Lock

`lesson_spec.md` is explanatory. `spec_lock.json` is executable.

Executor and quality checks must read `spec_lock.json`, not infer rules from prose.

Locked fields should include:

- route
- learner level
- target students
- scaffolding language
- lesson type
- duration
- teaching method
- runtime template
- allowed interaction components
- media policy
- quality policy

### 4. Media Planner / Generator

Media generation should be manifest-driven.

Inputs:

- `blueprints/media_plan.json`
- `specs/spec_lock.json`

Outputs:

- `assets/images/*`
- `assets/audio/*`
- `assets/video/*`
- `assets/fonts/*`
- `assets/data/asset_manifest.json`
- `assets/data/attribution.json`

Rules:

- placeholder assets are allowed in demo mode
- real provider failures should degrade gracefully only when policy allows
- every asset referenced by the blueprint must exist or be reported
- generated media should record prompt, provider, model, and source text

### 5. Courseware Executor

The executor renders courseware from locked data:

```text
spec_lock.json + lesson_blueprint.json + interaction_plan.json + asset_manifest.json + runtime template
  -> courseware/lesson.html
```

The executor should not decide pedagogy. It should implement the locked plan.

Runtime expectations:

- offline-ready HTML
- keyboard-accessible interactions
- responsive teacher preview
- clear learner/scaffolding language modes
- deterministic asset paths
- embedded data manifest for debugging

### 6. Quality Gate

Quality gates run before export.

They should produce:

- `quality/quality_report.json`
- `quality/quality_summary.md`

The quality gate decides whether export is:

- `pass`
- `warning`
- `blocked`

### 7. Render / Package / Export

Exports should be immutable snapshots.

Outputs:

- `exports/HanClassStudio_Output_<timestamp>.zip`
- `exports/export_manifest.json`
- optional `backup/<timestamp>/`

The ZIP must include:

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

## Current Code Mapping

| Current module | Target role |
|---|---|
| `hcs_api.parser` | Source intake |
| `hcs_api.agents` | Early strategist and fallback blueprint builder |
| `hcs_api.providers` | Provider adapter layer |
| `hcs_api.pipeline` | Pipeline orchestration |
| `hcs_api.media` | Media planner/generator |
| `hcs_api.quality` | Quality gate |
| `hcs_api.renderer` | Courseware executor |
| `hcs_api.storage` | Project workspace and artifact storage |
| `apps/web/src/App.tsx` | Teacher-facing workflow console |

## Target Module Direction

The existing modules can grow without a rewrite:

```text
hcs_api/
  intake.py              source normalization and analysis
  strategist.py          lesson_spec and spec_lock generation
  pipeline.py            orchestration only
  media.py               manifest-driven media generation
  quality.py             quality gate engine
  renderer.py            HTML runtime renderer
  storage.py             artifact paths and project lifecycle
  routes.py              FastAPI route handlers split from UI console
  templates.py           template discovery and validation
```

This is a direction, not an immediate refactor requirement.
