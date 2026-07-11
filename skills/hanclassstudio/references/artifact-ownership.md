# Artifact Ownership

| Folder | Owner | Kind | Rebuildable |
|---|---|---|---:|
| `uploads/` | user | original source | no |
| `sources/` | intake/parser | normalized source contract | yes, from uploads |
| `analysis/` | analysis pipeline | derived facts and constraints | yes |
| `learning/` | State-Evidence kernel | pedagogical authoritative plans | yes, subject to review |
| `specs/` | strategist / user / agent | human-readable and execution policy | partially |
| `presentation/` | presentation compiler/compatibility layer | canonical, legacy, and shadow presentation artifacts | yes |
| `blueprints/` | legacy strategist / user / agent | production compatibility inputs | partially |
| `assets/` | media generator / user | runtime source and manifests | partially |
| `courseware/` | renderer | derived output | yes |
| `quality/` | quality/review modules | derived gates and diagnostics | yes |
| `diagnostics/` | validation tools | derived review evidence | yes |
| `exports/` | exporter | immutable delivery snapshots | yes |

## Authority Classes

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

### Diagnostic-only

- shadow adapter output;
- readiness, parity, assessment, projection, reconciliation, cutover, and rendered-output reports;
- internal v2 HTML, DOM snapshots, and screenshots.

Agents must not edit derived or diagnostic folders to fake success. Fix the artifact owned by the failing upstream layer, then rerun downstream compilation and gates.

The current Agent Handoff API may permit editing legacy specs and blueprints. That is a production compatibility workflow; it does not make those files the pedagogical authority of the v2 path.
