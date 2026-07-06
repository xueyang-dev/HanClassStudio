# HanClassStudio Agent Guide

HanClassStudio is an AI interactive courseware generation system for international Chinese teaching. It turns source teaching materials into editable, offline-ready HTML courseware with Chinese as the target language and optional scaffolding in one teacher-selected support language.

All Agents must read `skills/hanclassstudio/SKILL.md` before modifying any HanClassStudio project files.

## Core Pipeline

```text
Source Intake
  -> Project Workspace
  -> Lesson Strategist
  -> Spec Lock
  -> Blueprint / Interaction / Media Plans
  -> Runtime Render
  -> Quality Gate
  -> Export
```

HanClassStudio expects external agents such as Claude Code, Codex, Hermes, or Cursor Agent to edit source workflow artifacts. HanClassStudio owns validation, rendering, quality gates, and export.

## Forbidden

- Do not directly edit `courseware/lesson.html`.
- Do not directly edit `exports/`.
- Do not modify `uploads/`.
- Do not invent components outside `courseware/components/registry.json`.
- Do not bypass the quality gate.

