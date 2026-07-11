# Presentation Contracts And Bindings

**Status**: Phase 2B migration contract

**Production**: legacy v1 binding path

**Future path**: canonical v2 presentation contracts in shadow/internal mode

## Why This Layer Exists

The State-Evidence Kernel is presentation-independent. It defines learner states, goals, evidence, and activities, but it must not know about slide IDs, component IDs, DOM nodes, PPTX layouts, fonts, colors, or renderer coordinates.

The presentation layer translates already-approved activities and evidence into renderer-neutral content and presentation units. It does not create goals, evidence, or activities and does not judge pedagogical validity.

## Two Binding Models During Migration

### v1 production binding

`presentation/activity_bindings.json` maps activity/evidence trace to an existing legacy slide and component:

```text
Legacy LessonBlueprint
→ v1 PresentationBinding with slide_id/component_id
→ existing HTML/PPTX renderers
```

It remains necessary for the current production renderer contract. It may centralize compatibility matching, but it is not the future canonical Kernel-to-Presentation contract and must not become pedagogical authority.

### v2 abstract binding

`presentation/abstract_activity_bindings.json` maps approved activities and evidence to abstract presentation modes:

```text
LearningActivity + EvidenceSpec
→ AbstractPresentationBinding
→ Canonical Presentation Blueprint
→ compatibility adapter
```

The abstract model uses stable activity, evidence, content, and presentation-unit references. It has no `slide_id`, `component_id`, layout coordinates, font/color data, or exact renderer component identity.

## Canonical v2 Presentation Flow

```text
Learning State / Evidence / Activity / Language artifacts
→ presentation/presentation_content_plan.json
→ presentation/presentation_media_request_plan.json
→ presentation/abstract_activity_bindings.json
→ presentation/presentation_blueprint.json
→ shadow LegacyLessonBlueprint adapter
→ parity, capability, and rendered-output diagnostics
```

Presentation Content owns component-neutral prompts, options, accepted-response projections, matching pairs, media references, learner-safe hints, and provenance. Evidence owns acceptance semantics; Activity owns interaction flow; the Binding owns presentation-mode mapping; the Canonical Blueprint owns ordered renderer-neutral units.

## Artifact Boundaries

The following must remain presentation-independent:

- `learning/learning_state_plan.json`
- `learning/evidence_plan.json`
- `learning/activity_plan.json`
- `quality/evidence_alignment_report.json`

Canonical v2 artifacts must not contain:

- new `LearningGoal`, `EvidenceSpec`, or `LearningActivity` objects;
- learner-state assumptions;
- `slide_id` or `component_id`;
- layout coordinates, font sizes, colors, or renderer styling;
- teacher-only observation notes in learner-facing content;
- quality verdict authority.

Legacy presentation IDs are allowed only in compatibility artifacts such as:

- `presentation/activity_bindings.json`;
- `blueprints/lesson_blueprint.json`;
- renderer-specific plans and manifests;
- shadow adapter output used only to validate compatibility.

## Teacher Channel Boundary

Teacher-only evidence may route to speaker notes, teacher observation, teacher HTML, or diagnostic export. It must not receive a learner-facing mode or appear in learner prompts, options, answers, hints, or embedded learner data.

## Current Execution Status

Implementation note: the current shadow orchestrator materializes abstract bindings and a canonical skeleton immediately after evidence alignment, then generates optional content and enriches the canonical blueprint with content references. This is a migration sequencing seam, not a change in ownership: bindings do not generate content or pedagogy, and the final canonical blueprint must reference the content contract. The target dependency order remains content/media contracts before final canonical compilation.

### Production

```text
blueprints/lesson_blueprint.json
→ presentation/activity_bindings.json
→ presentation readiness
→ existing HTML/PPTX renderers
→ export
```

### Shadow/internal

```text
Kernel
→ content/media contracts
→ abstract bindings
→ canonical blueprint
→ in-memory compatibility adapter
→ courseware/lesson_v2_internal.html
→ v2 rendered-output review
```

The internal route is disabled by default and uses whole-lesson routing. Its current learner-facing allowlist is:

- `listening_choice`
- `matching_response`

`choice_response` remains fallback-only because the registry lacks a native generic scored-choice component. Guided response and role play are not cutover-ready, and teacher observation has no production teacher-channel adapter.

## Quality And Report Dependency

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

A downstream warning cannot override an upstream blocked state. Shadow reports are diagnostic and must not authorize public export.

## Migration Rules

- Do not replace production renderers in the current phase.
- Do not read `lesson_blueprint.json` as pedagogical input for the v2 compiler.
- Do not route a partially supported lesson through mixed pedagogical authority; current internal routing is whole-lesson only.
- Do not use approximate text matching as authoritative media trace.
- Do not treat schema validity, structural parity, or DOM completeness as visual or pedagogical equivalence.
- Do not add another narrow metadata layer without a demonstrated product need.

## Next Milestone

Phase 2B is substantially complete and Phase 2C has completed internal technical validation. The next milestone is a teacher-led three-lesson pilot using the supported modes, followed by product work selected from observed teaching and editing problems. See [roadmap.md](roadmap.md).
