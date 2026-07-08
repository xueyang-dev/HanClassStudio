# Portfolio Copy

## 中文项目简介

HanClassStudio 是一个面向国际中文教学的 AI 互动课件生成系统。它不是简单的 PPT 转 HTML 工具，而是把源课件解析为结构化教学 artifacts，再通过 lesson spec、spec lock、组件注册表、质量门禁和离线 HTML runtime，生成可投屏、可互动、可导出的中文课堂课件。

v0.1 版本验证了 demo-ready 闭环：教师上传 PPTX/PDF，确认课程信息，系统生成互动课件蓝图和媒体计划，渲染 slide-based `lesson.html`，运行质量检查，并导出可离线打开的 HTML ZIP 或可编辑课堂展示 PPTX。当前 v0.2.1-alpha 进一步加入 State-Evidence Kernel，在渲染前生成学习状态、证据和活动契约，让教学逻辑可以独立审计。同时，HanClassStudio 支持 Agent Handoff，让 Claude Code / Codex / Hermes / Cursor Agent 修改结构化课件 artifacts，再由系统负责校验、渲染、质量门禁和导出。

## English Project Summary

HanClassStudio is an AI-assisted interactive courseware generation system for international Chinese teaching. It is not a simple PPT-to-HTML converter. It transforms source teaching material into structured lesson artifacts, then uses a lesson spec, spec lock, component registry, quality gate, and offline HTML runtime to produce classroom-ready interactive courseware.

The v0.1 demo proves the end-to-end loop: upload PPTX/PDF, confirm the course profile, generate structured lesson artifacts, render slide-based `lesson.html`, run quality checks, and export either an offline HTML ZIP or an editable classroom PPTX. The current pipeline adds a State-Evidence Kernel plus a formal presentation binding layer that connects learning states, evidence contracts, activities, slides, components, and teacher notes before rendering. It also supports Agent Handoff, allowing Claude Code, Codex, Hermes, or Cursor Agent to edit structured artifacts while HanClassStudio remains responsible for validation, rendering, quality policy, and export.

## One-Line Pitch Options

1. HanClassStudio turns Chinese lesson materials into agent-compatible interactive courseware with validation, quality gates, and offline export.
2. An artifact-first courseware pipeline where teachers, AI agents, and a quality gate collaborate before HTML export.
3. Not PPT-to-HTML: HanClassStudio is a structured interactive lesson pipeline for international Chinese classrooms.

## Technical Highlights

- Artifact-first workspace under `runtime/projects/<project_id>`.
- Canonical artifacts: `lesson_spec.md`, `spec_lock.json`, `lesson_blueprint.json`, `interaction_plan.json`, `media_plan.json`.
- Component registry as the single source of truth for supported runtime interactions.
- Agent Skill Layer through `AGENTS.md`, `skills/hanclassstudio/SKILL.md`, and Agent Handoff files.
- FastAPI backend with a React workbench frontend.
- Slide-based offline HTML runtime with no CDN dependency.
- Deterministic Editable PPTX exporter using native PowerPoint shapes and text boxes.
- State-Evidence Kernel artifacts: `learning_state_plan`, `evidence_plan`, `activity_plan`, and `evidence_alignment_report`.
- Quality gate with `pass`, `warning`, and `blocked` states.
- ZIP export with quality report and export manifest.
- Backend tests cover pipeline, export, registry consistency, Agent Handoff E2E, and runtime smoke.

## Product Highlights

- Designed for international Chinese teaching, not generic slide conversion.
- Chinese remains the target language; scaffolding language supports comprehension.
- Teacher confirmation gates for profile and blueprint.
- Project artifacts are inspectable and portable.
- Runtime supports slide navigation, fullscreen, language mode toggle, and interactive components.
- Editable PPTX supports classroom display and teacher editing when PowerPoint is required.
- Evidence-aware PPTX deck plans include teacher-facing evidence notes.
- Agent-compatible workflow lets external coding Agents improve lesson structure safely.
- Export package can be opened offline after unzipping.

## Current Limitations

- Real LLM, image generation, TTS, OCR, and video providers are not connected by default.
- Placeholder media is expected in v0.1.
- Runtime themes are fixed templates.
- Editable PPTX is a static classroom activity version, not a preservation of HTML interactions.
- Evidence alignment and the first formal `presentation/activity_bindings.json` contract are implemented; teacher-facing confirmation UX is still future work.
- Project persistence is local development storage, not a multi-user production library.

## v0.2 Roadmap

- Harden `presentation/activity_bindings.json` with teacher confirmation for low-confidence bindings.
- Provider layer for LLM, image generation, TTS, OCR, and video.
- Template discovery and multiple runtime themes.
- Teacher review checkpoints for Agent edits.
- Richer component authoring UI.
- More classroom activity components.
- Streaming pipeline progress.
- Project library, version history, and better restore flows.
- LMS-oriented export formats.
