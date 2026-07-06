<div align="center">

# 🏫 HanClassStudio

**AI 赋能的国际中文教育互动课件生成平台**

[![v0.1 Demo](https://img.shields.io/badge/status-demo%20ready-blueviolet?style=flat-square)](https://github.com/xueyang-dev/HanClassStudio)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)](apps/api/pyproject.toml)
[![React](https://img.shields.io/badge/react-18-61DAFB?style=flat-square&logo=react)](apps/web/package.json)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi)](apps/api/pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

将 PPTX / PDF 教学材料一键转化为离线可用的互动 HTML 课件。  
为国际中文教师打造——支持拼音标注、语言支架、课堂互动组件，无需互联网即可在教室使用。

</div>

---

## 📖 简介

HanClassStudio 是一个**面向国际中文教育**的开源课件制作系统。它采用 AI Agent 工作流（AI Agent Workflow），将传统的教学材料（PPTX/PDF）转化为结构化的、可离线运行的互动 HTML 课件。

> **从课件到互动课堂，只需三步：上传 → 配置 → 生成**

### 为什么是 HanClassStudio？

- **🎯 专为中文教学设计** — 内置汉字书写、拼音标注、词汇翻卡等国际中文课堂专属组件
- **🤖 AI Agent 驱动** — 基于构件化 AI Agent 工作流，自动解析材料、生成教案、设计互动
- **📦 离线可用** — 导出的 HTML 课件完全离线运行，无需网络，不依赖 CDN
- **🔧 开放式架构** — 支持外部 AI Agent（Claude Code、Codex、Hermes、Cursor）协作编辑课件蓝图
- **🆓 开源 MIT 协议** — 完全免费，自由使用、修改和分发

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| **📂 材料导入** | 上传 PPTX / PDF 教学材料，自动解析页面内容 |
| **📋 教案生成** | AI 辅助生成课程画像、教案文档、教学蓝图 |
| **🎮 互动组件** | 内置 6 种课堂互动组件（翻卡、拖拽造句、听音选择、配对游戏、汉字书写、音频按钮） |
| **🌐 语言支架** | 可选择教师支持语言，双语对照呈现，降低初学者理解门槛 |
| **🧪 质量门禁** | 导出前自动检查课件完整性、组件兼容性、资源完整性 |
| **📦 离线导出** | 一键打包为 ZIP，内含完整 HTML + 素材 + 教案数据，离线解压即用 |
| **🤝 Agent 协作** | 支持将课件蓝图导出给 AI Agent 编辑，完成后自动校验、渲染、导出 |
| **🔍 课件审查** | 内置 Artifact Inspector，可浏览项目每一阶段产出的结构化数据 |

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Web Workbench (React + Vite)              │
│  上传 → 画像 → 生成 → 预览 → 审查 → 导出                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────────┐
│                   FastAPI Backend (Python)                    │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ 材料解析  │→│ 教案策略  │→│ 蓝图生成  │→│ 课件渲染    │  │
│  │ PPTX/PDF │  │ 画像确认  │  │ 互动/媒体  │  │ HTML 输出  │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────┬─────┘  │
│                                                    │        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │        │
│  │ 质量门禁  │←│ 素材管理  │←│ 组件注册  │         │        │
│  └──────┬───┘  └──────────┘  └──────────┘         │        │
│         │                                          │        │
│  ┌──────▼──────────────────────────────────────────▼────┐  │
│  │              导出引擎 → ZIP 打包                      │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────┐           │
│  │        Agent Handoff (外部 AI 协作接口)       │           │
│  └──────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

每个课件项目在 `runtime/projects/<project_id>/` 下生成结构化工作区：

```
project/
├── uploads/          # 原始上传文件
├── sources/          # 解析后的素材数据
├── analysis/         # 分析中间产物
├── specs/            # 教案文档 + Spec Lock（执行契约）
├── blueprints/       # 课件蓝图、互动计划、媒体计划
├── assets/           # 图片、音频、视频、字体
├── courseware/       # 渲染后的 lesson.html
├── quality/          # 质量报告
├── exports/          # 导出的 ZIP 包
├── agent/            # Agent 协作任务文件
└── backup/           # 备份
```

---

## 🚀 快速开始

### 环境要求

- **Python** 3.11
- **Node.js** 18+
- **npm** 9+

### 安装

```bash
# 克隆仓库
git clone https://github.com/xueyang-dev/HanClassStudio.git
cd HanClassStudio

# 安装前端依赖
npm install
npm run install:web

# 安装后端依赖（使用 uv）
uv sync --project apps/api
```

### 启动

```bash
# 终端 1：启动后端 API（FastAPI）
npm run dev:api

# 终端 2：启动前端开发服务器（Vite）
npm run dev:web
```

打开浏览器访问 `http://localhost:5173`，上传一份 PPTX/PDF 教学材料，按照五步工作流体验完整流程。

### 运行测试

```bash
npm test
```

---

## 📋 工作流程

HanClassStudio 的课件生成遵循严格的分阶段流水线，每个阶段产出的制品（artifact）作为下一阶段的输入：

| 阶段 | 输入 | 产出 |
|------|------|------|
| **① 材料导入** | PPTX/PDF 文件 | `source_material.json` |
| **② 课程画像** | 解析后的素材 | 课程画像（水平、目标学生、教学模式、支架语言） |
| **③ 教案策略** | 课程画像 | `lesson_spec.md` + `spec_lock.json`（执行契约） |
| **④ 蓝图生成** | Spec Lock | `lesson_blueprint.json` + `interaction_plan.json` + `media_plan.json` |
| **⑤ 课件渲染** | 蓝图 + 媒体 | `courseware/lesson.html`（离线 HTML） |
| **⑥ 质量门禁** | 课件 HTML | `quality_report.json` + 通过/告警/阻塞 状态 |
| **⑦ 打包导出** | 所有制品 | ZIP 离线包 |

---

## 🎮 互动组件生态

| 组件 | 说明 | 状态 |
|------|------|------|
| `AudioButton` | 点击播放拼音/词语发音 | ✅ 已实现 |
| `VocabularyFlipCard` | 词汇翻卡——正面中文，反面释义 + 拼音 | ✅ 已实现 |
| `SentenceDragBuilder` | 拖拽词语组成完整句子 | ✅ 已实现 |
| `ListenAndChoose` | 听音选择正确答案 | ✅ 已实现 |
| `MatchGame` | 配对游戏——中文 ↔ 释义/图片 | ✅ 已实现 |
| `CharacterFormation` | 汉字书写笔顺演示 | ✅ 已实现 |

---

## 🧭 v0.1 路线图

### ✅ v0.1 — Demo Ready（当前版本）

- [x] PPTX/PDF 材料解析
- [x] 课程画像与教案策略
- [x] 课件蓝图 + 互动计划 + 媒体计划生成
- [x] 离线 HTML 课件渲染
- [x] 6 种互动组件
- [x] 语言支架（双语模式）
- [x] 质量门禁
- [x] ZIP 离线导出
- [x] Agent Handoff 接口
- [x] Artifact Inspector

### 🔜 下一阶段规划

- [ ] 真实 LLM 提供方接入（支持多模型切换）
- [ ] 图片生成 / TTS / OCR 提供方接入
- [ ] 多主题课件模板
- [ ] 课件蓝图可视化编辑器
- [ ] 流式生成进度（SSE/WebSocket）
- [ ] 更多课堂互动组件
- [ ] 项目版本管理与历史回溯
- [ ] LMS / SCORM 导出支持

---

## 📁 项目结构

```
HanClassStudio/
├── apps/
│   ├── api/              # FastAPI 后端
│   │   ├── src/hcs_api/  # API 源码
│   │   └── tests/        # 后端测试
│   └── web/              # React + Vite 前端
├── architecture/         # 架构设计文档
├── courseware/           # 课件运行时模板
│   └── components/       # 互动组件注册表
├── docs/                 # 项目文档
│   ├── demo-v0.1.md      # 演示指南
│   ├── architecture-overview.md
│   ├── agent-workflow.md
│   └── release-notes-v0.1.md
├── examples/             # 示例项目
├── skills/               # AI Agent 技能定义
│   └── hanclassstudio/   # HanClassStudio Agent 技能
├── AGENTS.md             # AI Agent 工作指南
├── CLAUDE.md             # Claude Code 配置
├── package.json          # 工作区配置
└── README.md             # 项目说明
```

---

## 🤝 如何贡献

我们欢迎任何形式的贡献！在开始之前，请先阅读 [AGENTS.md](AGENTS.md) 了解项目的 AI Agent 工作流约定。

### 贡献方式

- 🐛 **提交 Issue** — 发现 Bug 或有功能建议，请创建 [GitHub Issue](https://github.com/xueyang-dev/HanClassStudio/issues)
- 🛠️ **提交 PR** — Fork 仓库，在 `main` 分支上开发，提交 Pull Request
- 📖 **完善文档** — 改进文档、添加示例、翻译
- 💡 **分享反馈** — 在 Issue 中分享你的使用体验

### 开发须知

- 前端工作区：`apps/web`（React + TypeScript + Vite）
- 后端工作区：`apps/api`（Python + FastAPI + uv）
- 所有 AI Agent 修改应遵循 [skills/hanclassstudio/SKILL.md](skills/hanclassstudio/SKILL.md) 的流水线规定
- 不要直接编辑 `courseware/lesson.html`、`exports/` 和 `uploads/`

---

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。

---

<div align="center">
  Made with ❤️ for international Chinese educators and learners worldwide.
</div>
