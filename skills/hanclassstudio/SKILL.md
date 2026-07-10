---
name: hanclassstudio
description: Agent-compatible workflow for editing HanClassStudio international Chinese interactive courseware projects. Use when an agent needs to inspect or modify lesson specs, learning plans, presentation contracts, legacy blueprints, interaction/media plans, or validate/render/export HanClassStudio courseware.
---

# HanClassStudio Skill

Use this skill to work on HanClassStudio as an inspectable artifact workflow. External agents may improve approved source/design artifacts; HanClassStudio owns validation, rendering, quality gates, and export.

## Architecture Paradigm

HanClassStudio is **State-first and Evidence-first**, not slide-first. Read [the State-Evidence white paper](../../docs/state-evidence-kernel-v0.2.2.md), [architecture overview](../../docs/architecture-overview.md), and [roadmap](../../docs/roadmap.md) before changing architecture.

```text
Source
→ learner/source analysis
→ Learning State Plan
→ Learning Goal
→ Evidence Spec
→ Learning Activity
→ Presentation Content / Media Contracts
→ Abstract Presentation Binding
→ Canonical Presentation Blueprint
→ compatibility adapter
→ Render
→ Quality
→ Export
```

A learning goal must define evidence before an activity is selected. Renderers must not create goals, evidence, activities, or pedagogical verdicts.

## Current Migration Status

```text
Phase 2B: substantially complete
Phase 2C: internal technical validation complete
Real teaching validation: not started
Production v2 cutover: not started
```

Current routes:

- Production: `blueprints/lesson_blueprint.json` → v1 `presentation/activity_bindings.json` → existing HTML/PPTX renderers and exports.
- Shadow v2: State/Evidence/Activity → content/media contracts → abstract bindings → canonical blueprint → shadow adapter and diagnostics.
- Internal experiment: eligible whole lessons → in-memory adapter → `courseware/lesson_v2_internal.html` → rendered-output review.

The internal route is disabled by default and currently permits only lessons whose learner-facing modes are entirely `listening_choice` and `matching_response`.

## Artifact Authority

### Pedagogical authoritative

- `learning/learning_state_plan.json`
- `learning/evidence_plan.json`
- `learning/activity_plan.json`
- `quality/evidence_alignment_report.json` as the pedagogical gate

### Canonical presentation

- `presentation/presentation_content_plan.json`
- `presentation/presentation_content_plan.reconciled.json`
- `presentation/presentation_media_request_plan.json`
- `presentation/abstract_activity_bindings.json`
- `presentation/presentation_blueprint.json`

### Legacy production compatibility

- `blueprints/lesson_blueprint.json`
- `presentation/activity_bindings.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`

These remain active production inputs during migration. They are not the future pedagogical source of truth.

### Diagnostic-only

- presentation content/media/projection/reconciliation/readiness/parity/assessment reports;
- v2 cutover and rendered-output reports;
- shadow adapter output and internal HTML;
- visual/DOM diagnostics.

Diagnostics explain a run and enforce boundaries. They do not create pedagogy or independently authorize public export.

## Strict Pipeline

Follow the active production, shadow, or internal route without skipping its required upstream artifacts and gates.

### Workflow Discipline

1. Inspect source, analysis, learner/language constraints, and existing report states.
2. Fix the artifact owned by the failing layer; do not patch a downstream render to hide an upstream issue.
3. Preserve Goal → Evidence → Activity ordering.
4. Keep teacher-only information outside learner-facing content and runtime data.
5. Use only registered components from `courseware/components/registry.json`.
6. Validate current artifacts before rendering.
7. Run the applicable quality gates before export.
8. Treat `courseware/` and `exports/` as derived output.

## Report Dependency

```text
Evidence Alignment
→ Presentation Content
→ Media Request
→ Media Projection / Asset Reconciliation when required
→ Abstract Binding / Canonical Blueprint
→ Adapter Assessment
→ Structural Parity
→ Presentation Readiness
→ internal cutover readiness
→ rendered-output review
→ future aggregate export decision
```

A downstream warning or pass cannot override an upstream blocked state. Missing v2 artifacts are acceptable for legacy-only projects, but not when claiming an opt-in v2 experiment succeeded.

## Agent Editing Boundary

Current generated Agent Handoff tasks may allow edits to legacy production specs and blueprints. Treat that as a compatibility workflow:

- do not infer or replace learning goals, evidence, or activities from slide titles;
- do not copy deprecated blueprint pedagogy into the canonical v2 path;
- do not edit the shadow adapter output as source;
- do not make renderer code compensate for invalid presentation content.

When the task explicitly concerns pedagogical design, edit or regenerate the appropriate learning artifacts and rerun alignment before updating presentation.

## Product Boundaries

- Chinese is the target language; scaffold language supports comprehension.
- Client-side accepted answers are normal for offline practice and immediate feedback. The product does not claim exam security or anti-cheating capability.
- Browser automation supports teacher-led real-lesson pilots and should not delay them.
- Do not add another narrow shadow metadata/report layer without a demonstrated teacher, learner, reliability, or editing need.
- Do not mix UI/UX, compiler architecture, documentation, real-lesson pilots, and component expansion in one large change.

## Required References

- `references/artifact-ownership.md` before editing project artifacts.
- `references/component-registry.md` before adding or editing components.
- `references/scaffolding-language.md` before changing language support.
- `workflows/routing.md` before selecting a project route.
- `workflows/failure-recovery.md` when validation, render, quality, or export fails.

## Hard Rules

- Do not edit `uploads/`.
- Do not edit `courseware/lesson.html` or `lesson_v2_internal.html` as source.
- Do not edit `exports/` or generated `.pptx` files.
- Do not invent components outside `courseware/components/registry.json`.
- Do not bypass quality gates.
- Do not make `lesson_blueprint.json` the source of pedagogical truth.
- Do not let renderer code choose pedagogy.
- Do not expose teacher-only evidence in learner-facing output.
- Do not claim visual or pedagogical equivalence from schema, DOM, or screenshot similarity alone.
