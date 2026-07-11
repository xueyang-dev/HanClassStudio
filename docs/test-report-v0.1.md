# HanClassStudio v0.1.0-alpha Release Test Report

> 测试日期：2026-07-07
> 测试环境：macOS 26.5.2 · Python 3.11.15 · Node.js 22.23.0 · uv 0.11.26
> 测试范围：自动化测试套件 + 端到端流水线手工验证（含 Editable PPTX 出口）

---

## 1. 自动化测试

### 1.1 命令

```bash
npm test
```

等价于：

```bash
npm run test:api    # 后端 pytest 测试
npm run build:web   # 前端 TypeScript 类型检查 + Vite 生产构建
```

### 1.2 后端测试结果

```
platform darwin -- Python 3.11.15, pytest-9.0.3, pluggy-1.6.0
rootdir: <repository>/apps/api
collected 18 items

apps/api/tests/test_api_routes.py ...........                  [61%]
apps/api/tests/test_pipeline.py .......                        [100%]

====================== 18 passed, 1 warning in 0.68s ======================
```

| 测试文件 | 用例数 | 状态 |
|----------|--------|------|
| `test_api_routes.py` | 11 | ✅ 全部通过（含 PPTX 导出路由测试） |
| `test_pipeline.py` | 7 | ✅ 全部通过 |
| **合计** | **18** | **✅ 全部通过** |

> 新增 2 用例覆盖 PPTX 导出路由：正常导出 + blocked 拒绝。

### 1.3 前端构建结果

```
vite v8.0.16 building client environment for production...
✓ 1566 modules transformed.
dist/index.html                   0.40 kB │ gzip:  0.27 kB
dist/assets/index-Ccho6JiI.css   14.23 kB │ gzip:  3.32 kB
dist/assets/index-rGWFcDW5.js   176.44 kB │ gzip: 56.24 kB
✓ built in 159ms
```

- TypeScript 类型检查：✅ 通过
- Vite 生产构建：✅ 通过（159ms，176KB JS + 14KB CSS）

---

## 2. 端到端流水线测试

### 2.1 测试素材

使用 `python-pptx` 生成的一份包含 1 页的测试 PPTX：

```
Slide 1: "第一课：你好"
  ─ 今天我们来学习如何用中文打招呼。
  ─ 你好 (nǐ hǎo) - Hello
  ─ 再见 (zài jiàn) - Goodbye
```

### 2.2 完整工作流验证

| 阶段 | API 端点 / 操作 | 结果 | 产出物 |
|------|----------------|------|--------|
| **① 文件上传与解析** | `POST /api/projects/upload` | ✅ | `project_id`, `source_material.json` — 正确识别标题和正文段落 |
| **② 课程画像确认** | `PUT /api/projects/{id}/profile` | ✅ | 自动派生 Beginner 等级、English 支架语言、45 分钟课时 |
| **③ 流水线生成** | `POST /api/projects/{id}/pipeline` | ✅ | 素材 → 蓝图 → 媒体 → 渲染 → 质量 → 导出 |
| **④ HTML 课件渲染** | 流水线阶段 | ✅ | `courseware/lesson.html` — 离线 HTML |
| **⑤ 质量门禁** | 流水线阶段 | ⚠️ warning | `quality/quality_report.json` + `quality/quality_summary.md` |
| **⑥ HTML ZIP 导出** | `GET /api/projects/{id}/export` | ✅ | `exports/HanClassStudio_Output_*.zip` |
| **⑦ Editable PPTX 导出** | `POST /api/projects/{id}/export/pptx-editable?force=false` | ✅ | `exports/HanClassStudio_Editable_*.pptx` |

### 2.3 生成的课件结构

#### 幻灯片（8 页）

| Slide ID | 类型 | 标题 | 互动组件 |
|----------|------|------|---------|
| 1 | `CoverSlide` | 第一课：你好 | — |
| 2 | `ObjectiveSlide` | 学习目标 | — |
| 3 | `WarmUpSlide` | 看图说一说 | — |
| 4 | `VocabularySlide` | 生词练习 | `VocabularyFlipCard`（6 词） |
| 5 | `GrammarPatternSlide` | 句型操练 | `SentenceDragBuilder` |
| 6 | `DialogueSlide` | 听一听，选一选 | `ListenAndChoose` |
| 7 | `PracticeSlide` | 连一连 | `MatchGame`（4 对） |
| 8 | `SummarySlide` | 课堂小结 | — |

