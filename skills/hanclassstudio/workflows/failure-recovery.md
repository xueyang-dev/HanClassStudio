# Failure Recovery

Use the smallest upstream fix that makes the pipeline valid again.

## Schema Invalid

- Re-open the invalid JSON file.
- Fix syntax first.
- Validate the file against the expected artifact role.
- Re-run agent validation.

## Missing Asset

- Check `blueprints/media_plan.json` and `assets/data/asset_manifest.json`.
- Regenerate media through HanClassStudio when possible.
- If adding a manual asset, place it under `assets/images`, `assets/audio`, `assets/video`, or `assets/fonts` and update the manifest.

## Blocked Quality

- Read `quality/quality_report.json`.
- Fix `blocking` items in upstream artifacts, usually blueprints or asset manifests.
- Re-render and rerun quality.
- Do not export normally until state is not `blocked`.

## Missing Interaction Answer

- Locate the component in `blueprints/lesson_blueprint.json`.
- Add required answer fields according to `courseware/components/registry.json`.
- Ensure answers match choices or word lists where required.

## Render Failure

- Validate `specs/spec_lock.json`, `blueprints/lesson_blueprint.json`, and `assets/data/asset_manifest.json`.
- Remove unsupported components or invalid asset paths.
- Re-render through HanClassStudio.

## Export Failure

- Confirm `courseware/lesson.html` exists.
- Confirm latest quality state is not `blocked`, unless the user explicitly requests forced demo export.
- Re-run export through HanClassStudio.

