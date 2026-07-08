# HanClassStudio Agent Guide

HanClassStudio is an AI interactive courseware generation system for international Chinese teaching. It turns source teaching materials into editable, offline-ready HTML courseware with Chinese as the target language and optional scaffolding in one teacher-selected support language.

All Agents must read `skills/hanclassstudio/SKILL.md` before modifying any HanClassStudio project files.

## Core Pipeline

HanClassStudio uses a **State-first** architecture ([docs/state-evidence-kernel-v0.2.2.md](docs/state-evidence-kernel-v0.2.2.md)):

```text
Source
  → Learning State Plan
  → Learning Goal / Evidence / Activity
  → Presentation Plan
  → Render
```

Current working pipeline:
```text
Source Intake
  → Project Workspace
  → Source Lesson Profile
  → Learner Model
  → Language Items
  → Blueprint / Interaction / Media Plans
  → Courseware Review Agent
  → Revision Plan Application
  → Runtime Render
  → Quality Gate
  → Export
```

HanClassStudio expects external agents such as Claude Code, Codex, Hermes, or Cursor Agent to edit source workflow artifacts. HanClassStudio owns validation, rendering, quality gates, and export.

## Forbidden

- Do not directly edit `courseware/lesson.html`.
- Do not directly edit `exports/`.
- Do not directly edit generated `.pptx` exports.
- Do not modify `uploads/`.
- Do not invent components outside `courseware/components/registry.json`.
- Do not bypass the quality gate.
