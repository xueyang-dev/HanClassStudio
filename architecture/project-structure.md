# Project Structure And Artifact Ownership

## Repository Structure

```text
HanClassStudio/
  architecture/
  apps/
    api/
      src/hcs_api/
      tests/
    web/
      src/
  courseware/
    runtimes/
    themes/
    components/
  templates/
  runtime/
    config/
    projects/
  docs/
  skills/
  README.md
```

`courseware/` contains reusable runtime assets. `runtime/` contains generated local projects and stays outside version control.

## Runtime Project Layout

Representative current layout:

```text
runtime/projects/<project_id>/
  uploads/
  sources/
  analysis/
  learning/
    learning_state_plan.json
    evidence_plan.json
    activity_plan.json
  specs/
  blueprints/
    lesson_blueprint.json
    interaction_plan.json
    media_plan.json
  presentation/
    activity_bindings.json
    abstract_activity_bindings.json
    presentation_content_plan.json
    presentation_content_plan.reconciled.json
    presentation_media_request_plan.json
    presentation_blueprint.json
    legacy_blueprint_from_v2.shadow.json
  assets/
    images/
    audio/
    video/
    fonts/
    data/
      asset_manifest.json
  courseware/
    lesson.html
    render_manifest.json
    lesson_v2_internal.html
    render_manifest_v2_internal.json
  quality/
    evidence_alignment_report.json
    quality_report.json
    presentation_readiness_report.json
    v2_cutover_readiness_report.json
    v2_rendered_output_review.json
  diagnostics/
  exports/
  agent/
  backup/
```

Shadow/internal files are generated only when their opt-in paths run. They are not required for legacy production projects.

## Ownership Matrix

| Category | Artifact examples | Owner | Authority | Rebuildable |
|---|---|---|---|---:|
| User source | `uploads/*` | user | original input | no |
| Normalized source | `sources/*` | intake | source contract | yes, from uploads |
| Analysis | `analysis/*` | analysis pipeline | machine facts and constraints | yes |
| Pedagogical authoritative | learning state, evidence, activity plans | State-Evidence kernel | goals, evidence, activities | yes, subject to review |
| Pedagogical gate | evidence alignment report | alignment gate | pedagogical validity | yes |
| Canonical presentation | content plan, media request plan, abstract bindings, presentation blueprint | v2 presentation compiler | renderer-neutral content and structure | yes |
| Legacy production compatibility | lesson blueprint, v1 binding, interaction/media plans | legacy strategist/adapter | current renderer input only | partially |
| Runtime assets | media files and asset manifest | media generator/user | files available to renderers | partially |
| Rendered output | HTML, PPTX, render manifests | renderer/exporter | derived output | yes |
| Diagnostic-only | readiness, parity, projection, reconciliation, assessment, cutover, rendered review | quality modules | run diagnostics | yes |
| Delivery | ZIP/PPTX export snapshots | exporter | immutable delivery | yes |

## Source-Of-Truth Rules

| Rule | Reason |
|---|---|
| Do not edit rendered HTML or exported PPTX as source | They are derived outputs. |
| Do not put teaching decisions only in chat | Goals, evidence, and activities belong in learning artifacts. |
| Do not make `lesson_blueprint.json` pedagogical authority | It is a legacy production compatibility contract. |
| Do not let renderers invent interactions or pedagogy | Renderers compile validated presentation input. |
| Do not copy teacher-only evidence into learner content | Teacher and learner channels have separate safety boundaries. |
| Do not let quality checks mutate upstream artifacts | Reports diagnose; upstream owners are fixed or regenerated. |
| Do not treat shadow diagnostics as production export approval | Public export remains governed by active production gates. |
| Do not treat missing v2 artifacts as success when v2 mode is requested | Missing or stale artifacts must block or invalidate the experiment. |

## Rebuild Paths

| Need | Rebuild from |
|---|---|
| Rebuild pedagogical kernel | normalized source, learner/language analysis, confirmed constraints |
| Rebuild canonical presentation | valid learning artifacts plus source/language/media references |
| Re-render production HTML | legacy production blueprints, bindings, assets, runtime template |
| Re-render internal v2 HTML | current canonical blueprint/content plus in-memory compatibility adapter |
| Regenerate media | media plan/request plus provider settings |
| Re-run quality | authoritative inputs, current presentation artifacts, manifests, rendered output |
| Rebuild public ZIP | production HTML, assets, data manifests, active quality reports |

## Stale Artifact Policy

Before an opt-in v2 rerun, stale shadow adapter output, internal HTML, rendered-output reports, DOM snapshots, and visual diagnostics must be removed or invalidated. A blocked upstream run must not leave a previous successful downstream artifact looking current.

Do not introduce a separate lineage subsystem for this. Use existing fingerprints, trace IDs, timestamps, and explicit cleanup seams.

## Backup Policy

Before destructive or hard-to-recreate operations, back up confirmed specs, legacy blueprints, pedagogical artifacts where user-edited, and asset manifests. Generated courseware, diagnostics, and exports can normally be rebuilt.