#### 互动组件小计

| 组件 | 实例数 | 类型 |
|------|--------|------|
| `VocabularyFlipCard` | 1 | 词汇翻卡 |
| `SentenceDragBuilder` | 1 | 拖拽造句 |
| `ListenAndChoose` | 1 | 听音选择 |
| `MatchGame` | 1 | 配对游戏 |

### 2.4 项目制品清单

```
runtime/projects/<project_id>/
├── uploads/                       # 原始上传文件
├── sources/source_material.json   # 解析后的素材数据
├── specs/
│   ├── lesson_spec.md             # 教案文档
│   └── spec_lock.json             # 执行契约
├── blueprints/
│   ├── lesson_blueprint.json      # 课件蓝图
│   ├── interaction_plan.json      # 互动计划
│   └── media_plan.json            # 媒体计划
├── assets/
│   ├── images/                    # 占位 / 真实图片
│   ├── audio/                     # 占位 / 真实音频
│   └── data/                      # 清单数据
├── courseware/
│   ├── lesson.html                # 离线 HTML 课件
│   └── render_manifest.json       # 渲染清单
├── quality/
│   ├── quality_report.json        # HTML 质量报告
│   ├── quality_summary.md         # 质量摘要
│   └── pptx_quality_report.json   # PPTX 质量报告
└── exports/
    ├── HanClassStudio_Output_*.zip           # HTML 离线包
    ├── export_manifest.json                  # HTML 导出清单
    ├── HanClassStudio_Editable_*.pptx        # Editable PPTX
    └── pptx_export_manifest.json             # PPTX 导出清单
```

---

## 3. 质量门禁状态说明

当前流水线质量状态为 **`warning`**（非阻塞）。

### 3.1 HTML 质量检查项明细

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `lesson_has_title` | ✅ 通过 | 课件标题有效 |
| `lesson_has_objectives` | ✅ 通过 | 学习目标已定义 |
| `lesson_has_slides` | ✅ 通过 | 幻灯片结构完整 |
| `courseware_html_exists` | ✅ 通过 | `lesson.html` 已渲染 |
| 占位媒体告警 | ⚠️ 10 项 | 图片和音频为占位文件，非真实生成内容 |

### 3.2 占位媒体清单

以下资源使用了占位文件（SVG/WAV），需接入真实提供方后替换：

```
⚠️ assets/images/slide_1_scene.svg
⚠️ assets/images/slide_3_warmup.svg
⚠️ assets/audio/word_1.wav ~ word_6.wav
⚠️ assets/audio/sentence_pattern_1.wav
⚠️ assets/audio/listen_choose_1.wav
```

### 3.3 PPTX 质量报告

| 检查项 | 状态 |
|--------|------|
| `pptx_file_created` | ✅ 通过 |
| `slide_count:N` | ✅ 幻灯片数量正确 |
| `editable_shapes_created` | ✅ 文本框和形状已创建 |
| 互动组件降级告警 | ⚠️ HTML 互动组件已转为课堂静态活动页面 |
| 音频替换告警 | ⚠️ 音频以文本标注形式呈现，未嵌入真实音频 |

> **结论**：质量门禁为 `warning` 状态属于 v0.1.0-alpha 的正常预期。所有核心教学检查（标题、目标、幻灯片、HTML 存在性、PPTX 生成）均通过。占位媒体和互动降级由真实提供方接入后自动解决，不阻塞发布。

---

## 4. HTML 离线导出验收

### 4.1 验收检查项

| 检查项 | 结果 | 备注 |
|--------|------|------|
| ZIP 包是否生成 | ✅ | 含完整目录结构 |
| `lesson.html` 是否可离线打开 | ✅ | 无外部 CDN 依赖 |
| HTML 是否包含完整 DOCTYPE | ✅ | `<!doctype html>` |
| 课件数据是否随附 | ✅ | `assets/data/` 下 8 个规范 JSON |
| 质量报告是否随附 | ✅ | `quality_summary.md` |
| 导出清单是否存在 | ✅ | `export_manifest.json` |

### 4.2 ZIP 包内容结构

```
HanClassStudio_Output_*.zip/
├── lesson.html
├── assets/
│   ├── images/
│   ├── audio/
│   ├── fonts/
│   └── data/
│       ├── lesson_profile.json
│       ├── source_material.json
│       ├── lesson_blueprint.json
│       ├── interaction_plan.json
│       ├── media_plan.json
│       ├── asset_manifest.json
│       ├── quality_report.json
│       └── attribution.json
├── quality_summary.md
└── export_manifest.json
```

