# SVG 与栅格双轨媒体策略（最终定位 + 栅格 Provider 交接）

> 适用范围：HanClassStudio 媒体子系统。本文固定 SVG 的产品职责，并给后续
> 实现「低成本栅格图像 Provider」的开发者（如 ChatGPT Codex）留下清晰接口
> 与交接说明。
>
> 生效时间：本仓库合入 `feat/svg-offline-illustration-lane` 起。
> 改动性质：**收口 / 定位 / 文档**，不扩展 SVG 生成能力，不新增 benchmark。

---

## 1. 产品背景

HanClassStudio 帮助教师快速制作高质量教学课件，覆盖课堂展示、课堂练习、
教师引导、学生自学。媒体策略的第一优先级是**教学效果、制作效率、教师可用
性**，而不是技术纯度（不追求「所有插画都必须是 SVG」）。

因此媒体采用**双轨（dual-lane）** 策略：

```
Raster illustration provider  （栅格轨）
  → 人物动作、情境插画、课堂主图
  → 由外部/低成本图像模型生成 PNG

Deterministic SVG lane        （确定性 SVG 轨）
  → 图标、结构图、简单语义图、离线 fallback
  → 由锁定契约 + 注册组件库确定性渲染，无网络依赖
```

两条轨通过 `MediaRequirements.media_kind` 区分，互不替代。

---

## 2. SVG 的最终产品职责（固定）

从本文生效起，SVG 的职责被**固定**为如下内容。

### 2.1 适合用 SVG 承担的内容

- 教学图标（icon）
- 简单物体图（object diagram）
- 结构图、关系图、流程图
- 简单词汇语义图（vocab semantic map）
- 离线模式（offline mode）
- 无网络或 Provider 不可用时的 **deterministic fallback**
- 小尺寸 UI / 词汇卡辅助图
- 开发诊断与 benchmark

### 2.2 不再要求 SVG 承担的内容

- 高质量人物场景主插画
- 复杂人体姿态
- 多人物交互场景
- 餐厅、家庭、教室等完整情境插画
- 商业级封面插画
- 通用 AI 绘画能力

> 结论：人物场景主图、情境插画、课堂主图应走**栅格轨**；SVG 只负责
> 图标 / 结构图 / 简单语义图 / 离线兜底。两者职责边界清晰，不要试图用
> SVG 去「画」它不擅长的复杂人物场景。

---

## 3. 当前实现接线（as of this release）

### 3.1 判别字段

`models.MediaRequirements` 新增判别字段：

```python
class MediaRequirements(BaseModel):
    image_prompt: str | None = None
    image_key: str | None = None
    media_kind: Literal["raster", "svg_illustration"] = "raster"  # 判别字段
    svg_style: str | None = None
    illustration_level: Literal["icon", "scene"] | None = None
    text_policy: Literal["no_text", "semantic_symbols_only", "short_environment_label"] | None = None
    scene_type: str | None = None
```

- `media_kind == "raster"`：走栅格轨（`generate_raster_image`）。
- `media_kind == "svg_illustration"`：走确定性 SVG 轨（LLM 规划 SceneSpec →
  锁定契约渲染 → 质量门）。

### 3.2 SVG 轨数据流

```
agents.py / strategist.py
   → MediaRequirements(media_kind="svg_illustration", scene_type=..., ...)
media.generate_configured_media
   → 仅对 media_kind=="svg_illustration" 的 key 调用 _upgrade_svg_illustrations
      → providers.generate_scene_spec(llm, brief)   # LLM 只输出 IllustrationSceneSpec JSON
      → svg_illustration.generate_svg_illustration(contract, llm)
         → validate_scene_spec → render_scene_spec → 质量门
   → 对 media_kind!="svg_illustration" 的 key 调用 generate_raster_image
quality.check_quality
   → _check_svg_illustrations：离线安全 + 教学适用性双门
      → 写出 quality/svg_illustration_report.json
pptx_exporter
   → _rasterize_svg：python-pptx 不能直接嵌 SVG，cairosvg 可用时栅格化为 PNG，
     否则回退占位框
```

关键点：**LLM 永远不写 SVG**。LLM 只输出结构化 `IllustrationSceneSpec`
（概念、层级、场景类型、主体/客体、相对比例、位置分区、文本策略、style_token），
由确定性渲染器从注册组件库组装。这样保证离线安全、可控、可评审。

### 3.3 质量门（两条，职责分离）

- **离线安全门** `check_svg_offline_safe`：SVG 是否良构、可安全加载、无外链/
  脚本/外部资源。
- **教学适用门** `check_illustration_quality`：是否好图（主体占比、视觉中心、
  接触关系、文本策略、跨画幅一致性等）。例如 `睡觉` 场景要求使用单一复合组件
  `SleepingInBed`（床+枕+人+被 的正确接触），不接受「Bed+Pillow+Blanket+
  PersonLying 浮空」模式。

两条门失败均为 warning（人工视觉复核），不阻断构建——因为「测试通过 /
  能打开」不等于「教学可用」，最终可用性由教师目检决定。

### 3.4 Fallback 与离线

- `svg_offline_safe=True`（spec_lock 默认）时，SVG 轨完全确定性、无网络依赖。
- 栅格轨在 Provider 不可用 / 返回 None / 抛 `ProviderError` 时，回退到占位图
  （placeholder），不阻断课件产出。

---

## 4. 栅格 Provider 接口（给后续实现者的交接）

> 目标：实现一个**低成本**栅格图像 Provider，用于人物动作 / 情境插画 / 课堂
> 主图。实现者：**ChatGPT Codex**（或同等能力 Agent）。

### 4.1 唯一集成点（seam）

