# HanClassStudio v0.1 测试报告

> 测试日期：2026-07-07
> 测试环境：macOS 26.5.2 · Python 3.11.15 · Node.js 22.23.0 · uv 0.11.26
> 测试范围：自动化测试套件 + 端到端流水线手工验证

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
rootdir: /private/tmp/HanClassStudio/apps/api
collected 16 items

apps/api/tests/test_api_routes.py .........                  [56%]
apps/api/tests/test_pipeline.py .......                      [100%]

====================== 16 passed, 1 warning in 11.07s ======================
```

| 测试文件 | 用例数 | 状态 |
|----------|--------|------|
| `test_api_routes.py` | 9 | ✅ 全部通过 |
| `test_pipeline.py` | 7 | ✅ 全部通过 |
| **合计** | **16** | **✅ 全部通过** |

### 1.3 前端构建结果

```
vite v8.1.3 building client environment for production...
✓ 1566 modules transformed.
dist/index.html                   0.40 kB │ gzip:  0.27 kB
dist/assets/index-CKid1fR2.css   14.16 kB │ gzip:  3.31 kB
dist/assets/index-BTWNkMSg.js   175.35 kB │ gzip: 55.99 kB
✓ built in 579ms
```

- TypeScript 类型检查：✅ 通过
- Vite 生产构建：✅ 通过（575ms，175KB JS + 14KB CSS）

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
| **① 文件上传与解析** | `POST /api/projects/upload` | ✅ | `project_id: bc800661a794`, `source_material.json` — 正确识别标题和正文段落 |
| **② 课程画像确认** | `PUT /api/projects/{id}/profile` | ✅ | 自动派生 Beginner 等级、English 支架语言、45 分钟课时、New lesson 模式 |
| **③ 流水线生成** | `POST /api/projects/{id}/pipeline` | ✅ | 成功触发完整流水线：素材 → 蓝图 → 媒体 → 渲染 → 质量 → 导出 |
| **④ 课件渲染** | 流水线阶段 | ✅ | `courseware/lesson.html` — 离线 HTML，含完整 `<!doctype html>` 声明 |
| **⑤ 质量门禁** | 流水线阶段 | ⚠️ warning | `quality/quality_report.json` + `quality/quality_summary.md` |
| **⑥ ZIP 导出** | 流水线阶段 | ✅ | `exports/HanClassStudio_Output_*.zip`（30KB） |

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

### 2.4 项目制品清单（17 文件）

```
runtime/projects/bc800661a794/
├── uploads/test_lesson.pptx         # 原始上传
├── sources/source_material.json     # 解析后的素材数据
├── specs/
│   ├── lesson_spec.md               # 教案文档
│   └── spec_lock.json               # 执行契约
├── blueprints/
│   ├── lesson_blueprint.json        # 课件蓝图
│   ├── interaction_plan.json        # 互动计划
│   └── media_plan.json              # 媒体计划
├── assets/
│   ├── images/slide_1_scene.svg     # 占位图片
│   ├── images/slide_3_warmup.svg    # 占位图片
│   ├── audio/word_*.wav             # 占位音频（6 词）
│   ├── audio/sentence_pattern_1.wav # 占位音频
│   ├── audio/listen_choose_1.wav    # 占位音频
│   └── data/                        # 清单数据
├── courseware/
│   ├── lesson.html                  # 离线 HTML 课件
│   └── render_manifest.json         # 渲染清单
├── quality/
│   ├── quality_report.json          # 质量报告
│   └── quality_summary.md           # 质量摘要
└── exports/
    ├── HanClassStudio_Output_*.zip  # 导出的离线包
    └── export_manifest.json         # 导出清单