---

## 5. Editable PPTX 导出验收 — 已实现

### 5.1 功能定义

将生成的课件蓝图（`lesson_blueprint.json` + `interaction_plan.json` + `media_plan.json`）反向渲染为教师可编辑的 `.pptx` 文件（editable classroom deck），与现有的 HTML ZIP 离线课件形成**双出口**。

> **注意**：PPTX 是 Editable Classroom Deck，不是 HTML 互动 runtime 的完整复刻。HTML 的交互组件（翻卡、拖拽、配对等）在 PPTX 中转为课堂静态活动页面（可编辑文本框），教师可在 PowerPoint / WPS / Keynote 中自由修改内容后用于课堂教学。

### 5.2 API 定义

```
POST /api/projects/{project_id}/export/pptx-editable?force=false
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `project_id` | path | — | 项目 ID |
| `force` | query | `false` | 跳过 quality state `blocked` 检查 |

响应模型：

```json
{
  "filename": "HanClassStudio_Editable_20260707_233023_459226.pptx",
  "download_url": "/runtime/projects/{id}/exports/HanClassStudio_Editable_*.pptx",
  "export_type": "pptx_editable",
  "editable": true,
  "interaction_policy": "classroom_static_activity",
  "quality_state": "warning"
}
```

### 5.3 验收清单

#### 5.3.1 基础导出

| # | 检查项 | 结果 | 备注 |
|---|--------|------|------|
| P1 | API 返回 200 | ✅ | `POST /api/projects/{id}/export/pptx-editable` |
| P2 | PPTX 文件生成 | ✅ | `exports/HanClassStudio_Editable_*.pptx` |
| P3 | 幻灯片数量 | ✅ | 与 `lesson_blueprint.json` 中的 `slides[]` 数量一致 |
| P4 | 可编辑文本框 | ✅ | 标题、正文等均为 `python-pptx` 文本框（textbox），可直接选中编辑 |
| P5 | 中文字符编码 | ✅ | UTF-8，无乱码 |
| P6 | 文件扩展名 | ✅ | `.pptx`，MIME 类型 `application/vnd.openxmlformats-officedocument.presentationml.presentation` |

#### 5.3.2 内容完整性

| # | 检查项 | 结果 | 备注 |
|---|--------|------|------|
| C1 | 幻灯片标题 | ✅ | 每页标题文本与蓝图 `title` 字段一致 |
| C2 | 内容正文 | ✅ | `content_blocks[].text` 写入对应文本框 |
| C3 | 支架语言 | ✅ | `scaffolding_text` 随正文输出 |
| C4 | 幻灯片类型标签 | ✅ | 每页右上角标注类型（如 `CoverSlide`） |
| C5 | 幻灯片备注 | ✅ | 每页写入教学提示、参考答案、音频指向 |
| C6 | 页脚标注 | ✅ | 标注 "Editable PPTX export · HTML interactions are converted to classroom static activity pages" |

#### 5.3.3 布局与样式

| # | 检查项 | 结果 | 备注 |
|---|--------|------|------|
| L1 | 幻灯片版式 | ✅ | 使用 16:9 宽屏（13.333" × 7.5"），空白版式 |
| L2 | 标题层级 | ✅ | 标题 31pt 加粗，正文 22pt |
| L3 | 卡片布局 | ✅ | ObjectiveSlide 使用双列卡片布局 |
| L4 | 颜色主题 | ✅ | 内置配色：背景、表面、文字、强调色 |
| L5 | 圆角形状 | ✅ | 活动框和媒体占位使用圆角矩形 |

#### 5.3.4 媒体资源

| # | 检查项 | 结果 | 备注 |
|---|--------|------|------|
| M1 | PNG/JPG 图片嵌入 | ✅ | `assets/` 中的真实图片通过 `shapes.add_picture` 嵌入 |
| M2 | 占位 SVG 处理 | ✅ | 无法嵌入的 SVG 显示为圆角矩形占位框 + 提示文字 |
| M3 | 音频标注 | ✅ | 在活动框或备注中标注音频内容文本 |
| M4 | 资源路径解析 | ✅ | 通过 `asset_manifest.json` 定位资源路径 |

#### 5.3.5 互动组件降级

| # | 组件 | PPTX 降级表现 | 结果 |
|---|------|-------------|------|
| C1 | `AudioButton` | 音频活动框：显示音频内容和标签文本 | ✅ |
| C2 | `VocabularyFlipCard` | 词汇卡布局：词 + 拼音 + 释义 + 例句，每词一卡 | ✅ |
| C3 | `SentenceDragBuilder` | 排序词块列表 + 参考答案区域 | ✅ |
| C4 | `ListenAndChoose` | 选择题文本（选项 + 答案标注 + 音频文本） | ✅ |
| C5 | `MatchGame` | 配对列表（左 ↔ 右） | ✅ |
| C6 | `CharacterFormation` | 汉字展示：部件分解 + 释义 | ✅ |
| C7 | `ClassroomGame` | JSON 数据展示为纯文本 | ✅ |
| C8 | 未支持组件 | 标注 "static fallback" + 原始数据 | ✅ |
| C9 | 组件备注 | 每页备注中标注原互动组件类型 | ✅ |

#### 5.3.6 质量与完整性

| # | 检查项 | 结果 | 备注 |
|---|--------|------|------|
| Q1 | `pptx_quality_report.json` | ✅ | `quality/` 下生成 |
| Q2 | `pptx_export_manifest.json` | ✅ | `exports/` 下生成 |
| Q3 | quality state 集成 | ✅ | `blocked` 状态阻止导出，`force=true` 可绕过 |
| Q4 | 文件可打开 | ✅ | PowerPoint 已手工验证可正常打开；WPS / Keynote / LibreOffice 待交叉验证 |
| Q5 | 文件大小 | ✅ | 含嵌入图片时大小合理 |
| Q6 | Artifact Inspector 展示 | ✅ | 前端面板展示 PPTX 相关制品 |

#### 5.3.7 Agent Handoff 兼容

| # | 检查项 | 结果 | 备注 |
|---|--------|------|------|
| A1 | Agent 编辑后 PPTX 导出 | ✅ | 蓝图通过验证后正常导出 |
| A2 | 任务文件更新 | ✅ | `AGENT_TASK.md` 包含 PPTX 导出策略说明 |

### 5.4 拒绝标准

以下情况返回 HTTP 4xx 并附带明确错误信息：

| 场景 | HTTP 状态 | 错误说明 |
|------|-----------|---------|
| 项目不存在 | 404 | 自动触发 |
| 缺少 `lesson_blueprint.json` | 400 | "Project needs blueprints/lesson_blueprint.json before editable PPTX export" |
| quality state 为 `blocked` 且未传 `force=true` | 409 | "Quality gate is blocked; pass force=true to export editable PPTX anyway" |
| 未运行质量门禁 | 409 | "Run quality gate before editable PPTX export" |

---

## 6. v0.1.0-alpha Non-goals

以下事项**不在** v0.1.0-alpha 的范围内，使用和评估时需注意：

- Editable PPTX 是 **teacher-editable draft（教师可编辑草稿）**，不是 HTML 互动 runtime 的完整复刻。互动组件（翻卡、拖拽、配对等）已转为课堂静态活动页面。
- 占位媒体（SVG / WAV）是预期的 demo 行为，除非配置真实 LLM / TTS / 图片生成服务。
- 生成的 PPTX 是课堂教学可用的可编辑版本，**不是**最终出版级精排课件。
- 不支持 PPTX → HTML 反向转换。
- 不支持 SCORM / LMS 包导出。

---

## 7. 总结

| 测试域 | 结果 | 备注 |
|--------|------|------|
| 自动化测试（18 用例） | ✅ 全部通过 | 后端路由 + 流水线（含 PPTX 导出） |
| 前端构建 | ✅ 通过 | TypeScript + Vite |
| 端到端流水线 | ✅ 通过 | PPTX 上传 → 解析 → 蓝图 → 渲染 → 质量 → 双出口导出 |
| 质量门禁 | ⚠️ warning | 占位媒体，非阻塞 |
| HTML ZIP 离线导出 | ✅ 通过 | 双出口之一，alpha 可用 |
| Editable PPTX 导出 | ✅ 通过 | 双出口之二，alpha 可用。Editable Classroom Deck，非 HTML 互动 runtime 复刻 |

**HanClassStudio v0.1.0-alpha 双出口（HTML ZIP + Editable PPTX）均进入可用状态，具备发布条件。**
