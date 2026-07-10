# HanClassStudio Roadmap

This document is the canonical product and engineering roadmap. Historical demo documents describe the state of a specific release and must not override this roadmap.

## Product Direction

HanClassStudio is an AI-native courseware compiler for international Chinese teaching. It is **State-first and Evidence-first**, not slide-first.

The target pipeline is:

```text
Source
→ learner/source analysis
→ Learning State Plan
→ Evidence Plan
→ Activity Plan
→ Evidence Alignment Gate
→ Presentation Content Contract
→ Presentation Media Request Contract
→ Abstract Presentation Bindings
→ Canonical Presentation Blueprint
→ Legacy LessonBlueprint Adapter
→ Renderers
→ Quality Gates
→ Export
```

Learning goals do not directly select activities. Goals define evidence; evidence constrains activities; activities support presentation. Renderers compile approved presentation artifacts and do not decide pedagogy.

## Current Milestone

```text
Phase 2B: substantially complete
Phase 2C: internal technical validation complete
Real teaching validation: not started
Production v2 cutover: not started
```

What has been demonstrated:

- the State-Evidence kernel and evidence alignment gate run end to end;
- the v2 presentation contracts can compile to a legacy-compatible render input;
- `listening_choice` and `matching_response` can enter a disabled-by-default internal HTML route;
- trace coverage, teacher-channel isolation, deterministic output, and production isolation have automated coverage;
- existing production HTML, PPTX, ZIP, v1 bindings, and `blueprints/lesson_blueprint.json` remain the default route.

What has not been demonstrated:

- teachers are willing to use the generated lesson without substantial edits;
- generated Chinese, pinyin, translations, prompts, and feedback are consistently natural and accurate;
- learners can complete the activities independently;
- the rendered lesson meets a high classroom presentation standard;
- the teacher editing workflow is efficient;
- visual parity or public v2 export readiness.

## Artifact Ownership

### Pedagogical authoritative

- `learning/learning_state_plan.json`
- `learning/evidence_plan.json`
- `learning/activity_plan.json`
- `quality/evidence_alignment_report.json` as the authoritative pedagogical gate

### Canonical presentation

- `presentation/presentation_content_plan.json`
- `presentation/presentation_content_plan.reconciled.json`
- `presentation/presentation_media_request_plan.json`
- `presentation/abstract_activity_bindings.json`
- `presentation/presentation_blueprint.json`

These artifacts may reference approved goal, evidence, activity, content, and presentation-unit IDs. They must not contain renderer layout coordinates, font/color choices, or newly invented pedagogy.

### Legacy production compatibility

- `blueprints/lesson_blueprint.json`
- `presentation/activity_bindings.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`

These remain production inputs during migration. They are not the future source of pedagogical truth.

### Diagnostic-only

- presentation readiness, shadow, parity, adapter assessment, content, media request, projection, reconciliation, cutover-readiness, and rendered-output reports;
- `presentation/legacy_blueprint_from_v2.shadow.json`;
- `presentation/presentation_media_projection_links.shadow.json`;
- `presentation/legacy_component_mapping.shadow.json`;
- `courseware/lesson_v2_internal.html` and its internal render manifest;
- `diagnostics/v2_rendered_output/`.

Diagnostic artifacts explain or validate a run. They do not own learning goals, evidence, activities, or export authorization by themselves.

## Current Execution Routes

### Production

```text
Legacy LessonBlueprint
→ v1 Presentation Bindings
→ production readiness and quality gates
→ existing HTML/PPTX renderers
→ existing exports
```

### Shadow v2

```text
State / Evidence / Activity / Language
→ Presentation Content
→ Media Requests and reconciliation
→ Abstract Bindings
→ Canonical Presentation Blueprint
→ shadow Legacy Adapter
→ parity and capability diagnostics
```

### Internal experiment

```text
eligible whole lesson
→ v2 readiness allowlist
→ in-memory compatibility adapter
→ courseware/lesson_v2_internal.html
→ v2 rendered-output review
```

The internal route is disabled by default. Its current whole-lesson allowlist is:

- `listening_choice`
- `matching_response`

Unsupported or conditional modes must remain isolated from the internal route. `choice_response` still lacks a native generic scored-choice component. Guided response, role play, and a production teacher channel are not cutover-ready.

## Next Work

### PR 3 — Documentation convergence

- align the white paper, README, architecture documents, roadmap, portfolio copy, and Agent Skill;
- document production, shadow, and internal-experiment routes;
- publish the artifact ownership matrix and report dependency order;
- remove claims that v1 bindings or `lesson_blueprint.json` are the future pedagogical authority.

### PR 4 — Real lesson pilot

Generate and review three small, real Chinese lessons using the current supported modes:

1. greetings and polite forms of address;
2. numbers, time, and dates;
3. restaurant ordering or shopping.

Evaluate:

- Chinese, pinyin, and translation accuracy;
- zero-beginner cognitive sequence;
- classroom projection usability;
- independent learner completion;
- visual clarity and audio/feedback naturalness;
- teacher correction time;
- whether correction requires editing JSON or code.

A reliable browser runner and screenshot capture may be improved in parallel, but must not delay the first teacher-led review.

### PR 5 — Product capability selected by pilot evidence

Do not pre-commit to a component or workflow before the pilot. Examples:

- high demand for generic choice tasks → add a registered `ChoiceQuestion`-style component;
- unclear classroom facilitation → improve teacher notes or a teacher channel;
- weak self-study instructions → improve prompts, scaffolds, and feedback;
- poor projection usability → improve courseware layout;
- high editing cost → build a teacher editing workflow;
- recurring browser regressions → strengthen the browser test runner.

### Later

- expand the supported-mode allowlist only after mode-specific pilot evidence;
- run a reversible HTML cutover experiment before considering public export;
- keep PPTX cutover separate;
- resume provider integration, themes, streaming progress, project history, and LMS export according to teacher value.

## Product and Safety Boundaries

- Do not add another narrow shadow metadata layer without a demonstrated product need.
- Do not treat schema validity, DOM completeness, or screenshot similarity as pedagogical equivalence.
- Do not expose teacher-only evidence in learner output.
- Do not let renderers create goals, evidence, activities, or pedagogical verdicts.
- Do not mix UI/UX, compiler architecture, documentation, real-lesson pilots, and component expansion in one large pull request.
- Client-side accepted answers are expected for classroom practice and self-study. HanClassStudio does not currently provide exam security or anti-cheating guarantees.

## Cutover Principle

The next milestone is not “more architecture.” It is:

> Produce the first lessons that a teacher is willing to use in a real classroom.

Public cutover should be considered only after real-lesson evidence shows that the output is pedagogically sound, usable, editable at acceptable cost, and stable under the supported-mode allowlist.