```

---

## 3. 质量门禁状态说明

当前流水线质量状态为 **`warning`**（非阻塞）。

### 3.1 检查项明细

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

> **结论**：质量门禁为 `warning` 状态属于 v0.1 demo 的正常预期。所有核心教学检查（标题、目标、幻灯片、HTML 存在性）均通过。占位媒体由真实 LLM / TTS / 图片生成服务接入后自动解决，不阻塞流水线测试。

---

## 4. HTML 离线导出验收

### 4.1 验收检查项

| 检查项 | 结果 | 备注 |
|--------|------|------|
| ZIP 包是否生成 | ✅ | 30KB，含完整目录结构 |
| `lesson.html` 是否可离线打开 | ✅ | 无外部 CDN 依赖 |
| HTML 是否包含完整 DOCTYPE | ✅ | `<!doctype html>` |
| 课件数据是否随附 | ✅ | `assets/data/` 下 4 个 JSON |
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

## 5. Editable PPTX 导出验收

> **说明**：Editable PPTX 导出是 HanClassStudio 的规划中功能，当前 v0.1 尚不实现。本节定义验收标准，供后续版本开发和回归测试使用。

### 5.1 功能定义

将生成的课件蓝图（`lesson_blueprint.json` + `interaction_plan.json` + `media_plan.json`）反向渲染为教师可编辑的 `.pptx` 文件，与现有的 HTML 离线课件形成**双出口**。

### 5.2 验收清单

#### 5.2.1 基础导出

| # | 检查项 | 验收标准 | 优先级 |
|---|--------|---------|--------|
| P1 | PPTX 文件生成 | 调用导出接口后生成有效的 `.pptx` 文件，可用 PowerPoint / WPS / LibreOffice 打开 | P0 |
| P2 | 幻灯片数量 | PPTX 幻灯片数与 `lesson_blueprint.json` 中的 `slides[]` 数量一致 | P0 |
| P3 | 幻灯片标题 | 每页幻灯片的标题文本与蓝图中的 `title` 字段一致 | P0 |
| P4 | 内容文本框 | 蓝图中的 `content_blocks[].text` 正确写入对应幻灯片的文本框 | P0 |
| P5 | 中文文本编码 | 中文字符显示正常，无乱码（UTF-8 / Unicode） | P0 |
| P6 | 文件扩展名 | 导出文件扩展名为 `.pptx`，MIME 类型为 `application/vnd.openxmlformats-officedocument.presentationml.presentation` | P0 |

#### 5.2.2 布局与样式

| # | 检查项 | 验收标准 | 优先级 |
|---|--------|---------|--------|
| L1 | 幻灯片版式 | 每页使用空白版式或根据蓝图 `layout_variant` 选择合适的占位符布局 | P1 |
| L2 | 标题层级 | `title` 使用大号加粗字体（如 28pt），`body` 使用常规字体（如 18pt） | P1 |
| L3 | 支架语言显示 | 如果 `scaffolding_text` 非空，可置于副标题位置或底部备注 | P2 |
| L4 | 字体支持 | 嵌入 Noto Sans SC 或使用通用中文字体回退（如微软雅黑、PingFang） | P1 |

#### 5.2.3 媒体资源

| # | 检查项 | 验收标准 | 优先级 |
|---|--------|---------|--------|
| M1 | 图片嵌入 | 蓝图 `media_requirements.image_key` 对应的图片文件嵌入到对应幻灯片 | P0 |
| M2 | 占位图片处理 | 占位 SVG 可正常显示或转换为 PNG 后嵌入 | P1 |
| M3 | 音频占位 | 在幻灯片备注中标注音频指向（如 `[音频: word_1]`），不实际嵌入 | P2 |
| M4 | 资源路径解析 | 资源文件路径正确解析到 `assets/` 目录，不产生断链 | P0 |

#### 5.2.4 互动组件降级

| # | 检查项 | 验收标准 | 优先级 |
|---|--------|---------|--------|
| C1 | `VocabularyFlipCard` | 降级为词汇列表（词 + 拼音 + 释义），可编辑 | P1 |
| C2 | `SentenceDragBuilder` | 降级为组句练习题文本（"请将下列词语组成句子" + 词语列表 + 参考答案），可编辑 | P1 |
| C3 | `ListenAndChoose` | 降级为选择题（题目 + 选项 + 答案标注），音频路径写在备注中 | P1 |
| C4 | `MatchGame` | 降级为配对列表（左列 ↔ 右列），可编辑 | P1 |
| C5 | `CharacterFormation` | 降级为汉字展示（大号字 + 部件分解 + 说明），可编辑 | P2 |
| C6 | 组件回退标注 | 每页备注中标注原始组件类型（如 `[原互动组件: VocabularyFlipCard]`） | P2 |

#### 5.2.5 质量与完整性

| # | 检查项 | 验收标准 | 优先级 |
|---|--------|---------|--------|
| Q1 | 幻灯片备注 | 每页幻灯片写入教师备注（教学提示、参考答案、音频指向） | P1 |
| Q2 | 文件完整性 | 导出的 PPTX 可被 PowerPoint 打开且无修复提示 | P0 |
| Q3 | 文件大小 | 含嵌入图片的 PPTX 大小合理（单页 < 5MB，参考 v0.1 素材规模） | P2 |
| Q4 | 质量门禁集成 | PPTX 导出同样受现有 quality state 约束（`blocked` 状态阻止导出） | P1 |
| Q5 | 导出清单 | `export_manifest.json` 记录 PPTX 导出路径、时间戳、export_type = "pptx" | P1 |

#### 5.2.6 Agent Handoff 兼容

| # | 检查项 | 验收标准 | 优先级 |
|---|--------|---------|--------|
| A1 | Agent 编辑后的 PPTX 导出 | 外部 Agent 编辑蓝图后，`lesson_blueprint.json` 通过验证，PPTX 导出正常 | P1 |
| A2 | Agent 任务文件 | `agent/AGENT_TASK.md` 增加 PPTX 导出策略的说明 | P2 |

### 5.3 拒绝标准

以下情况应拒绝 PPTX 导出并返回明确错误信息：

- 项目状态不是 `rendered` 或 `quality_done`
- quality state 为 `blocked`（非强制导出路径）
- `lesson_blueprint.json` 缺少必需的 `slides[]` 字段
- 指定引用的媒体文件在 `assets/` 中不存在
- `python-pptx` 依赖未安装

---

## 6. 总结

| 测试域 | 结果 | 备注 |
|--------|------|------|
| 自动化测试（16 用例） | ✅ 全部通过 | 后端路由 + 流水线 |
| 前端构建 | ✅ 通过 | TypeScript + Vite |
| 端到端流水线 | ✅ 通过 | PPTX 上传 → 解析 → 蓝图 → 渲染 → 质量 → 导出 |
| 质量门禁 | ⚠️ warning | 占位媒体，非阻塞 |
| HTML 离线导出 | ✅ 通过 | ZIP 包结构完整 |
| Editable PPTX 导出 | 📋 验收标准已定义 | 待后续版本实现 |

**HanClassStudio v0.1 流水线完整可用，具备演示和评估条件。**
