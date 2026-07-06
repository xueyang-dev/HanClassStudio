# Demo Script: HanClassStudio v0.1

Target length: 3 to 5 minutes.

## 0:00-0:30 Opening

Show the browser with HanClassStudio workbench open.

Say:

"HanClassStudio is an agent-compatible interactive courseware pipeline for international Chinese teaching. It does not simply convert PPT into HTML. It turns source materials into structured teaching artifacts, validates them, renders interactive offline courseware, and exports a portable ZIP."

## 0:30-1:10 Upload And Profile

Click:

1. Upload PPTX/PDF.
2. Move to course profile.
3. Show title, learner level, target students, generation mode, and scaffolding language.
4. Click save profile.

Say:

"The teacher starts with familiar material. HanClassStudio parses the source, then asks the teacher to confirm pedagogical context before generation. This confirmation is a blocking gate."

## 1:10-1:50 One-Click Pipeline

Click:

1. Choose generation mode.
2. Click `一键生成课件`.
3. Show pipeline labels: Spec Lock, Blueprint, Media, Render, Quality, Export.
4. Show route badge and quality state.

Say:

"The pipeline is artifact-first. It writes a lesson spec, a spec lock, a lesson blueprint, interaction and media plans, then renders and checks quality. Later stages read canonical artifacts rather than guessing from UI state."

## 1:50-2:40 Runtime Preview

Show:

1. Slide-based `lesson.html` preview.
2. Previous/next controls.
3. Keyboard left/right.
4. Fullscreen button.
5. Slide list.
6. Chinese/scaffold/bilingual language toggle.
7. Vocabulary flip cards, sentence builder, listen-and-choose, matching, or character formation.

Say:

"The output is PPT-like interactive courseware, not a long web page. It is designed for projection: large type, strong whitespace, simple controls, and offline operation. Chinese remains the core, while the selected scaffolding language supports comprehension."

## 2:40-3:30 Agent Handoff

Click:

1. Agent Handoff panel.
2. Generate Agent task.
3. Show `AGENT_TASK.md` and `AGENT_RULES.md`.
4. Click Validate Agent Output.
5. Show Artifact Inspector with `agent/`, `specs/`, `blueprints/`, `quality/`, and `exports/`.

Say:

"This is where HanClassStudio becomes agent-compatible. Claude Code, Codex, Hermes, or Cursor Agent can edit the structured artifacts: lesson spec, spec lock, blueprint, interaction plan, and media plan. The Agent is not allowed to edit the rendered HTML or exports. HanClassStudio validates the result before rendering and export."

## 3:30-4:20 Export

Click:

1. Download ZIP.
2. Open the ZIP contents or explain expected files.
3. Open `lesson.html` offline if time allows.

Say:

"The export includes the offline courseware, assets, canonical data artifacts, quality report, and export manifest. If quality is blocked, normal export is prevented. Demo force export is explicit and recorded."

## 4:20-5:00 Close

Say:

"v0.1 proves the core product loop: teacher confirmation, artifact-first generation, Agent Handoff, quality gate, and offline interactive courseware. The next stage is real provider integration for LLM, image, TTS, OCR, and video, plus richer templates and teacher review workflows."

