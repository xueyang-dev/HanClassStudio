# 前后端契约修复矩阵

| 问题 | 状态 | 当前切片 | 验证 |
| --- | --- | --- | --- |
| Provider capability contract | 已测试 | 后端目录、统一 Provider ID、WebUI 动态目录、设置 merge、不可用能力状态、空密钥保护 | 26 route tests + frontend production build |
| Unified ProjectState / gate summary | 已测试 | ProjectState 阶段、profile 状态、四层门控摘要、结构化导出阻塞、开发端口 CORS | 24 route tests + frontend production build |
| Pipeline stage truthfulness | 已测试 | 前端按后端阶段渲染管线指示；提前停止不再伪造全完成 | full backend baseline + browser DOM/screenshot check |
| Project reopen / persistent profile state | 已测试 | 最近项目列表、按 ID 恢复、URL project_id/stage、profile inferred/confirmed/stale | route listing/profile regression + browser recent-project check |
| Dependency invalidation | 已测试 | revision、stale_state、上游到下游最小失效矩阵、过期预览/导出隐藏 | invalidation matrix + profile/media route regression |
| State-first teacher summary | 已测试 | 受控教师摘要接口与 WebUI 目标/证据/活动统计 | summary route regression + frontend build |
| Media review / force regeneration | 已测试 | 候选接受/拒绝、教师替换、审阅历史、force_regenerate 参数 | media API regression + existing media review tests |
| Health / settings semantics / formats / CORS / i18n | 已测试 | 健康状态、自动保存单一语义、上传格式、六阶段多语言、Vite 回退端口、Provider 不可用显示 | health/CORS/provider route + browser DOM/screenshot + frontend build |
| Frontend and end-to-end contract tests | 已测试 | Provider、ProjectState/gate、media、invalidation、pipeline/export 状态映射 | 26 route tests + 418 collected (417 passed, 1 skipped) + frontend state runner + production build |
