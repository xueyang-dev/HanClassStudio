# Expected Snapshot

The golden sample pipeline should produce:

- `sources/source_material.json`
- `specs/lesson_spec.md`
- `specs/spec_lock.json`
- `blueprints/lesson_blueprint.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`
- `assets/data/asset_manifest.json`
- `courseware/lesson.html`
- `quality/quality_report.json` with a `state` field
- `exports/HanClassStudio_Output_<timestamp>.zip`

The ZIP should include:

- `lesson.html`
- `assets/data/lesson_blueprint.json`
- `assets/data/asset_manifest.json`
- `assets/data/quality_report.json`

