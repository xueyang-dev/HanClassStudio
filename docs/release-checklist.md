# Release Checklist — HanClassStudio v0.1.0-alpha

> 在发布前逐项检查。通过项标记为 ✅，未通过或不适用的标记为 ❌ / N/A。

---

## 1. 代码与构建

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 1.1 | `npm test` 全部通过（18 用例） | ☐ | 后端 pytest (18) + 前端 tsc + Vite build |
| 1.2 | 前端生产构建无错误 | ☐ | `npm run build:web` |
| 1.3 | GitHub Actions CI 通过 | ☐ | 推送后检查 Actions 页面 |
| 1.4 | `git diff --check` 无空白错误 | ☐ | 提交前运行 |
| 1.5 | `git status` 干净，无未跟踪的敏感文件 | ☐ | 确认无 `runtime/` 开发数据 |
| 1.6 | `.gitignore` 覆盖 `runtime/`、`.venv/`、`node_modules/`、`dist/` | ☐ | 已在 `.gitignore` 中 |

---

## 2. 后端服务

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 2.1 | `npm run dev:api` 正常启动 | ☐ | 监听 `127.0.0.1:8000` |
| 2.2 | `GET /api/health` 返回 `{"status":"ok"}` | ☐ | 健康检查 |
| 2.3 | `GET /api/component-registry` 返回组件列表 | ☐ | 含 ClassroomGame(experimental) |
| 2.4 | 上传 PPTX 返回有效 `project_id` | ☐ | `POST /api/projects/upload` |
| 2.5 | 流水线生成完成，状态为 `rendered` 或 `quality_done` | ☐ | `POST /api/projects/{id}/pipeline` |
| 2.6 | HTML ZIP 导出接口正常 | ☐ | `GET /api/projects/{id}/export` |
| 2.7 | Editable PPTX 导出接口正常 | ☐ | `POST /api/projects/{id}/export/pptx-editable?force=false` |

---

## 3. 前端工作台

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 3.1 | `npm run dev:web` 正常启动 | ☐ | 监听 `127.0.0.1:5173` |
| 3.2 | 五步工作流导航栏可见 | ☐ | 上传解析 → 课程确认 → 模式语言 → 大纲编辑 → 预览导出 |
| 3.3 | 文件上传功能正常 | ☐ | PPTX/PDF 均可 |
| 3.4 | 课程画像确认后可保存 | ☐ | |
| 3.5 | "一键生成课件" 按钮可用 | ☐ | |
| 3.6 | 生成后显示 route badge、pipeline 阶段、quality 面板 | ☐ | |
| 3.7 | Artifact Inspector 可展开查看各阶段制品 | ☐ | 含 `exports/*.pptx`、`exports/pptx_export_manifest.json`、`quality/pptx_quality_report.json` |
| 3.8 | 课件预览可正常加载和导航 | ☐ | 上一页/下一页/键盘/全屏 |

---

## 4. 质量门禁

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 4.1 | Quality state 正确展示（pass / warning / blocked） | ☐ | |
| 4.2 | `blocked` 状态阻止正常导出 | ☐ | HTML ZIP 和 PPTX 均受约束 |
| 4.3 | 强制导出路径在 demo 中正常工作 | ☐ | `force=true` |
| 4.4 | 占位媒体告警正确显示为 `warning` | ☐ | 非阻塞 |
| 4.5 | PPTX 质量报告在 Artifact Inspector 中可见 | ☐ | `quality/pptx_quality_report.json` |
| 4.6 | `classroom_quality_report.json` 在流水线中生成 | ☐ | 检查 `quality/` 目录 |
| 4.7 | Classroom quality 捕获 "Meaning scaffold" → blocked | ☐ | 内容泄露检查 |
| 4.8 | Classroom quality 捕获伪支架文本 → blocked | ☐ | 如 "Arabic: 中文文本" |
| 4.9 | Classroom quality 捕获数字声调（ni3 hao3）→ warning | ☐ | 拼音格式检查 |
| 4.10 | Classroom quality 捕获 grammar/练习不匹配 → warning/blocked | ☐ | 语法点与练习一致 |

---

## 5. 导出验收 — 双出口

### 5.1 HTML 离线 ZIP 出口

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 5.1.1 | ZIP 包生成成功 | ☐ | `exports/*.zip` |
| 5.1.2 | `lesson.html` 在 ZIP 中，可离线打开 | ☐ | 无外部 CDN 依赖 |
| 5.1.3 | `assets/` 目录包含图片、音频、数据 | ☐ | |
| 5.1.4 | `assets/data/` 包含 8 个规范 JSON | ☐ | |
| 5.1.5 | `quality_summary.md` 随附 | ☐ | |
| 5.1.6 | `export_manifest.json` 存在 | ☐ | |
| 5.1.7 | ZIP 文件名包含项目标识和时间戳 | ☐ | `HanClassStudio_Output_<timestamp>.zip` |
| 5.1.8 | UI 上的"下载"按钮可触发下载 | ☐ | |

