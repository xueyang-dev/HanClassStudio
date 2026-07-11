# Diagnostics（开发者诊断页）

本目录是 **SVG 教学插画** 功能的开发者诊断与 benchmark 工具，**不属于课件
运行时产物**，仅供人工目检与回归核对。

> 运行方式（需先建好 `apps/api/.venv`）：从仓库根目录执行，使用 venv 的 python。
> ```bash
> apps/api/.venv/bin/python diagnostics/build_sleep_comparison.py
> apps/api/.venv/bin/python diagnostics/build_sleep_html.py
> apps/api/.venv/bin/python diagnostics/build_svg_gallery.py
> ```

## 目录结构

### `sleep_comparison/`
「睡觉」场景的 **current vs revised** 前后对比画廊（本轮为 v3 → v4）。

- `before/` `after/`：各画幅（16:9 / 1:1 / thumb）的 SVG 源文件。
- `before_reports.json` `after_reports.json`：离线安全门 + 教学适用门的判定结果。
- `index.html`：并排对比页（含各版主体占画布比例、48px / 96px 缩略图真实预览）。

> 复现逻辑：`build_sleep_comparison.py` 会先把磁盘上已有的 `after/` 拷贝为
> `before/`（即「上一轮」），再从当前代码重新渲染 `after/`（即「本轮」），
> 因此每次运行都会把对比基准前移一轮。

### `svg_gallery/`
8 个示例概念的主画廊（`svgs/` 下为各概念的 `.svg` + `.scene.json`），用于
快速巡检 SVG 轨在不同词汇上的确定性输出。

## 说明

- 这些页面是**人工视觉复核**工具，不进入质量门自动化；
- 自动质量门见 `apps/api/src/hcs_api/quality.py`（`_check_svg_illustrations`），
  产物为 `quality/svg_illustration_report.json`；
- 媒体双轨策略与栅格 Provider 交接见 `docs/svg_media_strategy.md`。
