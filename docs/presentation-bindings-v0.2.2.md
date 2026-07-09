# Presentation Bindings v0.2.2

**Status**: v0.2.2-alpha implementation contract  
**Scope**: binding State-Evidence Kernel artifacts to HTML, PPTX, speaker notes, and teacher-facing views

## Why This Layer Exists

The State-Evidence Kernel is presentation-independent. It defines learner states, goals, evidence, and activities, but it must not know about slide IDs, component IDs, HTML nodes, or PPTX layouts.

Before v0.2.2-alpha, HTML and PPTX evidence mapping used local heuristics such as vocabulary matching. That worked for the v0.2.1-alpha MVP, but it made each renderer guess the relationship between teaching evidence and presentation targets.

`presentation/activity_bindings.json` is the single binding contract:

```text
LearningActivity
  -> EvidenceSpec
  -> PresentationBinding
  -> slide_id / component_id
  -> HTML / PPTX / speaker notes / teacher observation
```

## Kernel Boundary

These artifacts must remain presentation-independent:

- `learning/learning_state_plan.json`
- `learning/evidence_plan.json`
- `learning/activity_plan.json`
- `quality/evidence_alignment_report.json`

They must not contain `slide_id`, `component_id`, `html_component_id`, `pptx_layout`, or similar presentation references.

Presentation IDs are allowed in:

- `presentation/activity_bindings.json`
- `presentation/binding_quality_report.json`
- downstream presentation artifacts such as `blueprints/pptx_deck_plan.json`

## Schema

`PresentationBinding`:

```json
{
  "binding_id": "bind_act_dialogue_choice_ev_dialogue_choice_s7_match_pairs",
  "activity_id": "act_dialogue_choice",
  "evidence_id": "ev_dialogue_choice",
  "slide_id": 7,
  "component_id": "match_pairs",
  "presentation_modes": ["html_interactive", "html_classroom", "pptx_classroom", "speaker_notes"],
  "binding_confidence": 0.8,
  "binding_reason": "matched_by_component_type",
  "teacher_note_policy": "include_evidence_claim_pass_fail",
  "created_by": "binding_builder"
}
```

`PresentationBindingPlan`:

```json
{
  "schema": "hanclassstudio.presentation_bindings.v1",
  "bindings": [],
  "warnings": [],
  "blocking": [],
  "state": "pass"
}
```

## Pipeline Position

The v0.2.2-alpha pipeline position is:

```text
source/profile
  -> blueprint
  -> learner_model
  -> language_items
  -> source/difficulty/inventory
  -> State-Evidence Kernel
  -> presentation/activity_bindings.json
  -> presentation/binding_quality_report.json
  -> HTML/PPTX render
```

If `presentation/binding_quality_report.json` is `blocked`, classroom-ready render/export must not proceed.

## Binding Quality Gate

The binding quality gate checks:

- Every `EvidenceSpec` has at least one presentation binding.
- Every binding references an existing `activity_id` and `evidence_id`.
- Every binding references an existing `slide_id`.
- Non-empty `component_id` values exist on the referenced slide.
- zero-beginner lessons do not bind evidence to unsuitable components such as `SentenceDragBuilder`, `open_response`, or `role_play_scene`.
- `teacher_observation` evidence includes `speaker_notes` or `teacher_observation` presentation mode.
- Low-confidence bindings produce warnings.

## HTML Consumption

The HTML renderer reads `presentation/activity_bindings.json`.

In classroom `lesson-data`, bound component data includes:

- `binding_id`
- `activity_id`
- `evidence_id`

These fields are metadata only. They must not appear as learner-facing visible text.

## PPTX Consumption

The PPTX deck builder reads `presentation/activity_bindings.json`.

For bound slides, `blueprints/pptx_deck_plan.json` includes:

- `binding_id`
- `activity_id`
- `evidence_id`
- `evidence_claim`
- `expected_behavior`
- `failure_action`

Speaker notes include:

```text
Binding:
Activity:
Evidence:
Claim:
Pass:
Fail:
```

Cover and objective slides receive no evidence by default unless a binding explicitly targets them.

## Known Limitations

- Binding generation still uses heuristic matching as a fallback, but the heuristic is centralized in `presentation_bindings.py`.
- The first v0.2.2-alpha implementation records low-confidence matches as warnings rather than requiring manual teacher confirmation.
- Teacher observation views are represented through binding modes and speaker notes; a dedicated teacher dashboard is still future work.
- PPTX binary-level notes XML inspection is still a separate verification step.