### 5.2 Editable PPTX 出口（v0.1.0-alpha 已实现）

> Editable Classroom Deck：HTML 的互动组件在此转为可编辑的课堂静态活动页面。教师可在 PowerPoint / WPS / Keynote 中自由修改后用于课堂教学。

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 5.2.1 | PPTX 文件生成成功 | ☐ | `exports/HanClassStudio_Editable_*.pptx` |
| 5.2.2 | API 返回正确响应模型 | ☐ | `POST /api/projects/{id}/export/pptx-editable` |
| 5.2.3 | 幻灯片数与蓝图一致 | ☐ | |
| 5.2.4 | 文本框为可编辑状态 | ☐ | 标题、正文均可直接选中编辑 |
| 5.2.5 | 中文字符无乱码 | ☐ | UTF-8 编码 |
| 5.2.6 | 互动组件已降级为静态活动页面 | ☐ | 翻卡 → 词卡列表，拖拽 → 排序词块，选择 → 选择题文本，配对 → 配对列表 |
| 5.2.7 | 每页有幻灯片类型标签 | ☐ | 右上角标注 |
| 5.2.8 | 每页有教师备注 | ☐ | 教学提示、参考答案、音频指向 |
| 5.2.9 | PNG/JPG 图片已嵌入 | ☐ | 占位 SVG 显示为提示框 |
| 5.2.10 | 可在 PowerPoint 中打开 | ☐ | 无修复提示 |
| 5.2.11 | 可在 WPS 中打开 | ☐ | |
| 5.2.12 | 可在 Keynote 中打开 | ☐ | |
| 5.2.13 | `pptx_export_manifest.json` 生成 | ☐ | `exports/` 下 |
| 5.2.14 | `pptx_quality_report.json` 生成 | ☐ | `quality/` 下 |
| 5.2.15 | blocked 状态阻止 PPTX 导出 | ☐ | 返回 HTTP 409 |
| 5.2.16 | `force=true` 绕过 blocked 检查 | ☐ | |
| 5.2.17 | Artifact Inspector 展示 PPTX 相关制品 | ☐ | 文件、清单、质量报告 |

---

## 6. Agent Handoff

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 6.1 | Agent 任务文件和规则文件可生成 | ☐ | `agent/AGENT_TASK.md` + `AGENT_RULES.md` |
| 6.2 | 外部 Agent 编辑后验证接口可用 | ☐ | `POST /api/projects/{id}/agent/validate` |
| 6.3 | 验证通过后可重新渲染和导出（含 PPTX） | ☐ | |
| 6.4 | 验证失败时返回明确的阻塞信息 | ☐ | |

---

## 7. 文档与发布

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 7.1 | README.md 已更新（中文，含双出口说明） | ✅ | 已完成 |
| 7.2 | LICENSE 文件存在（MIT） | ✅ | 已完成 |
| 7.3 | AGENTS.md 和 CLAUDE.md 存在 | ✅ | |
| 7.4 | docs/ 文档完整 | ☐ | 含 demo 指南、架构概述、脚本、截图记录、测试报告 |
| 7.5 | 测试报告已生成 | ☐ | `docs/test-report-v0.1.md` |
| 7.6 | GitHub Actions CI 配置就绪 | ☐ | `.github/workflows/` |
| 7.7 | CONTRIBUTING.md 和 SECURITY.md 就绪 | ☐ | |
| 7.8 | GitHub Release 描述已撰写 | ☐ | 基于 `docs/release-notes-v0.1.md` |
| 7.9 | Git tag 已创建 | ☐ | `v0.1.0-alpha` |

---

## 8. 发布前最终检查

| # | 检查项 | 状态 |
|---|--------|------|
| 8.1 | 所有自动化测试通过（18 用例） | ☐ |
| 8.2 | 端到端流水线手工验证完成（含 PPTX 导出） | ☐ |
| 8.3 | `git diff --check` 无空白错误 | ☐ |
| 8.4 | 无敏感信息泄露（API key、本地路径、个人数据） | ☐ |
| 8.5 | 代码仅含预期变更 | ☐ |
| 8.6 | GitHub Release 页面已附带 release notes、测试报告链接和已知限制 | ☐ |

---

## 使用说明

1. 按顺序逐块检查，每项确认后标记为 ✅。
2. 5.1（HTML ZIP）和 5.2（Editable PPTX）均为当前 release 必查项。
3. 发布前至少完成一轮端到端测试（含两个出口）并在测试报告中记录结果。
4. 创建 Git tag `v0.1.0-alpha` 并发布 GitHub Release 后，在仓库的 Releases 页面撰写发布说明。
