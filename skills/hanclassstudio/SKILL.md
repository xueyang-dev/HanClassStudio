---
name: hanclassstudio
description: Agent-compatible workflow for editing HanClassStudio international Chinese interactive courseware projects. Use when an agent needs to inspect or modify lesson specs, spec locks, blueprints, interaction plans, media plans, or validate/render/export HanClassStudio courseware.
---

# HanClassStudio Skill

Use this skill to work on HanClassStudio as a file workflow. External agents may read source materials and edit specs or blueprints; HanClassStudio validates, renders, runs quality gates, and exports.

## Architecture Paradigm

HanClassStudio uses a **State-first** architecture documented in [docs/state-evidence-kernel-v0.2.2.md](../docs/state-evidence-kernel-v0.2.2.md):

```text
Source
→ Learning State Plan
→ Learning Goal
→ Evidence Spec
→ Learning Activity
→ Presentation Plan
→ Render
```

State / Goal / Evidence / Activity constitute the pedagogical kernel.
HTML / PPTX / Teacher Observation are downstream presentation forms.
The renderer is a backend compiler and must NOT make pedagogical judgments.

## Strict Pipeline

Execute the workflow in order:

```text
Source Intake
  → Source Lesson Profile
  → Learner Model
  → Language Items
  → Learning State Plan (new - state-first kernel)
  → Evidence Plan (new)
  → Activity Plan (new)
  → Blueprint / Interaction / Media Plans
  → Courseware Review Agent
  → Revision Application
  → Runtime Render
  → Quality Gate
  → Export
```

## Core Artifacts

| Artifact | Status | Description |
|---|---|---|
| `learning/learning_state_plan.json` | Planned | State DAG & transitions |
| `learning/evidence_plan.json` | Planned | Evidence specs per transition |
| `learning/activity_plan.json` | Planned | Activity definitions |
| `quality/evidence_alignment_report.json` | Planned | Goal-Evidence-Activity alignment |

See [docs/state-evidence-kernel-v0.2.2.md](../docs/state-evidence-kernel-v0.2.2.md) for full model schemas and quality gate rules.

## Current Implementation Status

Existing pipeline (working):
- Source intake → Learner Model → Language Items
- Blueprint generation (existing `agents.py`)
- Quality checks (classroom, off-level, comprehensibility, realization)
- Courseware Review Agent
- Revision Plan Application
- HTML render (debug + classroom)
- Traditional PPTX Deck render
- Export (ZIP, diagnostic PPTX)

Next phase (State-Evidence Kernel):
- `learning_state_plan.json` generator
- `evidence_plan.json` generator
- `activity_plan.json` generator
- `evidence_alignment_report.json` quality gate
- Pipeline integration: state plan → evidence → activity → existing renderers

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
- `exports/*.pptx` files are derived editable export artifacts.

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
- Do not directly edit generated `.pptx` files.
- Do not use components outside `courseware/components/registry.json`.
- Do not bypass quality gates.
- Keep Chinese as the target language; use scaffolding language only as support.
