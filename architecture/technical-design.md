# Technical Design

## Product Positioning

HanClassStudio is a local-first, AI-native courseware compiler for international Chinese teaching. It accepts source materials such as PPTX, PDF, text, Markdown, URLs, or topic briefs and produces inspectable teaching artifacts plus offline-ready HTML and editable PPTX outputs.

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

The source of truth remains inspectable files, not opaque chat memory or rendered HTML.

## Current Migration State

### Production route

```text
blueprints/lesson_blueprint.json
→ presentation/activity_bindings.json
→ existing readiness and quality gates
→ existing HTML/PPTX renderers
→ public exports
```

This route remains enabled. The LessonBlueprint and v1 binding are legacy production compatibility contracts, not the future pedagogical authority.

### Shadow v2 route

```text
State / Evidence / Activity / Language
→ presentation content and media request contracts
→ abstract bindings
→ canonical presentation blueprint
→ shadow legacy adapter
→ parity and capability diagnostics
```

### Internal experiment route

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
| Source | user and intake | `uploads/`, `sources/source_material.json` |
| Analysis | analysis pipeline | learner model, language items, difficulty and inventory artifacts |
| Pedagogical truth | State-Evidence kernel | learning state, evidence, and activity plans |
| Pedagogical verdict | evidence alignment gate | `quality/evidence_alignment_report.json` |
| Canonical presentation | presentation compiler | content plan, media request plan, abstract bindings, canonical blueprint |
| Legacy compatibility | strategist/adapter | lesson blueprint, v1 binding, interaction/media plans |
| Rendered output | renderer | HTML, PPTX, render manifests |
| Diagnostics | quality/review modules | readiness, parity, reconciliation, assessment, cutover, rendered review |
| Delivery | exporter | ZIP/PPTX snapshots and export manifests |

Quality reports describe a run and gate allowed transitions. They do not mutate upstream artifacts or invent learning decisions.

## Pipeline Responsibilities

### Source intake and analysis

- normalize source material and extracted assets;
- build source profile, learner model, language items, and language inventory;
- distinguish learner-facing, teacher-only, off-level, and excluded content;
- preserve provenance.

### State-Evidence kernel

- own learner assumptions, constraints, risks, and learning goals;
- define observable evidence and acceptance contracts;
- plan activities that collect specific evidence;
- block invalid or missing Goal-Evidence-Activity mappings.

### Presentation content and media contracts

- derive content only for already-approved activities and presentation modes;
- project accepted-response semantics from evidence;
- preserve deterministic media-request and asset trace;
- never fabricate missing choices, pairs, accepted responses, or assets;
- keep teacher-only information outside learner content.

### Presentation compiler

- map activities/evidence to abstract presentation modes;
- order renderer-neutral presentation units;
- reference content items rather than duplicating their authority;
- reject renderer-specific layout and style fields.

### Compatibility adapter

- translate an already-decided canonical presentation unit into a registered legacy component shape;
- preserve trace metadata;
- omit teacher-only units from learner output;
- never select pedagogy or use slide-title heuristics.

### Media generation

- execute existing generation plans and provider calls;
- record actual files, failures, and provenance in `AssetManifest`;
- preserve stable origin identity where available;
- remain independent of renderer or pedagogical selection.

### Renderer

- consume validated render input and registered component payloads;
- generate deterministic offline-ready output;
- preserve safe trace metadata;
- never generate goals, evidence, activities, or quality verdicts.

### Quality and export

- evaluate alignment, content completeness, media trace, adapter capability, readiness, rendered behavior, accessibility, and export integrity;
- keep upstream blocked states visible downstream;
- block normal export when the active production gate is blocked;
- never treat visual similarity as pedagogical equivalence.

## Current Code Mapping

| Module | Role |
|---|---|
| `hcs_api.learning_kernel`, `evidence`, `activity_planner` | pedagogical planning |
| `hcs_api.evidence_alignment` | pedagogical alignment gate |
| `hcs_api.presentation_content` | component-neutral content contract |
| `hcs_api.presentation_media_requests` | deterministic presentation media needs |
| `hcs_api.presentation_media_projection`, `presentation_asset_reconciliation` | shadow media trace and reconciliation |
| `hcs_api.presentation_blueprint` | abstract bindings and canonical blueprint |
| `hcs_api.blueprint_compatibility` | legacy compatibility projection |
| `hcs_api.presentation_readiness`, `presentation_parity`, `presentation_adapter_assessment` | presentation diagnostics |
| `hcs_api.v2_cutover_readiness`, `v2_rendered_output_review` | internal experiment gates |
| `hcs_api.pipeline` | orchestration and feature flags |
| `hcs_api.renderer`, `pptx_deck`, `pptx_exporter` | existing production renderers/exporters |
| `hcs_api.storage` | project workspace and artifact storage |
| `apps/web/src/App.tsx` | teacher-facing workflow console |

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

Missing or blocked upstream reports must not be interpreted as success in v2 mode.

## Product Boundaries

- Chinese remains the target language; scaffolding language supports comprehension.
- Teacher-only evidence never enters learner-facing output.
- Accepted answers may exist client-side for immediate practice feedback. The product does not claim exam security or anti-cheating capability.
- Existing public render/export behavior remains legacy until an explicitly reviewed cutover.
- Browser automation supports real-lesson review; it must not postpone teacher-led pilots.
- New infrastructure must be justified by a demonstrated teacher, learner, reliability, or editing need.

## Next Milestone

Phase 2B is substantially complete and Phase 2C has completed internal technical validation. The next work is documentation convergence followed by three real Chinese micro-lesson pilots. Product capability should then be selected from observed classroom and editing problems rather than from speculative architecture needs.

See `docs/roadmap.md` for the canonical sequence and cutover criteria.
