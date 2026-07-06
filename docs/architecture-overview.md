# Architecture Overview

HanClassStudio v0.1 uses an artifact-first architecture. The web workbench is a teacher-facing controller; the backend owns project workspaces, canonical artifacts, validation, rendering, quality gates, and export.

## Artifact-First Workspace

Each project lives under:

```text
runtime/projects/<project_id>/
```

The workspace is divided by ownership:

```text
uploads/
sources/
analysis/
specs/
blueprints/
assets/
courseware/
quality/
exports/
agent/
backup/
```

The important rule: each stage writes named artifacts to a predictable path. Later stages read those artifacts instead of guessing state from UI fields.

## Lesson Spec And Spec Lock

`specs/lesson_spec.md` is the human-readable teaching design. It explains the lesson intent, audience, language scaffolding, route, media strategy, and quality policy.

`specs/spec_lock.json` is the execution contract. It locks the route, generation mode, runtime assumptions, allowed components, media policy, and export policy.

Downstream stages should read `spec_lock.json` instead of inferring policy directly from frontend fields.

## Component Registry

`courseware/components/registry.json` is the source of truth for interactive components.

The registry defines:

- component names
- renderer support
- required data fields
- optional fields
- quality checks
- experimental status

The frontend loads this registry through `/api/component-registry`, and the renderer plus quality gate validate against the same component names.

## Agent Handoff

Agent Handoff lets external coding Agents work on structured lesson artifacts without owning render/export.

HanClassStudio can generate:

```text
agent/AGENT_TASK.md
agent/AGENT_RULES.md
```

An external Agent may edit:

- `specs/lesson_spec.md`
- `specs/spec_lock.json`
- `blueprints/lesson_blueprint.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`

HanClassStudio then validates the output, renders `courseware/lesson.html`, runs quality, and exports.

## Quality Gate

The quality gate writes:

```text
quality/quality_report.json
quality/quality_summary.md
```

The report state is:

```text
pass | warning | blocked
```

`blocked` prevents normal export. A forced export path exists for demo use, and forced exports are marked in `export_manifest.json`.

The v0.1 gate checks title/objectives/slides, component support, interaction answers, missing assets, path safety, runtime output, and basic vocabulary language requirements.

## Offline HTML Export

The renderer writes:

```text
courseware/lesson.html
courseware/render_manifest.json
```

The exported ZIP includes `lesson.html`, media assets, canonical data artifacts, the quality report, and an export manifest.

The runtime is slide-based, local-only, and does not depend on external CDNs. Its CSS and JavaScript come from the fixed runtime renderer/template, not from generated Agent content.

