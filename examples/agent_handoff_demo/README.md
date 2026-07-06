# Agent Handoff Demo

This example explains how HanClassStudio can hand structured courseware work to Claude Code, Codex, Hermes, or Cursor Agent without letting the external agent render or export directly.

## Flow

1. HanClassStudio creates a project workspace and canonical artifacts.
2. The teacher generates an Agent package from the workbench.
3. The external Agent reads `AGENTS.md` and `skills/hanclassstudio/SKILL.md`.
4. The Agent edits `lesson_spec.md`, `spec_lock.json`, `lesson_blueprint.json`, `interaction_plan.json`, and `media_plan.json`.
5. HanClassStudio validates the output.
6. HanClassStudio renders, runs the quality gate, and exports.

## Demo Files

- `sample_agent_task.md`: task text copied from HanClassStudio.
- `sample_agent_response_plan.md`: a plausible external Agent plan.
- `expected_modified_blueprint_notes.md`: expected changes in the structured lesson artifacts.

The key point for a portfolio recording: the Agent changes the lesson design artifacts, while HanClassStudio remains responsible for validation, runtime rendering, quality policy, and ZIP export.
