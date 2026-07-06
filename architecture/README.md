# HanClassStudio Architecture

This folder defines the target architecture for HanClassStudio after borrowing the strongest ideas from PPT Master:

- strict pipeline discipline
- clear runtime artifact ownership
- deterministic route selection
- locked execution specs
- reusable templates
- quality gates before export

HanClassStudio is not a PPT generator. Its target shape is:

> AI-driven interactive courseware generation system for international Chinese teaching.

It turns teaching materials into offline-ready, teacher-editable, interactive HTML courseware packages.

## Documents

| File | Purpose |
|---|---|
| `technical-design.md` | System positioning, core pipeline, module boundaries, and technical route. |
| `project-structure.md` | Target runtime project folders, artifact ownership, and rebuild rules. |
| `routing.md` | How different user requests enter different workflows. |
| `templates-and-specs.md` | Template model, `lesson_spec.md`, `spec_lock.json`, and component registry. |
| `quality-gates.md` | Quality checks for pedagogy, interaction, media, accessibility, and offline export. |

## Core Pipeline

```text
Source Material
  -> Project Init
  -> Source Intake
  -> Lesson Strategist
  -> Spec Lock
  -> Media Planner / Generator
  -> Courseware Executor
  -> Quality Gate
  -> Render / Package
  -> Export
```

Current v0.1 already has the beginning of this flow:

```text
upload -> parse_source -> infer_profile -> generate_blueprint
       -> spec_lock -> generate_media -> render_lesson
       -> check_quality -> export_policy -> zip_output
```

The new architecture makes each step explicit, recoverable, and inspectable.

## Architectural Invariants

These rules should stay true as the codebase grows:

| Invariant | Meaning |
|---|---|
| `sources/` is the content contract | Source facts come from normalized materials, not from rendered HTML. |
| `analysis/` stores machine facts | It can be regenerated and should not become human-authored teaching design. |
| `lesson_spec.md` explains design | Human-readable teaching rationale, audience, route, and choices. |
| `spec_lock.json` executes design | Runtime truth for generation, rendering, quality checks, and recovery. |
| `blueprints/` is author state | Lesson structure and interactions are editable source artifacts. |
| `courseware/` is derived output | Rendered HTML can be rebuilt from specs, blueprints, assets, and templates. |
| `exports/` is delivery output | ZIP packages are immutable snapshots for sharing or classroom use. |
| quality gates run before export | The system should know whether a courseware package is safe to hand to a teacher. |

## Relationship To PPT Master

| PPT Master concept | HanClassStudio equivalent |
|---|---|
| `design_spec.md` | `lesson_spec.md` |
| `spec_lock.md` | `spec_lock.json` |
| SVG Executor | Courseware Executor |
| `svg_output/` | `blueprints/` + `courseware/` source/runtime artifacts |
| `svg_final/` | bundled/offline-ready courseware output |
| `svg_quality_checker.py` | courseware quality gates |
| brand/layout/deck templates | brand/pedagogy/runtime/courseware templates |
| PPTX export | offline HTML ZIP export |
