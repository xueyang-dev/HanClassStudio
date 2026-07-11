# Technical Design

## Product Positioning

HanClassStudio is a local-first, AI-native courseware compiler for international Chinese teaching. It accepts source material and produces inspectable teaching artifacts plus offline-ready HTML and editable PPTX outputs.

It is not a PPT-to-HTML converter and it is not slide-first. Its primary design problem is to preserve a valid chain from learner state and learning goals to evidence, activities, presentation, rendered output, quality, and export.

## Core Invariant

```text
Source
→ Learning State Plan
→ Learning Goals
→ Evidence Specs
→ Learning Activities
→ Presentation Contracts
→ Rendered Outputs
→ Quality Reports
```

A LearningGoal does not directly generate a LearningActivity. Goals define evidence; evidence constrains activities; activities support presentation. Renderers compile approved presentation artifacts and make no pedagogical judgments.

## Current Phase Status

```text
Phase 2B: substantially complete
Phase 2C: internal technical validation complete
Real teaching validation: not started
Production v2 cutover: not started
```

## Target Architecture

```text
Source Intake
  → normalized source and source analysis
  → learner model and language inventory
  → Learning State Plan
  → Evidence Plan
  → Activity Plan
  → Evidence Alignment Gate
  → Presentation Content Contract
  → Presentation Media Request Contract
  → Abstract Presentation Bindings
  → Canonical Presentation Blueprint
  → compatibility adapter
  → renderer
  → rendered-output quality
  → export gate
```

## Current Migration Routes

### Production

```text
blueprints/lesson_blueprint.json
→ presentation/activity_bindings.json
→ existing HTML/PPTX renderers
→ public exports
```

The LessonBlueprint and v1 binding remain production compatibility contracts. They are not the future pedagogical authority.

### Shadow v2

```text
State / Evidence / Activity / Language
→ presentation content and media request contracts
→ abstract bindings
→ canonical presentation blueprint
→ shadow legacy adapter
→ parity and capability diagnostics
```

### Internal experiment

```text
eligible whole lesson
→ v2 cutover readiness
→ in-memory compatibility-adapted LessonBlueprint
→ courseware/lesson_v2_internal.html
→ v2 rendered-output review
```

The internal route is disabled by default. It does not overwrite production blueprints, HTML, PPTX, ZIP files, or render manifests. Its current whole-lesson allowlist is `listening_choice` and `matching_response`.

## Artifact Authority

| Layer | Owner | Representative artifacts |
|---|---|---|
| Source | user and intake | `uploads/`, normalized source |
| Analysis | analysis pipeline | learner model, language items, difficulty and inventory artifacts |
| Pedagogical truth | State-Evidence kernel | learning state, evidence, and activity plans |
| Pedagogical verdict | evidence alignment gate | `quality/evidence_alignment_report.json` |
| Canonical presentation | presentation compiler | content plan, media request plan, abstract bindings, canonical blueprint |
| Legacy compatibility | strategist/adapter | lesson blueprint, v1 binding, interaction/media plans |
| Rendered output | renderer | HTML, PPTX, render manifests |
| Diagnostics | quality/review modules | readiness, parity, reconciliation, assessment, cutover, rendered review |
| Delivery | exporter | ZIP/PPTX snapshots and export manifests |

## Responsibility Boundaries

### State-Evidence kernel

- owns learner assumptions, constraints, risks, and learning goals;
- defines observable evidence and acceptance contracts;
- plans activities that collect specific evidence;
- blocks invalid Goal-Evidence-Activity mappings.

### Presentation contracts

- derive content only for already-approved activities and presentation modes;
- project accepted-response semantics from evidence;
- preserve deterministic media-request and asset trace;
- never fabricate missing choices, pairs, accepted responses, or assets;
- keep teacher-only information outside learner content.

### Presentation compiler and adapter

- map approved activity/evidence pairs to abstract presentation modes;
- order renderer-neutral presentation units;
- project units into registered legacy component shapes only after the presentation decision exists;
- preserve trace metadata and omit teacher-only units from learner output;
- never select pedagogy or use slide-title heuristics.

### Renderer and export

- consume validated render input and registered component payloads;
- generate deterministic offline-ready output;
- never generate goals, evidence, activities, or quality verdicts.

## Quality Dependency Order

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

No downstream warning or pass can override an upstream blocked state. Most v2 reports are diagnostic-only while the route remains shadow/internal.

## Product Boundaries

- Chinese remains the target language; scaffolding language supports comprehension.
- Teacher-only evidence never enters learner-facing output.
- Client-side accepted answers provide immediate practice feedback. The product does not claim exam security or anti-cheating capability.
- Browser automation supports real-lesson review and must not postpone teacher-led pilots.
- New infrastructure requires a demonstrated teacher, learner, reliability, or editing need.

## Next Milestone

The next work is a teacher-led three-lesson pilot, followed by product work selected from observed classroom and editing problems. See `docs/roadmap.md` for the canonical sequence and cutover criteria.
