---
name: hanclassstudio
description: Agent-compatible workflow for editing HanClassStudio international Chinese interactive courseware projects. Use when an agent needs to inspect or modify lesson specs, spec locks, blueprints, interaction plans, media plans, or validate/render/export HanClassStudio courseware.
---

# HanClassStudio Skill

Use this skill to work on HanClassStudio as a file workflow. External agents may read source materials and edit specs or blueprints; HanClassStudio validates, renders, runs quality gates, and exports.

## Strict Pipeline

Execute the workflow in order:

```text
Source Intake
  -> Project Workspace
  -> Lesson Strategist
  -> Spec Lock
  -> Blueprint / Interaction / Media Plans
  -> Runtime Render
  -> Quality Gate
  -> Export
```

Do not skip forward. Each phase consumes artifacts from the previous phase.

## Blocking Gates

Stop at these gates unless the user or host app has confirmed the prerequisite:

- course profile confirmation before blueprint generation
- lesson blueprint confirmation before media/render/export
- export before blocked quality state

If quality state is `blocked`, fix upstream artifacts or use the explicit forced-export path only when the user requests demo output.

## Source Of Truth

- `specs/lesson_spec.md` is the teaching design explanation.
- `specs/spec_lock.json` is the execution contract.
- `blueprints/lesson_blueprint.json` is the courseware structure.
- `blueprints/interaction_plan.json` is the interaction contract.
- `blueprints/media_plan.json` is the media requirement list.
- `courseware/lesson.html` is a derived artifact.

## Required References

Read these files as needed:

- `workflows/routing.md` before selecting a route.
- `references/artifact-ownership.md` before editing project artifacts.
- `references/component-registry.md` before adding or editing components.
- `references/scaffolding-language.md` before changing language support.
- `workflows/failure-recovery.md` when validation, render, quality, or export fails.

## Hard Rules

- Do not edit `uploads/`.
- Do not edit `courseware/lesson.html` as source.
- Do not edit `exports/`.
- Do not use components outside `courseware/components/registry.json`.
- Do not bypass quality gates.
- Keep Chinese as the target language; use scaffolding language only as support.

