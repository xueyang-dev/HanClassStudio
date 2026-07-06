# Agent Workflow

HanClassStudio can cooperate with Claude Code, Codex, Hermes, Cursor Agent, or a similar file-editing Agent. The Agent edits structured lesson artifacts; HanClassStudio validates, renders, runs quality, and exports.

## Before Editing

Every Agent should read:

1. `AGENTS.md`
2. `skills/hanclassstudio/SKILL.md`
3. `skills/hanclassstudio/references/artifact-ownership.md`
4. `skills/hanclassstudio/references/component-registry.md`
5. `skills/hanclassstudio/references/scaffolding-language.md`

The generated project task also appears in:

```text
runtime/projects/<project_id>/agent/AGENT_TASK.md
runtime/projects/<project_id>/agent/AGENT_RULES.md
```

## Files An Agent May Edit

- `specs/lesson_spec.md`
- `specs/spec_lock.json`
- `blueprints/lesson_blueprint.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`
- `assets/data/asset_manifest.json` only when media references are intentionally changed

## Files An Agent Must Not Edit

- `uploads/`
- `courseware/lesson.html`
- `exports/`
- generated ZIP files
- component names outside `courseware/components/registry.json`

The Agent should not bypass quality gate, invent runtime CSS, or treat `lesson.html` as source.

## Validate Agent Output

`POST /api/projects/{project_id}/agent/validate` checks external Agent edits before render/export.

It validates:

- required artifact presence
- JSON parseability
- `lesson_blueprint.json` schema
- duplicate component ids
- registry-compatible component names
- required component data fields
- whether render/quality artifacts still need to be regenerated

Validation does not render, export, or mutate `courseware/` and `exports/`. It returns readable `passed`, `warnings`, and `blocking` messages.

## Full Handoff Flow

1. Teacher uploads source material in HanClassStudio.
2. Teacher confirms the course profile.
3. HanClassStudio generates specs and blueprints.
4. Teacher clicks Agent Handoff.
5. HanClassStudio writes `agent/AGENT_TASK.md` and `agent/AGENT_RULES.md`.
6. The external Agent reads the rules and edits allowed artifacts.
7. Teacher returns to HanClassStudio and runs Validate Agent Output.
8. If validation is blocked, the Agent fixes artifacts.
9. If validation passes or only warns, HanClassStudio renders.
10. HanClassStudio runs the quality gate.
11. If quality is not blocked, HanClassStudio exports the offline ZIP.

This is the central demo point: HanClassStudio is not just a PPT-to-HTML converter. It is an agent-compatible interactive courseware pipeline with explicit artifacts and gates.