```python
# apps/api/src/hcs_api/media.py
def generate_raster_image(
    settings: ProviderSettings,
    prompt: str,
    aspect_ratio: str = "16:9",
) -> bytes | None:
    """Raster illustration provider seam.

    返回 PNG bytes；失败返回 None（上层回退占位图）。
    当前委托 generate_openai_image；替换为低成本后端时只改这里 + providers 内实现。
    """
    return generate_openai_image(settings.image, prompt)
```

这是栅格轨**唯一**的集成点。管道其余部分（媒体计划、质量门、PPTX 导出）都不
感知具体后端。

### 4.2 契约（Contract）

| 项 | 说明 |
|----|------|
| 输入 `prompt` | 来自 `MediaRequirements.image_prompt`（由 agents/strategist 生成） |
| 输入 `aspect_ratio` | `"16:9"` / `"1:1"` 等；后端支持时务必遵守（课堂主图多为 16:9） |
| 输入 `settings.image` | `ImageProviderSettings`：`provider` 选择后端，`api_key`、`model`、`base_url` |
| 输出 | `bytes | None`：PNG 图像字节；**失败必须返回 `None` 而非抛异常**（或抛 `ProviderError`，调用方会捕获为 None） |
| 选择机制 | `settings.image.provider`（当前示例值：`"openai_images"` / `"openai_compatible"` / `"placeholder"`） |
| 失败回退 | 返回 None → 管道保留/生成占位图，不阻断课件 |

### 4.3 推荐实现步骤（Codex 接手）

1. **后端实现**：在 `apps/api/src/hcs_api/providers.py` 新增
   `generate_<provider>_image(settings.image, prompt, aspect_ratio) -> bytes | None`，
   镜像 `generate_openai_image` 的签名与错误处理（`ProviderError`、超时、`None` 回退）。
2. **接入选择**：在 `generate_raster_image`（media.py）按 `settings.image.provider`
   分派到新后端（或直接改 `generate_raster_image` 内部委托）。**不要**改动
   `_replace_images_with_provider_assets` 及更上层。
3. **低成本约束**：
   - 优先选用性价比模型 / 端点；
   - 按 `prompt`（或 `image_key`）做结果缓存，避免重复计费；
   - 尊重 `spec_lock.media.svg_offline_safe` 与整体预算；
   - 不把栅格轨用于「图标 / 结构图 / 简单语义图 / 离线兜底」——那些是 SVG 轨的
     固定职责（见 §2）。
4. **不要做的事**：
   - 不要试图用栅格替代 SVG 轨的离线兜底职责；
   - 不要让 LLM 直接输出图像或 SVG；
   - 不要改变 `MediaRequirements.media_kind` 的语义。

### 4.4 测试衔接

- `tests/test_pipeline.py::test_media_pipeline_replaces_placeholder_assets_when_provider_returns_bytes`
  通过 `monkeypatch.setattr("hcs_api.media.generate_raster_image", ...)` 验证
  栅格轨返回 `.png`、SVG 轨保持 `.svg`。新增后端后该测试仍应绿。
- 新增后端建议补充单测：给定 mock `ImageProviderSettings`，验证返回 bytes /
  None / 异常回退。

---

## 5. 已完成 / 待办

### 已完成（本 release）
- SVG 轨端到端：SceneSpec 规划 → 锁定契约渲染 → 离线安全门 + 教学适用门。
- `睡觉` 场景作为「SVG 轨能做到教学可用」的标杆案例：单一复合组件
  `SleepingInBed` + 跨画幅（16:9 / 1:1 / thumb）独立构图 + Z/窗背景弱化 + 质量门。
- 媒体判别字段 `media_kind` 接入 agents / strategist / media / quality / pptx。
- 诊断页：`diagnostics/sleep_comparison/`、`diagnostics/svg_gallery/`。
- 栅格轨集成点 `generate_raster_image` 已留接口（当前委托 OpenAI 兼容端点）。

### 待办（非本次范围，留给后续）
- 实现低成本栅格 Provider（见 §4，ChatGPT Codex 接手）。
- 扩展示例概念（CONCEPT_RECIPES）覆盖更多词汇；复杂人物场景改走栅格轨。
- 可选：cairosvg 加入依赖以便 PPTX 真实栅格化 SVG（当前为 best-effort 回退）。

---

## 6. 关键文件地图

| 文件 | 职责 |
|------|------|
| `apps/api/src/hcs_api/models.py` | `MediaRequirements.media_kind` 等判别字段 |
| `apps/api/src/hcs_api/strategist.py` | spec_lock 中 `svg_illustration_policy` / `svg_offline_safe` |
| `apps/api/src/hcs_api/agents.py` | 为视觉 slide 设置 `media_kind` |
| `apps/api/src/hcs_api/providers.py` | `generate_openai_image`（栅格后端示例）、`generate_scene_spec`（SVG 规划） |
| `apps/api/src/hcs_api/media.py` | `generate_raster_image`（**栅格 seam**）、SVG 升级管线 |
| `apps/api/src/hcs_api/svg_illustration.py` | SceneSpec 模型、渲染器、质量门、placeholder |
| `apps/api/src/hcs_api/svg_components.py` | 注册组件库（含 `SleepingInBed` 复合组件） |
| `apps/api/src/hcs_api/style_tokens.py` | 锁定调色板（离线安全、禁止效果清单） |
| `apps/api/src/hcs_api/quality.py` | `_check_svg_illustrations` 双门 + 报告 |
| `apps/api/src/hcs_api/pptx_exporter.py` | `_rasterize_svg` PPTX 栅格化兜底 |
| `diagnostics/` | 开发者诊断页（对比画廊、benchmark 画廊） |
| `tests/test_svg_illustration.py` | SVG 轨几何回归 + 质量门测试 |
| `tests/test_pipeline.py` | 媒体双轨管线测试（栅格 seam 在此 mock） |
