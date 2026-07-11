# Portfolio Copy

## 中文项目简介

HanClassStudio 是一个面向国际中文教学的 AI 互动课件生成系统。它不是简单的 PPT 转 HTML 工具，而是把源课件解析为结构化教学 artifacts，再通过 lesson spec、spec lock、组件注册表、质量门禁和离线 HTML runtime，生成可投屏、可互动、可导出的中文课堂课件。

v0.1 版本验证了 demo-ready 闭环：教师上传 PPTX/PDF，确认课程信息，系统生成互动课件蓝图和媒体计划，渲染 slide-based `lesson.html`，运行质量检查，并导出可离线打开的 HTML ZIP 或可编辑课堂展示 PPTX。Phase 2B 建立 State-Evidence Kernel 与 shadow canonical presentation compiler；Phase 2C 完成 disabled-by-default 的内部技术验证。目前生产 HTML/PPTX/ZIP 仍使用 legacy LessonBlueprint 路径，真实教学验证尚未开始。

## English Project Summary

HanClassStudio is an AI-assisted interactive courseware generation system for international Chinese teaching. It is not a simple PPT-to-HTML converter. It transforms source teaching material into structured lesson artifacts, then uses a lesson spec, spec lock, component registry, quality gate, and offline HTML runtime to produce classroom-ready interactive courseware.

The v0.1 demo proves the end-to-end production loop: upload PPTX/PDF, confirm the course profile, generate structured lesson artifacts, render slide-based `lesson.html`, run quality checks, and export either an offline HTML ZIP or an editable classroom PPTX. Phase 2B adds a State-Evidence Kernel and a shadow canonical presentation compiler; Phase 2C validates a disabled-by-default internal HTML route for listening and matching lessons. Production exports still use the legacy LessonBlueprint contract, and real classroom validation has not started.

## One-Line Pitch Options

1. HanClassStudio turns Chinese lesson materials into agent-compatible interactive courseware with validation, quality gates, and offline export.
2. An artifact-first courseware pipeline where teachers, AI agents, and a quality gate collaborate before HTML export.
3. Not PPT-to-HTML: HanClassStudio is a structured interactive lesson pipeline for international Chinese classrooms.

## Technical Highlights

- Artifact-first workspace under `runtime/projects/<project_id>`.
- Pedagogical authoritative artifacts: learning state, evidence, and activity plans plus the evidence alignment gate.
- Canonical v2 presentation artifacts: presentation content, media requests, abstract bindings, and presentation blueprint.
- Legacy production compatibility artifacts: `lesson_blueprint.json`, v1 activity bindings, interaction plan, and media plan.
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
- The v2 internal route is limited to whole lessons containing only `listening_choice` and `matching_response`.
- Visual parity, classroom usability, editing cost, and teacher/learner acceptance remain unverified.
- Project persistence is local development storage, not a multi-user production library.

## Historical v0.2 Roadmap

This list records an earlier planning snapshot. It is not the current delivery order; see [roadmap.md](roadmap.md).

- Harden `presentation/activity_bindings.json` with teacher confirmation for low-confidence bindings.
- Provider layer for LLM, image generation, TTS, OCR, and video.
- Template discovery and multiple runtime themes.
- Teacher review checkpoints for Agent edits.
- Richer component authoring UI.
- More classroom activity components.
- Streaming pipeline progress.
- Project library, version history, and better restore flows.
- LMS-oriented export formats.
