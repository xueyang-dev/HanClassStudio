---
name: hanclassstudio
description: Agent-compatible workflow for editing HanClassStudio international Chinese interactive courseware projects. Use when an agent needs to inspect or modify lesson specs, spec locks, blueprints, interaction plans, media plans, or validate/render/export HanClassStudio courseware.
---

# HanClassStudio Skill

Use this skill to work on HanClassStudio as a file workflow. External agents may read source materials and edit specs or blueprints; HanClassStudio validates, renders, runs quality gates, and exports.

## Architecture Paradigm

HanClassStudio uses a **State-first** architecture documented in [docs/state-evidence-kernel-v0.2.2.md](../../docs/state-evidence-kernel-v0.2.2.md):

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
  → Learning State Plan
  → Evidence Plan
  → Activity Plan
  → Evidence Alignment Gate
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
| `learning/learning_state_plan.json` | Implemented | State DAG, goals, transitions |
| `learning/evidence_plan.json` | Implemented | Evidence specs per transition |
| `learning/activity_plan.json` | Implemented | Activity definitions and evidence collectors |
| `quality/evidence_alignment_report.json` | Implemented | Goal-Evidence-Activity alignment gate |
| `presentation/activity_bindings.json` | Implemented | Formal binding from activity/evidence to slide/component/presentation outputs |
| `presentation/binding_quality_report.json` | Implemented | Binding quality gate for presentation targets |

See [docs/state-evidence-kernel-v0.2.2.md](../../docs/state-evidence-kernel-v0.2.2.md) for full model schemas and quality gate rules.

## Current Implementation Status

Working pipeline:
- Source intake → Learner Model → Language Items
- State-Evidence Kernel generation
- Evidence alignment quality gate
- Blueprint generation (existing `agents.py`)
- Quality checks (classroom, off-level, comprehensibility, realization)
- Courseware Review Agent
- Revision Plan Application
- HTML render (debug + classroom)
- Traditional PPTX Deck render
- Export (ZIP, diagnostic PPTX)

Latest verified milestone:
- v0.2.1-alpha smoke test: 70 tests passed, 1 warning.
- Kernel artifacts are generated during the normal pipeline.
- Alignment `blocked` stops classroom render/export and emits a kernel diagnostic ZIP.
- Classroom HTML and PPTX deck plans carry evidence IDs and teacher-facing evidence notes.

Current v0.2.2-alpha work:
- `presentation/activity_bindings.json`
- `presentation/binding_quality_report.json`
- Centralize fallback evidence-to-slide matching in the binding builder.
- Use a single binding source for HTML, PPTX, speaker notes, and teacher observation views.

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
- `learning/learning_state_plan.json` is the state-first teaching kernel.
- `learning/evidence_plan.json` is the evidence contract.
- `learning/activity_plan.json` is the evidence collection activity contract.
- `quality/evidence_alignment_report.json` is the kernel quality gate.
- `presentation/activity_bindings.json` is the only formal Kernel-to-presentation binding contract.
- `presentation/binding_quality_report.json` is the binding quality gate.
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
