<div align="center">

# HanClassStudio

**AI-assisted interactive courseware generator for language teaching**

[![tests](https://img.shields.io/badge/tests-297%20passed-brightgreen)](#)
[![phase](https://img.shields.io/badge/phase-2C%20internal%20validation-yellow)](#)
[![license](https://img.shields.io/badge/license-MIT-blue)](#)

[简体中文](README.md) · **English**

</div>

---

## Overview

HanClassStudio is an open-source, AI-assisted interactive courseware generation system purpose-built for **language teaching**. It is not a slide designer — it's a **teaching-kernel compiler**.

Upload your source material (PPTX or PDF), configure the lesson profile, and run the pipeline. The system analyzes the material, models cognitive state transitions for your learners, defines verifiable evidence, plans activities, and compiles everything into offline-ready HTML courseware or editable Traditional PPTX classroom decks. No coding required.

The core philosophy is **State-first, Evidence-first**: instead of asking "what goes on this slide", the system first asks "what cognitive state is the learner in? what state should they reach? what evidence proves the transition? what activity collects that evidence?" — only then does it decide how to present. The renderer is a backend compiler that never makes pedagogical decisions.

---

## Project Status

```
Phase 2B: substantially complete            ✅
Phase 2C: internal technical validation     ✅
Real teaching pilot:                        ⏳ not started
Production v2 cutover:                      ⏳ not started
```

The codebase now has a complete production pipeline — from material upload and AI analysis to teaching kernel generation, courseware review, auto-revision, dual HTML/PPTX export, and quality gates.

**Next milestone**: a three-lesson teacher-led pilot. Contributions and feedback are welcome.

The authoritative roadmap is [docs/roadmap.md](docs/roadmap.md).

---

## Features

### Teaching Kernel

- **State-Evidence Kernel** — A cognitive-state-first lesson compiler. Defines learning goals, then plans evidence, activities, and presentation — rather than just stacking slides.
- **Learner Comprehension Engine** — i+1 input constraint engine that controls per-slide new-word limits, separates scaffold from target language, and detects off-level content. Language-agnostic by design.
- **Courseware Review Agent** — 4-dimension review (Suitable, Workable, Sustainable, Usable). Automatically detects activities unsuitable for zero-beginners, exposed teacher labels, missing scaffold glosses, and generates revision plans.
- **Auto-Revision** — Revision plans are automatically applied: replacing inappropriate activities, rewriting titles, moving answer keys into speaker notes.

### Output

- **HTML Interactive Courseware** — Offline-ready, slide-based, zero network required. Includes flip cards, listen-and-choose, scene matching and other interactive components. No debug info, teacher labels, or evidence IDs leak into the learner view.
- **Traditional PPTX Deck** — 8 classroom layouts (single-word focus, two-card contrast, dialogue bubbles, match pairs, etc.) with speaker notes containing teaching steps, answers, and evidence info. No component labels or debug text.
- **ZIP Offline Package** — One-click export with HTML, images, audio, and metadata. Unzip and use immediately.

### Quality Assurance

- **Evidence Alignment Gate** — Verifies that every learning goal has a corresponding evidence spec, every evidence has a collecting activity, and every activity fits the learner level. Blocks misaligned courseware output.
- **Classroom Safety Gate** — Checks for leaked teacher-only text, debug information, missing scaffold meanings, and inappropriate activity types.
- **Off-Level Detection** — Compares content against the source scope and learner level, flagging out-of-scope items.
- **PPTX Structure Check** — Detects component label leaks, exposed answer keys, empty placeholder blocks, and missing traditional layouts.

### Other

- **Language Profiles** — Built-in Arabic, Thai, Korean, Japanese, and English glossaries for classroom scaffolding.
- **i18n UI** — Teacher workbench supports 6 interface languages: Chinese, English, Japanese, Korean, Arabic, Russian.
- **Presentation Bindings** — Formal activity-to-component binding contract (v0.2.2), replacing the current heuristic vocabulary-based evidence mapping.

---

## Architecture

```text
Source (PPTX/PDF)
  ├─ Source Analysis (vocabulary, grammar, dialogues, exercises)
  ├─ Learner Model (level, known words, constraints)
  ├─ Language Items (target words, glosses, usage contexts)
  ├─ Learning State Plan     ← Pedagogical kernel
  ├─ Evidence Plan
  ├─ Activity Plan
  ├─ Evidence Alignment Gate
  ├─ Presentation Content & Media
  ├─ Presentation Bindings   ← v2 contract
  ├─ Canonical Presentation Blueprint
  ├─ Legacy Compatibility Adapter
  ├─ HTML / PPTX Renderers
  ├─ Quality Gates
  └─ Export
```

Renderers are backend compilers. They never make pedagogical decisions — they only render pre-approved learner-facing and teacher-facing content.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Install

```bash
git clone https://github.com/xueyang-dev/HanClassStudio.git
cd HanClassStudio

# Backend dependencies
cd apps/api
uv sync
cd ../..

# Frontend dependencies
cd apps/web
npm install
cd ../..

# Root scripts
npm install
```

### Run

```bash
# Start API server (FastAPI, port 8000)
npm run dev:api

# Start workbench (Vite + React, port 5173)
# Open a separate terminal
npm run dev:web
```

### Workflow

1. Open `http://localhost:5173` in your browser
2. Upload a PPTX or PDF source file
3. Configure the lesson profile (title, learner level, scaffold language, lesson type)
4. Click "Run Pipeline"
5. Inspect generated artifacts in the Artifact Inspector panel
6. Export ZIP offline package or PPTX classroom deck

### Tests

```bash
npm test            # All tests (backend + frontend build)
npm run test:api    # Backend tests only
npm run build:web   # Frontend build check
```

Current: **297 passed** (backend tests + frontend build).

---

## Documentation

| Document | Description |
|----------|-------------|
| [Roadmap](docs/roadmap.md) | Project phases and milestones |
| [State-Evidence Kernel](docs/state-evidence-kernel-v0.2.2.md) | Teaching kernel architecture (white paper) |
| [Presentation Bindings](docs/presentation-bindings-v0.2.2.md) | v2 contract specification |
| [Architecture Overview](docs/architecture-overview.md) | System design and component relationships |
| [Smoke Test Report](docs/smoke-test-v0.2.1.md) | v0.2.1-alpha end-to-end verification |
| [Demo Script](docs/demo-script.md) | 3–5 minute walkthrough |
| [Contributing Guide](CONTRIBUTING.md) | How to contribute |

---

## Project Structure

```
HanClassStudio/
├── apps/
│   ├── api/                   # FastAPI backend (core engine)
│   │   └── src/hcs_api/       # Pipeline, rendering, kernel, review
│   └── web/                   # React teacher workbench
├── docs/                      # Documentation
├── skills/                    # Agent collaboration specs
├── architecture/              # Architecture design docs
├── output/                    # Generated courseware
├── runtime/                   # Runtime project data
├── README.md                  # This file (Chinese)
├── README.en.md               # English README
└── CONTRIBUTING.md            # Contribution guidelines
```

---

## License

MIT

---

## Acknowledgments

Built with the assistance of Claude Code, Codex, Hermes Agent, and DeepSeek.
