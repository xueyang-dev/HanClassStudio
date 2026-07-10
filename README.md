# HanClassStudio

> **AI-powered interactive courseware generator for language teaching / 面向语言教学的 AI 互动课件生成器**

[![npm test](https://img.shields.io/badge/tests-70%20passed-brightgreen)](#)
[![Phase](https://img.shields.io/badge/phase-2C%20internal%20validation-yellow)](#)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)

**English** | [中文](#概要)

---

## Overview / 概要

**English** — HanClassStudio is an open-source, AI-assisted interactive courseware generation system purpose-built for language teaching. It turns source teaching materials (PPTX/PDF) into offline-ready HTML courseware and editable Traditional PPTX classroom decks — all through a **State-first, Evidence-first** pedagogical compiler.

The system is not a slide designer. It is a **teaching-kernel compiler**: it builds a structured learning plan, defines verifiable evidence for each cognitive transition, plans activities, and then compiles those contracts into learner-facing HTML or teacher-facing PPTX.

**中文** — HanClassStudio 是一个开源、AI 辅助的互动课件生成系统，专为语言教学场景而设计。它可将源教材（PPTX/PDF）编译为可离线的 HTML 互动课件和可编辑的 Traditional PPTX 课堂课件，核心驱动是一个**状态优先、证据优先**的教学内核编译器。

这不是一个幻灯片设计工具，而是一个**教学内核编译器**：构建结构化的学习计划，为每个认知状态转移定义可验证的证据，规划教学活动，然后将这些契约编译成面向学生的 HTML 课件或面向教师的 PPTX 课件。

---

## Project Status / 项目状态

```
Phase 2B: substantially complete           ✅
Phase 2C: internal technical validation    ✅
Real teaching pilot:                       ⏳ not started
Production v2 cutover:                     ⏳ not started
```

| Milestone | Status |
|-----------|--------|
| v0.1 demo loop (Workbench, export, quality gates) | ✅ Verified |
| v0.2.1-alpha State-Evidence Kernel | ✅ Smoke-tested, 70 tests |
| Shadow v2 presentation path | ✅ Phase 2B complete |
| Internal HTML route (phase 2C) | ✅ disabled-by-default, validated |
| **Next: 3-lesson teacher-led pilot** | 🎯 **Immediate priority** |

The authoritative roadmap is [docs/roadmap.md](docs/roadmap.md).

权威路线图请参见 [docs/roadmap.md](docs/roadmap.md)。

---

## Features / 功能特性

| Feature | Description |
|---------|-------------|
| **State-Evidence Kernel** | Cognitive-state-first lesson compiler: goals → evidence → activities → presentation |
| **Learner Comprehension Core** | i+1 constraint engine, word limits, scaffold separation, language-agnostic |
| **Courseware Review Agent** | 4-dimension review (Suitable / Workable / Sustainable / Usable) + revision plan |
| **Traditional PPTX Deck** | 8-layout classroom deck with speaker notes, no debug labels |
| **HTML Interactive Courseware** | Offline-ready, slide-based, zero external dependencies |
| **Language Profiles** | Built-in Arabic / Thai / Korean / Japanese / English glossaries |
| **Scaffold Resolver** | Multi-language scaffold lookup with fallback chain |
| **Presentation Bindings** | Activity-to-component binding contract (v0.2.2) |
| **Quality Gates** | Evidence alignment, classroom safety, off-level detection, content leak checks |
| **Bilingual UI** | Teacher workbench in Chinese, with six-language i18n |

---

## Architecture / 架构

```text
Source (PPTX/PDF)
  → Source Lesson Profile
  → Learner Model
  → Language Items
  → Learning State Plan          ← Pedagogical kernel
  → Evidence Plan
  → Activity Plan
  → Evidence Alignment Gate
  → Presentation Content & Media
  → Presentation Bindings        ← v2 contract
  → Canonical Presentation Blueprint
  → Legacy Adapter
  → HTML / PPTX Renderers
  → Quality Gates
  → Export
```

### Core Philosophy / 核心哲学

> **State-first, not Slide-first.** The system first asks: "What cognitive state is the learner in? What state should they reach? What evidence proves the transition? What activity collects that evidence?" — only then does it decide how to present the lesson.

Renderers are backend compilers. They never make pedagogical decisions — they only render pre-approved learner-facing and teacher-facing content.

> **状态优先，而非页面优先。** 系统首先问："学习者当前处于什么认知状态？目标状态是什么？什么证据能证明状态转移？什么活动能采集这个证据？"——然后才决定如何呈现。

Render 层是后端编译器，不做教学判断，只渲染已被审校通过的学生端和教师端内容。

---

## Quick Start / 快速开始

### Prerequisites / 环境要求

- Python 3.11+
- Node.js 18+
- uv (Python package manager)

### Install / 安装

```bash
# Clone
git clone https://github.com/xueyang-dev/HanClassStudio.git
cd HanClassStudio

# Backend
cd apps/api
uv sync
cd ../..

# Frontend
cd apps/web
npm install
cd ../..

# Root scripts
npm install
```

### Run / 运行

```bash
# Start API server (FastAPI)
npm run dev:api

# Start web workbench (Vite + React) — in another terminal
npm run dev:web

# Run tests
npm test

# Build frontend
npm run build:web
```

### Pipeline Demo / 流水线演示

1. Open `http://localhost:5173` in browser
2. Upload a PPTX or PDF source material
3. Set lesson profile (level, scaffold language, title)
4. Run pipeline
5. Inspect artifacts in the Artifact Inspector panel
6. Export ZIP or PPTX

---

## Documentation / 文档

| Document | Description |
|----------|-------------|
| [Roadmap](docs/roadmap.md) | Authoritative project roadmap and phase planning |
| [State-Evidence Kernel](docs/state-evidence-kernel-v0.2.2.md) | White paper: teaching kernel architecture |
| [Presentation Bindings](docs/presentation-bindings-v0.2.2.md) | v2 presentation contract specification |
| [Architecture Overview](docs/architecture-overview.md) | System design and component relationships |
| [Smoke Test Report](docs/smoke-test-v0.2.1.md) | v0.2.1-alpha end-to-end verification |
| [Agent Workflow](docs/agent-workflow.md) | Guide for AI agents working with this codebase |
| [Demo Script](docs/demo-script.md) | 3-5 minute walkthrough script |

---

## Project Structure / 项目结构

```
HanClassStudio/
├── apps/
│   ├── api/                   # FastAPI backend
│   │   └── src/hcs_api/       # Core engine
│   │       ├── pipeline.py    # Main pipeline orchestrator
│   │       ├── agents.py      # Blueprint generation
│   │       ├── analysis.py    # Source material parser
│   │       ├── renderer.py    # HTML renderer
│   │       ├── pptx_exporter.py  # PPTX exporter
│   │       ├── state_evidence_kernel.py  # SE kernel
│   │       ├── review_agent.py  # Courseware review
│   │       ├── content_contract.py  # Scaffold resolver
│   │       ├── learner_comprehension.py  # i+1 engine
│   │       ├── syllabus_engine.py  # Syllabus-aware planning
│   │       ├── pptx_deck.py   # Traditional PPTX deck plan
│   │       └── language_profiles/  # Multi-language glossaries
│   └── web/                   # React workbench UI
├── docs/                      # Documentation
├── skills/                    # Agent skill definitions
├── output/                    # Generated courseware
└── runtime/                   # Runtime project data
```

---

## Tests / 测试

```bash
# Run all tests
npm test

# Run only backend tests
npm run test:api

# Build frontend
npm run build:web
```

Current: **70 passed, 1 warning** (backend tests + frontend build).

---

## License / 许可

MIT

---

## Contributing / 贡献

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

This project is in active development. The immediate priority is a **three-lesson teacher-led pilot** — contributions that accelerate real teaching validation are especially welcome.

---

## Acknowledgments / 致谢

Built with the help of Claude Code, Codex, Hermes Agent, and DeepSeek.
