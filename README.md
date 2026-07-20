<div align="center">

# HanClassStudio

**AI 辅助语言教学课件生成器 — 面向国际中文教育**

[![测试](https://img.shields.io/badge/tests-498%20passed-brightgreen)](#)
[![阶段](https://img.shields.io/badge/phase-2C%20内部验证-yellow)](#)
[![许可](https://img.shields.io/badge/license-MIT-blue)](#)

**简体中文** · [English](README.en.md)

</div>

---

## 项目简介

HanClassStudio 是一个开源的 AI 辅助互动课件生成系统，专为**语言教学**场景而设计。它不是一个幻灯片设计工具，而是一个**教学内核编译器**。

它的工作方式很简单：上传你的教材（PPTX 或 PDF），设置课程信息，运行流水线。系统会自动分析教材内容，规划教学目标与认知状态转移路径，生成可离线的 HTML 互动课件和可编辑的传统 PPTX 课堂课件。整个过程不需要写代码。

核心设计理念是 **状态优先、证据优先**：系统先问"学习者当前处于什么状态？要到达什么状态？什么证据能证明状态转移？什么活动能采集证据？"，然后才决定如何呈现。Renderer（渲染器）只负责编译已审校通过的内容，不做教学判断。

---

## 项目状态

```
Phase 2B：基本完成
Phase 2C：内部技术验证完成
真实教学验证：尚未开始
生产 v2 cutover：尚未开始
```

当前代码库已具备完整的功能流水线：从教材上传、AI 分析、教学内核生成、课件审校、自动修订，到 HTML/PPTX 双端导出和质量门禁。

**下一步优先事项**：进行三节真实中文微课的教师主导 Pilot。浏览器自动化是并行支撑项，不阻塞真实审课。欢迎关注和贡献。

完整路线图请参见 [docs/roadmap.md](docs/roadmap.md)。

---

## 功能特性

### 教学内核

- **State-Evidence 内核** — 基于认知状态转移的课件编译器。先定义学习目标，再规划证据、活动和呈现方式，而非直接堆砌幻灯片页面。
- **学习者理解力引擎** — i+1 可理解输入约束引擎，自动控制每页生词量、分离母语与目标语、检测超纲内容。语言无关设计，未来可适配英语、日语、韩语、阿拉伯语等。
- **课件审校智能体** — 四维审校（适宜性、可执行性、可维护性、可用性），能自动发现不适合零基础学生的活动类型、暴露的教师标签、缺失的母语释义等问题，并生成修订方案。
- **自动修订** — 基于审校结果的修订计划能自动执行，替换不适合的活动、改写标题、将答案移入讲师备注。

### 输出端

- **HTML 互动课件** — 离线可用，幻灯片式切换，无需网络。内含词卡翻转、听音选择、场景配对等互动组件。学生端页面不显示调试信息、教师标签或证据 ID。
- **传统 PPTX 课件** — 8 种教学版式（单词聚焦、双卡对比、对话气泡、配对练习等），含讲师备注（教学步骤、答案、证据信息），不显示组件名或 debug 标签。
- **ZIP 离线包** — 一键打包，含 HTML 课件、图片、音频、元数据，解压即用。

### 质量保障

- **证据对齐门禁** — 检查每个学习目标是否有对应的证据规格、每个证据是否有采集活动、活动类型是否适合学习者水平。阻断不一致的课件输出。
- **课堂安全门禁** — 检查课件是否泄露教师用语、是否包含不适合学生的 debug 信息、母语释义词表是否完整。
- **超纲检测** — 对照教材范围和学习者级别，标记超越大纲的内容。
- **课件结构检查** — 检查 PPTX 是否有组件标签泄露、答案是否暴露在页面上、是否有空的占位块。

### 媒体策略（SVG 与栅格双轨）

- **栅格轨** — 人物动作、情境插画、课堂主图由外部/低成本图像 Provider 生成 PNG。
- **确定性 SVG 轨** — 图标、结构图、简单语义图、离线兜底由锁定契约 + 注册组件库确定性渲染，无网络依赖。
- 两条轨通过 `MediaRequirements.media_kind`（`"raster"` / `"svg_illustration"`）区分，互不替代。完整职责边界、接线与栅格 Provider 交接见 [`docs/svg_media_strategy.md`](docs/svg_media_strategy.md)。

### 其他

- **多语言配置** — 内置阿拉伯语、泰语、韩语、日语、英语的常用词汇对照表，用于课堂课件中的母语释义。
- **多语言 UI** — 教师工作台支持中文、英文、日文、韩文、阿拉伯文、俄文六种界面语言。
- **呈现契约** — v2 使用内容、媒体请求、抽象绑定和规范呈现蓝图；当前 v1 slide/component binding 仅保留为生产 renderer 兼容合同。

---

## 架构总览

```text
教材 (PPTX/PDF)
  ├─ 教材分析（抽取词汇、语法、对话、练习）
  ├─ 学习者模型（水平、已知词、限制条件）
  ├─ 语言项目（目标词、释义、用法场景）
  ├─ 学习状态计划     ← 教学内核
  ├─ 证据计划
  ├─ 活动计划
  ├─ 证据对齐门禁
  ├─ 呈现内容与媒体
  ├─ 呈现绑定契约     ← v2 新架构
  ├─ 规范呈现蓝图
  ├─ 兼容适配层
  ├─ HTML / PPTX 渲染
  ├─ 质量门禁
  └─ 导出
```

Render 层是后端编译器，不做教学判断。它只渲染已被审校通过的学生端内容和教师端内容。

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）

### 安装

```bash
git clone https://github.com/xueyang-dev/HanClassStudio.git
cd HanClassStudio

# 后端依赖
cd apps/api
uv sync
cd ../..

# 前端依赖
cd apps/web
npm install
cd ../..

# 根目录脚本
npm install
```

### 启动

```bash
# 启动 API 服务（FastAPI，端口 8000）
npm run dev:api

# 启动教师工作台（Vite + React，端口 5173）
# 另开一个终端窗口
npm run dev:web
```

### 使用流程

1. 浏览器打开 `http://localhost:5173`
2. 上传 PPTX 或 PDF 教材文件
3. 设置课程信息（标题、学生水平、母语语言、课型等）
4. 点击"运行流水线"
5. 在 Artifact Inspector 面板中查看生成的各个产物
6. 导出 ZIP 离线课件包或 PPTX 课堂课件

### 运行测试

```bash
npm test            # 全部测试（后端 + 前端构建）
npm run test:api    # 仅后端测试
npm run build:web   # 前端构建校验
```

当前测试：**498 passed，1 skipped**（后端测试 + 前端构建 + 状态契约）。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [路线图](docs/roadmap.md) | 项目阶段规划与里程碑 |
| [State-Evidence 内核白皮书](docs/state-evidence-kernel-v0.2.2.md) | 教学内核架构详细设计 |
| [呈现绑定规范](docs/presentation-bindings-v0.2.2.md) | v2 呈现契约规格说明 |
| [架构总览](docs/architecture-overview.md) | 系统设计与组件关系 |
| [HanClass Provider Hub](docs/provider-hub.md) | Provider 能力模型、刷新/安装任务、安全边界与扩展指南 |
| [Codex Provider 桥接](docs/codex-provider-bridge.md) | Codex ChatGPT / Image 的鉴权、任务与验证契约 |
| [冒烟测试报告](docs/smoke-test-v0.2.1.md) | v0.2.1-alpha 端到端验证 |
| [演示脚本](docs/demo-script.md) | 3–5 分钟快速演示稿 |
| [贡献指南](CONTRIBUTING.md) | 参与项目贡献的规范 |

---

## 项目结构

```
HanClassStudio/
├── apps/
│   ├── api/                   # FastAPI 后端（核心引擎所在）
│   │   └── src/hcs_api/       # 流水线、渲染、内核、审校等
│   └── web/                   # React 教师工作台
├── docs/                      # 文档
├── skills/                    # AI 智能体协作规范
├── architecture/              # 架构设计文档
├── output/                    # 生成的课件输出
├── runtime/                   # 运行时项目数据
├── README.md                  # 本文件（简体中文）
├── README.en.md               # 英文版 README
└── CONTRIBUTING.md            # 贡献指南
```

---

## 许可

本项目基于 MIT 许可协议开源。

---

## 致谢

在 Claude Code、Codex、Hermes Agent、DeepSeek 等 AI 开发工具的协助下构建。
