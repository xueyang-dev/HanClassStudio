# Project Structure And Artifact Ownership

## Repository Structure

Target repository layout:

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
    brands/
    pedagogy/
    runtimes/
    courseware/
  runtime/
    config/
    projects/
  README.md
  package.json
```

`courseware/` contains reusable runtime assets. `runtime/` contains generated local projects and should stay ignored by Git.

## Runtime Project Layout

Each generated lesson project should be self-contained:

```text
runtime/projects/<project_id>/
  README.md
  uploads/
    original.pptx
    original.pdf

  sources/
    source_material.json
    source.md
    source_assets/

  analysis/
    source_profile.json
    image_inventory.json
    teaching_candidates.json
    source_warnings.json

  specs/
    lesson_spec.md
    spec_lock.json

  blueprints/
    lesson_blueprint.json
    interaction_plan.json
    media_plan.json

  assets/
    images/
    audio/
    video/
    fonts/
    data/
      lesson_profile.json
      asset_manifest.json
      attribution.json

  courseware/
    lesson.html
    render_manifest.json

  quality/
    quality_report.json
    quality_summary.md

  exports/
    HanClassStudio_Output_<timestamp>.zip
    export_manifest.json

  backup/
    <timestamp>/
      blueprints/
      specs/
      assets/data/
```

## Artifact Ownership

| Artifact | Owner | Source or derived | Can be rebuilt |
|---|---|---:|---:|
| `uploads/*` | user | source | no |
| `sources/source_material.json` | intake | source contract | yes, from uploads |
| `sources/source.md` | intake | source contract | yes, from uploads |
| `analysis/source_profile.json` | intake analysis | machine fact | yes |
| `analysis/image_inventory.json` | intake/media analysis | machine fact | yes |
| `specs/lesson_spec.md` | strategist | author/design source | partially |
| `specs/spec_lock.json` | strategist/user confirmation | execution source | no, after confirmation |
| `blueprints/lesson_blueprint.json` | strategist/user editor | author source | partially |
| `blueprints/interaction_plan.json` | strategist/user editor | author source | partially |
| `blueprints/media_plan.json` | strategist/media planner | author source | partially |
| `assets/images/*` | media generator or user | runtime source | maybe |
| `assets/audio/*` | media generator or user | runtime source | maybe |
| `assets/data/asset_manifest.json` | media generator | execution source | yes, if assets exist |
| `courseware/lesson.html` | renderer | derived | yes |
| `quality/quality_report.json` | quality gate | derived | yes |
| `exports/*.zip` | exporter | delivery snapshot | yes |

## Source Of Truth Rules

| Rule | Reason |
|---|---|
| Do not edit `lesson.html` as the source of truth | It is derived from blueprints, assets, specs, and runtime templates. |
| Do not put teaching decisions only in chat | They must land in `lesson_spec.md` or `spec_lock.json`. |
| Do not let renderer invent interactions | Interactions come from `interaction_plan.json` or `lesson_blueprint.json`. |
| Do not let quality checks mutate artifacts | They report, then the pipeline or user fixes upstream artifacts. |
| Do not export without recording quality state | Teachers need to know whether the package is clean, warned, or blocked. |

## Rebuild Paths

| Need | Rebuild from |
|---|---|
| Re-render HTML | `spec_lock.json` + blueprints + assets + runtime template |
| Regenerate media | `media_plan.json` + provider settings |
| Re-run quality | blueprints + asset manifest + courseware output |
| Rebuild ZIP | `courseware/lesson.html` + `assets/` + data manifests |
| Rebuild source facts | `uploads/` |

## Backup Policy

Before destructive or hard-to-recreate operations, create:

```text
backup/<timestamp>/
  specs/
  blueprints/
  assets/data/
```

Backup is most important before:

- regenerating a blueprint
- applying a template
- replacing all media assets
- exporting a delivery version

