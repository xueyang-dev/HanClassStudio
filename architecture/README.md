# HanClassStudio Architecture

This folder defines the current and target architecture for HanClassStudio:

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

The canonical delivery sequence and phase status live in [`docs/roadmap.md`](../docs/roadmap.md).

## Core Pipeline

```text
Source Material
  -> learner/source analysis
  -> Learning State Plan
  -> Evidence Plan
  -> Activity Plan
  -> Evidence Alignment Gate
  -> Presentation Content / Media Contracts
  -> Abstract Bindings
  -> Canonical Presentation Blueprint
  -> Legacy Adapter
  -> Renderer
  -> Quality Gate
  -> Export
```

The current production route remains legacy while the v2 route is shadow/internal:

```text
Production: LessonBlueprint -> v1 Bindings -> existing renderers -> exports
Shadow v2: Kernel -> canonical presentation -> shadow adapter -> diagnostics
Internal: eligible v2 lesson -> lesson_v2_internal.html -> rendered review
```

The internal path is disabled by default and currently allows only whole lessons using `listening_choice` and `matching_response`.

## Architectural Invariants

These rules should stay true as the codebase grows:

| Invariant | Meaning |
|---|---|
| `sources/` is the content contract | Source facts come from normalized materials, not from rendered HTML. |
| `analysis/` stores machine facts | It can be regenerated and should not become human-authored teaching design. |
| learning artifacts own pedagogy | Goals, evidence, and activities are defined before presentation. |
| canonical presentation artifacts own renderer-neutral presentation | Content, media needs, abstract bindings, and ordered units live under `presentation/`. |
| legacy blueprints are compatibility inputs | `lesson_blueprint.json` and v1 bindings remain production inputs, not future pedagogical truth. |
| `courseware/` is derived output | Rendered HTML can be rebuilt from specs, blueprints, assets, and templates. |
| `exports/` is delivery output | ZIP packages are immutable snapshots for sharing or classroom use. |
| quality gates run before export | The system should know whether a courseware package is safe to hand to a teacher. |
| renderers do not decide pedagogy | They compile validated presentation inputs. |

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
