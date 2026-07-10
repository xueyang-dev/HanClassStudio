# HanClassStudio

> **AI 辅助语言教学课件生成器 — 面向国际中文教育**

[![npm test](https://img.shields.io/badge/tests-297%20passed-brightgreen)](#)
[![Phase](https://img.shields.io/badge/phase-2C%20内部验证-yellow)](#)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)

[**English**](README.en.md) | **简体中文**

---

## 概述

HanClassStudio 是一个开源的、AI 辅助的互动课件生成系统，专为**语言教学**场景而设计。它不是一个幻灯片设计工具，而是一个**教学内核编译器**：将教材（PPTX/PDF）编译成可离线的 HTML 互动课件和可编辑的传统 PPTX 课堂课件。

核心思路是**状态优先、证据优先**：先规划学习者的认知状态转移，定义可验证的学习证据，再决定如何呈现。Renderer 只负责编译——不做教学判断。

---

## 项目状态

```
Phase 2B: 基本完成               ✅
Phase 2C: 内部技术验证完成         ✅
真实教学 Pilot:                   ⏳ 未开始
生产环境 v2 切换:                 ⏳ 未开始
```

**下一步优先事项**：三轮真实课堂 Pilot 教学验证。

完整路线图请参见 [docs/roadmap.md](docs/roadmap.md)。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **State-Evidence 内核** | 认知状态优先的课件编译器：目标 → 证据 → 活动 → 呈现 |
| **学习者理解力引擎** | i+1 约束引擎、生词量限制、母语/目标语分离、语言无关 |
| **课件审校智能体** | 四维审校（适宜/可执行/可维护/可用）+ 自动修订方案 |
| **传统 PPTX 课件** | 8 种版式、含讲师备注、无调试标签泄露 |
| **HTML 互动课件** | 离线可用、幻灯片式切换、零外部依赖 |
| **语言配置** | 内置阿拉伯语/泰语/韩语/日语/英语词表 |
| **母语解释解析器** | 多语言查询，自动降级 |
| **呈现绑定契约** | 活动到组件的正式绑定（v0.2.2） |
| **质量门禁** | 证据对齐、课堂安全、超纲检测、内容泄露检查 |
| **多语言 UI** | 教师工作台支持中/英/日/韩/阿/俄六语 |

---

## 架构

```text
教材 (PPTX/PDF)
  → 教材分析
  → 学习者模型
  → 语言项目
  → 学习状态计划       ← 教学内核
  → 证据计划
  → 活动计划
  → 证据对齐门禁
  → 呈现内容与媒体
  → 呈现绑定           ← v2 契约
  → 规范呈现蓝图
  → 兼容适配层
  → HTML / PPTX 渲染
  → 质量门禁
  → 导出
```

Render 层是后端编译器，不做教学判断。它只渲染已经被审校通过的学生端内容和教师端内容。

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- uv（Python 包管理器）

### 安装

```bash
git clone https://github.com/xueyang-dev/HanClassStudio.git
cd HanClassStudio

# 后端
cd apps/api && uv sync && cd ../..

# 前端
cd apps/web && npm install && cd ../..

# 根目录脚本
npm install
```

### 运行

```bash
# 启动 API 服务（FastAPI）
npm run dev:api

# 启动教师工作台（Vite + React）— 另开终端
npm run dev:web

# 运行测试
npm test

# 构建前端
npm run build:web
```

### 使用流程

1. 浏览器打开 `http://localhost:5173`
2. 上传 PPTX 或 PDF 教材
3. 设置课程信息（级别、母语语言、标题）
4. 运行流水线
5. 在 Artifact Inspector 面板检查产物
6. 导出 ZIP 或 PPTX

---

## 文档

| 文档 | 说明 |
|------|------|
| [路线图](docs/roadmap.md) | 项目规划和阶段进展 |
| [State-Evidence 内核白皮书](docs/state-evidence-kernel-v0.2.2.md) | 教学内核架构 |
| [呈现绑定规范](docs/presentation-bindings-v0.2.2.md) | v2 呈现契约规格 |
| [架构总览](docs/architecture-overview.md) | 系统设计与组件关系 |
| [冒烟测试报告](docs/smoke-test-v0.2.1.md) | v0.2.1-alpha 端到端验证 |
| [演示脚本](docs/demo-script.md) | 3–5 分钟演示稿 |
| [贡献指南](CONTRIBUTING.md) | 参与贡献的规范 |

---

## 测试

```bash
npm test          # 全部测试
npm run test:api  # 仅后端测试
npm run build:web # 前端构建
```

当前：**297 passed**（后端测试 + 前端构建）。

---

## 许可

MIT

---

## 致谢

在 Claude Code、Codex、Hermes Agent、DeepSeek 的协助下构建。
