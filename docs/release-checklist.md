# Release Checklist — HanClassStudio v0.1

> 在发布前逐项检查。通过项标记为 ✅，未通过或不适用的标记为 ❌ / N/A。

---

## 1. 代码与构建

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 1.1 | `npm test` 全部通过（16 用例） | ☐ | 后端 pytest (16) + 前端 tsc + Vite build |
| 1.2 | 前端生产构建无错误 | ☐ | `npm run build:web` |
| 1.3 | `git diff --check` 无空白错误 | ☐ | 提交前运行 |
| 1.4 | `git status` 干净，无未跟踪的敏感文件 | ☐ | 确认无 `runtime/` 开发数据 |
| 1.5 | `.gitignore` 覆盖 `runtime/`、`.venv/`、`node_modules/`、`dist/` | ☐ | 已在 `.gitignore` 中 |

---

## 2. 后端服务

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 2.1 | `npm run dev:api` 正常启动 | ☐ | 监听 `127.0.0.1:8000` |
| 2.2 | `GET /api/health` 返回 `{"status":"ok"}` | ☐ | 健康检查 |
| 2.3 | `GET /api/component-registry` 返回 7 个组件 | ☐ | 含 ClassroomGame(experimental) |
| 2.4 | 上传 PPTX 返回有效 `project_id` | ☐ | `POST /api/projects/upload` |
| 2.5 | 流水线生成完成，状态为 `rendered` 或 `quality_done` | ☐ | `POST /api/projects/{id}/pipeline` |

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
| 3.7 | Artifact Inspector 可展开查看各阶段制品 | ☐ | |
| 3.8 | 课件预览可正常加载和导航 | ☐ | 上一页/下一页/键盘/全屏 |

---

## 4. 质量门禁

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 4.1 | Quality state 正确展示（pass / warning / blocked） | ☐ | |
| 4.2 | `blocked` 状态阻止正常导出 | ☐ | |
| 4.3 | 强制导出路径在 demo 中正常工作 | ☐ | |
| 4.4 | 占位媒体告警正确显示为 `warning` | ☐ | 非阻塞 |

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

### 5.2 Editable PPTX 出口（规划中）

> 以下为 v0.2 目标，当前版本不要求通过，但应在设计层面保持兼容。

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 5.2.1 | 蓝图数据包含 PPTX 渲染所需的全部字段 | ☐ | `slides[].title`, `content_blocks`, `layout_variant` |
| 5.2.2 | `spec_lock.json` 中的 export 策略可扩展 | ☐ | 预留 `export_type` 字段 |
| 5.2.3 | 资源路径可被 PPTX 渲染器正确引用 | ☐ | 相对路径，非绝对路径 |
| 5.2.4 | 互动组件降级策略已在蓝图中标注 | ☐ | 每组件标注 `fallback_text` 字段 |
| 5.2.5 | `media_plan.json` 包含 PPTX 所需的嵌入/引用标记 | ☐ | 如 `embed: true/false` |

---

## 6. Agent Handoff

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 6.1 | Agent 任务文件和规则文件可生成 | ☐ | `agent/AGENT_TASK.md` + `AGENT_RULES.md` |
| 6.2 | 外部 Agent 编辑后验证接口可用 | ☐ | `POST /api/projects/{id}/agent/validate` |
| 6.3 | 验证通过后可重新渲染和导出 | ☐ | |
| 6.4 | 验证失败时返回明确的阻塞信息 | ☐ | |

---

## 7. 文档与发布

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 7.1 | README.md 已更新（中文） | ✅ | 已完成 |
| 7.2 | LICENSE 文件存在（MIT） | ✅ | 已完成 |
| 7.3 | AGENTS.md 和 CLAUDE.md 存在 | ✅ | |
| 7.4 | docs/ 文档完整 | ☐ | 含 demo 指南、架构概述、脚本、截图记录、测试报告 |
| 7.5 | 测试报告已生成 | ☐ | `docs/test-report-v0.1.md` |
| 7.6 | GitHub Release 描述已撰写 | ☐ | 基于 `docs/release-notes-v0.1.md` |
| 7.7 | Git tag 已创建 | ☐ | `v0.1.0` |

---

## 8. 发布前最终检查

| # | 检查项 | 状态 |
|---|--------|------|
| 8.1 | 所有自动化测试通过 | ☐ |
| 8.2 | 端到端流水线手工验证完成 | ☐ |
| 8.3 | `git diff --check` 无空白错误 | ☐ |
| 8.4 | 无敏感信息泄露（API key、本地路径、个人数据） | ☐ |
| 8.5 | 代码仅含预期变更 | ☐ |

---

## 使用说明

1. 按顺序逐块检查，每项确认后标记为 ✅。
2. 5.2 节（Editable PPTX）为规划中目标，当前版本标注 ❌，不影响发布。
3. 发布前至少完成一轮端到端测试并在测试报告中记录结果。
4. 创建 Git tag 并发布 GitHub Release 后，在仓库的 Releases 页面撰写发布说明。
