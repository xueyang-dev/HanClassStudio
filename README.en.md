# HanClassStudio

> **AI-assisted interactive courseware generator for language teaching**

[![npm test](https://img.shields.io/badge/tests-297%20passed-brightgreen)](#)
[![Phase](https://img.shields.io/badge/phase-2C%20internal%20validation-yellow)](#)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)

**English** | [简体中文](README.md)

---

## Overview

HanClassStudio is an open-source, AI-assisted interactive courseware generation system purpose-built for **language teaching**. It is not a slide designer — it's a **teaching-kernel compiler** that takes source materials (PPTX/PDF) and compiles them into offline-ready HTML courseware and editable Traditional PPTX classroom decks.

The core philosophy is **State-first, Evidence-first**: instead of asking "what goes on this slide", the system first models the learner's cognitive state transitions, defines verifiable evidence for each transition, plans activities, and only then decides how to present. The renderer is a backend compiler — it never makes pedagogical judgments.

---

## Project Status

```
Phase 2B: substantially complete            ✅
Phase 2C: internal technical validation     ✅
Real teaching pilot:                        ⏳ not started
Production v2 cutover:                      ⏳ not started
```

**Next milestone**: a three-lesson teacher-led pilot.

The authoritative roadmap is [docs/roadmap.md](docs/roadmap.md).

---

## Features

| Feature | Description |
|---------|-------------|
| **State-Evidence Kernel** | Cognitive-state-first lesson compiler: goals → evidence → activities → presentation |
| **Learner Comprehension Engine** | i+1 constraint engine, word limits, scaffold/target language separation, language-agnostic |
| **Courseware Review Agent** | 4-dimension review (Suitable / Workable / Sustainable / Usable) with auto-revision |
| **Traditional PPTX Deck** | 8 layout templates, speaker notes, zero debug label leaks |
| **HTML Interactive Courseware** | Offline-ready, slide-based, zero external dependencies |
| **Language Profiles** | Built-in Arabic / Thai / Korean / Japanese / English glossaries |
| **Scaffold Resolver** | Multi-language lookup with automatic fallback chain |
| **Presentation Bindings** | Formal activity-to-component binding contract (v0.2.2) |
| **Quality Gates** | Evidence alignment, classroom safety, off-level detection, content leak checks |
| **i18n UI** | Teacher workbench in 6 languages (Chinese, English, Japanese, Korean, Arabic, Russian) |

---

## Architecture

```text
Source (PPTX/PDF)
  → Source Lesson Profile
  → Learner Model
  → Language Items
  → Learning State Plan       ← Pedagogical kernel
  → Evidence Plan
  → Activity Plan
  → Evidence Alignment Gate
  → Presentation Content & Media
  → Presentation Bindings     ← v2 contract
  → Canonical Presentation Blueprint
  → Legacy Compatibility Adapter
  → HTML / PPTX Renderers
  → Quality Gates
  → Export
```

Renderers are backend compilers. They never make pedagogical decisions — they only render pre-approved learner-facing and teacher-facing content.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- uv (Python package manager)

### Install

```bash
git clone https://github.com/xueyang-dev/HanClassStudio.git
cd HanClassStudio

# Backend
cd apps/api && uv sync && cd ../..

# Frontend
cd apps/web && npm install && cd ../..

# Root scripts
npm install
```

### Run

```bash
# Start API server (FastAPI)
npm run dev:api

# Start workbench (Vite + React) — in another terminal
npm run dev:web

# Run tests
npm test

# Build frontend
npm run build:web
```

### Workflow

1. Open `http://localhost:5173` in your browser
2. Upload a PPTX or PDF source
3. Configure lesson profile (level, scaffold language, title)
4. Run the pipeline
5. Inspect artifacts in the Artifact Inspector panel
6. Export ZIP or PPTX

---

## Documentation

| Document | Description |
|----------|-------------|
| [Roadmap](docs/roadmap.md) | Project phases and milestones |
| [State-Evidence Kernel](docs/state-evidence-kernel-v0.2.2.md) | White paper: teaching kernel architecture |
| [Presentation Bindings](docs/presentation-bindings-v0.2.2.md) | v2 contract specification |
| [Architecture Overview](docs/architecture-overview.md) | System design and component relationships |
| [Smoke Test Report](docs/smoke-test-v0.2.1.md) | v0.2.1-alpha end-to-end verification |
| [Demo Script](docs/demo-script.md) | 3–5 minute walkthrough |
| [Contributing Guide](CONTRIBUTING.md) | How to contribute |

---

## Tests

```bash
npm test          # Run all tests
npm run test:api  # Backend tests only
npm run build:web # Frontend build
```

Current: **297 passed** (backend tests + frontend build).

---

## License

MIT

---

## Acknowledgments

Built with the help of Claude Code, Codex, Hermes Agent, and DeepSeek.
