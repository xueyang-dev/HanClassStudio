# 前后端契约修复矩阵

| 问题 | 状态 | 当前切片 | 验证 |
| --- | --- | --- | --- |
| Provider capability contract | 已测试 | 后端目录、统一 Provider ID、设置 merge、不可用能力状态、空密钥保护、安全响应、项目静态目录隔离、deterministic offline Provider 与执行失败 blocker | 429 backend tests + provider-focused tests + frontend state/build |
| Unified ProjectState / gate summary | 已测试 | ProjectState 阶段、profile 状态、四层门控摘要、not_run 语义、结构化导出阻塞和不可绕过技术门控 | gate/export regression + 429 backend tests |
| Pipeline stage truthfulness | 已测试 | 前端按后端阶段渲染管线指示；提前停止不再伪造全完成；render 与 quality 分开映射 | stage regression + frontend state runner/build |
| Project reopen / persistent profile state | 已测试 | 最近项目列表、按 ID 恢复、URL project_id/stage、profile inferred/confirmed/stale、旧项目安全读取 | route listing/profile/legacy regression |
| Dependency invalidation | 已测试 | expected_revision、stale_state、上游到下游最小失效矩阵、过期预览/导出隐藏 | invalidation/revision/profile/media regression |
| State-first teacher summary | 已测试 | 受控教师摘要接口与 WebUI 目标/证据/活动统计 | summary route regression + frontend build |
| Media review / force regeneration | 已测试 | 候选接受/拒绝、教师替换、审阅历史、force_regenerate 参数 | media API regression + existing media review tests |
| Health / settings semantics / formats / CORS / i18n | 已测试 | 健康状态、自动保存单一语义、上传格式、六阶段多语言、Vite 回退端口、Provider 不可用显示 | health/CORS/provider route + 5174 browser DOM smoke + frontend build |
| Frontend and end-to-end contract tests | 已测试 | Provider、ProjectState/gate、media、invalidation、revision、pipeline/export 状态映射；浏览器上传、URL 恢复和未运行质量门控 | 429 collected (429 passed, 1 skipped) + frontend state runner + production build + Playwright browser contract test |
