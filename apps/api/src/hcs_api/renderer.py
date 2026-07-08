from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

from .models import AssetManifest, LessonBlueprint, LessonProfile, PresentationBindingPlan, QualityReport


def render_lesson(
    project_root: Path,
    profile: LessonProfile,
    blueprint: LessonBlueprint,
    manifest: AssetManifest,
    report: QualityReport,
    render_mode: str = "debug",
    activity_bindings: PresentationBindingPlan | None = None,
) -> Path:
    image_by_id = {asset.id: f"../{asset.path}" for asset in manifest.images}
    audio_by_id = {asset.id: f"../{asset.path}" for asset in manifest.audio}
    slides_html = "\n".join(_render_slide(slide, image_by_id, audio_by_id, render_mode) for slide in blueprint.slides)
    is_classroom = render_mode == "classroom"
    data_blob = _build_lesson_data_blob(profile, blueprint, report, is_classroom, activity_bindings)
    title_label = escape(profile.scaffolding_language) if not is_classroom else "辅助语言"
    html = f"""<!doctype html>
<html lang="zh-Hans">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(blueprint.lesson_title)} · HanClassStudio</title>
  <style>{_css()}</style>
</head>
<body>
  <div id="loadingState" class="loading-state">正在准备课件...</div>
  <a class="skip-link" href="#slides">跳到课件</a>
  <div class="courseware-shell" data-mode="bilingual">
    <aside class="slide-rail" aria-label="页面目录">
      <div class="rail-brand">HanClassStudio</div>
      <div class="thumb-list">
        {"".join(f'<button class="thumb" data-jump="{i}" aria-label="前往第 {i + 1} 页"><span>{i + 1}</span>{escape(slide.title)}</button>' for i, slide in enumerate(blueprint.slides))}
      </div>
    </aside>
    <main id="slides" class="stage" tabindex="-1">
      <header class="player-bar">
        <div>
          <strong>{escape(profile.lesson_title)}</strong>
          <span>{title_label}</span>
        </div>
        <div class="toolbar" role="group" aria-label="辅助语言显示">
          <button type="button" data-mode="zh">中文</button>
          <button type="button" data-mode="scaffold">提示</button>
          <button type="button" data-mode="bilingual" class="active">双语</button>
          <button type="button" id="fullscreenBtn">全屏</button>
        </div>
      </header>
      <section class="slide-frame" aria-live="polite">
        {slides_html}
      </section>
      <footer class="player-nav">
        <button type="button" id="prevBtn" aria-label="上一页">上一页</button>
        <span id="pageLabel">1 / {len(blueprint.slides)}</span>
        <button type="button" id="nextBtn" aria-label="下一页">下一页</button>
      </footer>
    </main>
  </div>
  <script type="application/json" id="lesson-data">{data_blob}</script>
  <script>{_js()}</script>
</body>
</html>"""
    filename = "lesson_classroom.html" if is_classroom else "lesson.html"
    output = project_root / "courseware" / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    manifest_filename = "render_manifest_classroom.json" if is_classroom else "render_manifest.json"
    (project_root / "courseware" / manifest_filename).write_text(
        json.dumps(
            {
                "schema": "hanclassstudio.render_manifest.v1",
                "entry": "courseware/lesson.html",
                "slide_count": len(blueprint.slides),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


PROVIDER_REQUIRED = re.compile(r"provider_required|\[Arabic\]|\[.*?\].*?provider_required")
SAFE_ALT = "课堂插图"

# Arabic Unicode ranges
ARABIC_RANGE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+")


def _build_lesson_data_blob(
    profile: LessonProfile,
    blueprint: LessonBlueprint,
    report: QualityReport,
    is_classroom: bool,
    activity_bindings: PresentationBindingPlan | None = None,
) -> str:
    if not is_classroom:
        return json.dumps(
            {"profile": profile.model_dump(mode="json"), "blueprint": blueprint.model_dump(mode="json"), "quality": report.model_dump(mode="json")},
            ensure_ascii=False,
        ).replace("</", "<\\/")

    binding_lookup = _binding_lookup(activity_bindings)

    # Classroom: redact debug info
    safe_profile = {"lesson_title": profile.lesson_title, "scaffolding_language": profile.scaffolding_language}
    safe_slides = []
    for s in blueprint.slides:
        safe_blocks = []
        for b in s.content_blocks:
            safe_blocks.append({
                "text": _clean_arabic_from_zh(b.text),
                "scaffolding_text": "" if PROVIDER_REQUIRED.search(b.scaffolding_text) else b.scaffolding_text,
            })
        safe_comps = []
        for c in s.components:
            data = {k: v for k, v in c.data.items() if k not in ("image_prompt",)}
            # Clean provider_required hints
            for key in list(data.keys()):
                if isinstance(data[key], str) and PROVIDER_REQUIRED.search(data[key]):
                    if is_classroom:
                        data[key] = ""
            # Clean Arabic from text fields
            for key in ("audio_text", "choices", "answer"):
                if key in data and isinstance(data[key], str):
                    data[key] = _clean_arabic_from_zh(data[key])
                elif key in data and isinstance(data[key], list):
                    data[key] = [_clean_arabic_from_zh(str(item)) for item in data[key]]
            binding = binding_lookup.get((s.id, c.id)) or binding_lookup.get((s.id, ""))
            if binding:
                data["evidence_id"] = binding.evidence_id
                data["activity_id"] = binding.activity_id
                data["binding_id"] = binding.binding_id
            safe_comps.append({"component_type": c.component_type, "title": c.title, "data": data})
        safe_slides.append({
            "id": s.id,
            "title": s.title,
            "content_blocks": safe_blocks,
            "components": safe_comps,
        })
    safe_blueprint = {
        "lesson_title": blueprint.lesson_title,
        "objectives": blueprint.objectives,
        "key_vocabulary": [{"word": v["word"], "pinyin": v.get("pinyin", "")} for v in blueprint.key_vocabulary],
        "slides": safe_slides,
    }
    safe_quality = {"state": report.state}
    return json.dumps(
        {"profile": safe_profile, "blueprint": safe_blueprint, "quality": safe_quality},
        ensure_ascii=False,
    ).replace("</", "<\\/")


def _binding_lookup(activity_bindings: PresentationBindingPlan | None) -> dict[tuple[int, str], object]:
    if not activity_bindings:
        return {}
    lookup = {}
    for binding in activity_bindings.bindings:
        if "html_classroom" in binding.presentation_modes or "html_interactive" in binding.presentation_modes:
            lookup[(binding.slide_id, binding.component_id or "")] = binding
    return lookup


def _clean_arabic_from_zh(text: str) -> str:
    """Remove Arabic text from a mixed Chinese-Arabic string, preserving Chinese, pinyin, and punctuation."""
    # Remove Arabic ranges
    cleaned = ARABIC_RANGE.sub("", text)
    # Clean up double spaces and leading/trailing spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Remove trailing Arabic punctuation artifacts
    cleaned = re.sub(r"[！?؟!]+$", "", cleaned).strip()
    return cleaned


def _render_slide(slide, image_by_id: dict[str, str], audio_by_id: dict[str, str], render_mode: str = "debug") -> str:
    image_path = image_by_id.get(slide.media_requirements.image_key or "")
    audio_path = audio_by_id.get(slide.media_requirements.audio_key or "")
    blocks = "".join(_render_block(block, render_mode) for block in slide.content_blocks)
    components = "".join(_render_component(component, audio_by_id, render_mode) for component in slide.components)

    is_classroom = render_mode == "classroom"
    if is_classroom:
        image = _image_classroom(image_path)
        kicker = ""
    else:
        image = _image_or_placeholder(image_path, slide.media_requirements.image_prompt or slide.title)
        kicker = f'<p class="slide-kicker">{escape(slide.slide_type)}</p>'

    audio = _audio_button(audio_path, slide.media_requirements.audio_text or "Demo audio", allow_unavailable=False) if slide.media_requirements.audio_key else ""

    # Classroom mode: hide media zone entirely if no real image
    media_zone = f'<div class="media-zone">{image}</div>'
    if is_classroom and not image_path:
        media_zone = ""

    return f"""
<article class="slide {escape(slide.slide_type)}" data-slide="{slide.id - 1}" data-layout="{escape(slide.layout_variant)}">
  <div class="slide-content">
    <div class="text-zone">
      {kicker}
      <h1>{escape(slide.title)}</h1>
      {blocks}
      {audio}
    </div>
    {media_zone}
  </div>
  <div class="component-zone">{components}</div>
</article>"""


def _render_block(block, render_mode: str = "debug") -> str:
    scaffold_text = block.scaffolding_text
    if render_mode == "classroom" and PROVIDER_REQUIRED.search(scaffold_text):
        scaffold_text = ""
    scaffold = f'<p class="scaffold">{escape(scaffold_text)}</p>' if scaffold_text else ""
    return f'<div class="content-block {escape(block.block_type)}"><p class="zh">{escape(block.text)}</p>{scaffold}</div>'


def _render_component(component, audio_by_id: dict[str, str], render_mode: str = "debug") -> str:
    data = component.data
    title = escape(component.title)
    is_classroom = render_mode == "classroom"

    def _scaffold_text(text: str) -> str:
        if is_classroom and PROVIDER_REQUIRED.search(text):
            return ""
        return text

    _hint = _scaffold_text(data.get("hint", ""))

    if component.component_type == "AudioButton":
        audio = _audio_button(audio_by_id.get(data.get("audio_key", ""), ""), data.get("label") or data.get("audio_text", "Demo audio"))
        return f'<section class="component component-container audio-component"><h2>{title}</h2>{audio}</section>'
    if component.component_type == "VocabularyFlipCard":
        cards = []
        for item in _list(data.get("items")):
            audio = _audio_button(audio_by_id.get(item.get("audio_key", ""), ""), item.get("audio_text", item.get("word", "")))
            meaning = _scaffold_text(item.get("meaning", ""))
            context = item.get("usage_context", "")
            example = _scaffold_text(item.get("example", ""))
            # In classroom mode for zero_beginner, usage_context should be in scaffold language, not Chinese
            context_html = ""
            if context and is_classroom:
                # Check it's not Chinese teacher text
                chinese = re.compile(r"[\\u4e00-\\u9fff]{4,}")
                if not chinese.search(context):
                    context_html = f'<p class="scaffold">{escape(context)}</p>'
            elif context and not is_classroom:
                context_html = f'<p class="scaffold">{escape(context)}</p>'
            cards.append(
                f"""<div class="flip-card" role="button" tabindex="0" aria-label="翻转生词卡 {escape(item.get('word', ''))}">
  <span class="card-face front"><strong>{escape(item.get('word', ''))}</strong><em>{escape(item.get('pinyin', ''))}</em></span>
  <span class="card-face back"><span class="zh">{escape(example)}</span><span class="scaffold">{escape(meaning)}</span>{context_html}</span>
</div>"""
            )
        title_html = "" if is_classroom else f"<h2>{title}</h2>"
        body = f'<div class="vocab-grid">{"".join(cards)}</div>' if cards else _component_empty("暂无生词卡数据")
        return f'<section class="component component-container vocab-component">{title_html}{body}</section>'
    if component.component_type == "SentenceDragBuilder":
        word_list = [str(word) for word in _list(data.get("words"))]
        words = "".join(f'<button type="button" class="word-chip" draggable="true">{escape(word)}</button>' for word in word_list)
        answer = json.dumps(_list(data.get("answer")), ensure_ascii=False)
        empty = _component_empty("暂无可组句词语") if not word_list else ""
        return f"""<section class="component component-container drag-builder" data-answer='{escape(answer)}'>
  <h2>{title}</h2>
  <p class="scaffold">{escape(_hint)}</p>
  {empty}<div class="word-bank">{words}</div>
  <div class="drop-zone" aria-label="组句区域"></div>
  <div class="component-actions"><button type="button" data-check="sentence">检查</button><button type="button" data-reset="sentence">重来</button></div>
  <p class="feedback" aria-live="polite"></p>
</section>"""
    if component.component_type == "ListenAndChoose":
        choices_list = [str(choice) for choice in _list(data.get("choices"))]
        choices = "".join(f'<button type="button" class="choice">{escape(choice)}</button>' for choice in choices_list)
        audio = _audio_button(audio_by_id.get(data.get("audio_key", ""), ""), data.get("audio_text", "播放音频"))
        empty = _component_empty("暂无选择项") if not choices_list else ""
        return f"""<section class="component component-container listen-choose" data-answer="{escape(data.get('answer', ''))}">
  <h2>{title}</h2>
  <p class="scaffold">{escape(_hint)}</p>
  {audio}
  {empty}<div class="choice-grid">{choices}</div>
  <p class="feedback" aria-live="polite"></p>
</section>"""
    if component.component_type == "MatchGame":
        pairs = [pair for pair in _list(data.get("pairs")) if isinstance(pair, dict)]
        left = "".join(f'<button type="button" data-value="{escape(pair.get("left", ""))}">{escape(pair.get("left", ""))}</button>' for pair in pairs)
        right = "".join(f'<button type="button" data-value="{escape(pair.get("left", ""))}">{escape(pair.get("right", ""))}</button>' for pair in reversed(pairs))
        body = f'<div class="match-columns"><div>{left}</div><div>{right}</div></div>' if pairs else _component_empty("暂无配对数据")
        return f"""<section class="component component-container match-game">
  <h2>{title}</h2>
  <p class="scaffold">{escape(_hint)}</p>
  {body}
  <p class="feedback" aria-live="polite"></p>
</section>"""
    if component.component_type == "CharacterFormation":
        character = escape(data.get("character", "字"))
        parts_list = _list(data.get("parts"))
        parts = "".join(f"<li>{escape(str(part))}</li>" for part in parts_list)
        explanation = escape(data.get("explanation", ""))
        logic = f'<div class="formation-flow"><span>{" + ".join(escape(str(part)) for part in parts_list)}</span><strong>→</strong><span>{character}</span></div>' if parts_list else _component_empty("暂无汉字部件数据")
        return f"""<section class="component component-container character-formation">
  <h2>{title}</h2>
  <div class="character-focus">{character}</div>
  {logic}
  <ul>{parts}</ul>
  <p class="scaffold">{explanation}</p>
</section>"""
    return f'<section class="component component-container"><h2>{title}</h2>{_component_empty("此组件暂未支持渲染")}</section>'


def _audio_button(path: str, label: str, allow_unavailable: bool = True) -> str:
    if not path:
        disabled = "disabled" if allow_unavailable else ""
        return f'<button type="button" class="audio-button unavailable" {disabled} aria-label="音频不可用"><span class="audio-icon" aria-hidden="true"></span>音频不可用</button>'
    return f'<button type="button" class="audio-button" data-audio="{escape(path)}" aria-label="播放音频：{escape(label)}"><span class="audio-icon" aria-hidden="true"></span>播放</button>'


def _image_or_placeholder(path: str | None, label: str) -> str:
    if path:
        return f'<img class="slide-image" src="{escape(path)}" alt="{escape(label)}" />'
    return f'<div class="media-placeholder" role="img" aria-label="图片占位">{escape(label or "Demo image placeholder")}</div>'


def _image_classroom(path: str | None) -> str:
    """Classroom mode: show real image or empty placeholder without technical text."""
    if path:
        return f'<img class="slide-image" src="{escape(path)}" alt="{SAFE_ALT}" />'
    return ""


def _component_empty(message: str) -> str:
    return f'<p class="component-empty">{escape(message)}</p>'


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f8faf7;
  --surface: #ffffff;
  --ink: #223236;
  --muted: #5f7370;
  --line: #dce8e2;
  --teal: #087e8b;
  --coral: #f25f5c;
  --gold: #f7b32b;
  --mint: #ddf7e5;
  --shadow: 0 18px 45px rgba(22, 49, 54, 0.14);
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; font-family: Inter, "Noto Sans SC", "Microsoft YaHei", Arial, sans-serif; background: var(--bg); color: var(--ink); }
button { font: inherit; cursor: pointer; min-height: 44px; }
button:disabled { cursor: not-allowed; opacity: .62; }
.loading-state { position: fixed; inset: 0; z-index: 20; display: grid; place-items: center; background: var(--bg); color: var(--teal); font-size: 22px; font-weight: 800; }
.loading-state.hidden { display: none; }
.skip-link { position: fixed; left: 12px; top: -60px; z-index: 5; background: var(--ink); color: #fff; padding: 10px 14px; border-radius: 8px; }
.skip-link:focus { top: 12px; }
.courseware-shell { min-height: 100dvh; display: grid; grid-template-columns: 220px minmax(0, 1fr); }
.slide-rail { background: #edf5ef; border-right: 1px solid var(--line); padding: 18px 14px; overflow: auto; }
.rail-brand { font-weight: 800; margin-bottom: 18px; color: var(--teal); }
.thumb-list { display: grid; gap: 8px; }
.thumb { text-align: left; border: 1px solid transparent; background: transparent; color: var(--ink); border-radius: 8px; padding: 10px; display: grid; grid-template-columns: 28px 1fr; gap: 8px; align-items: center; }
.thumb span { display: inline-grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; background: var(--surface); color: var(--teal); font-weight: 800; }
.thumb.active, .thumb:hover { background: var(--surface); border-color: var(--line); }
.stage { min-height: 100dvh; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; padding: 18px; gap: 14px; }
.player-bar, .player-nav { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.player-bar strong { display: block; font-size: 18px; }
.player-bar span, .scaffold { color: var(--muted); }
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
.toolbar button, .player-nav button, .component-actions button, .audio-button { border: 1px solid var(--line); background: var(--surface); color: var(--ink); border-radius: 8px; padding: 9px 13px; }
.toolbar button.active, .player-nav button:hover, .component-actions button:hover { border-color: var(--teal); color: var(--teal); }
.slide-frame { position: relative; min-height: min(72vw, calc(100dvh - 150px)); aspect-ratio: 16 / 9; max-height: calc(100dvh - 150px); margin: 0 auto; width: min(100%, 1280px); }
.slide { display: none; position: absolute; inset: 0; overflow: hidden; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); padding: clamp(28px, 4vw, 56px); }
.slide.active { display: grid; grid-template-rows: minmax(0, 1fr) auto; gap: 18px; }
.slide-content { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(260px, 0.9fr); gap: 32px; align-items: center; min-height: 0; }
.text-zone { min-width: 0; }
.slide-kicker { margin: 0 0 10px; color: var(--coral); font-weight: 800; font-size: 14px; }
h1 { margin: 0 0 18px; font-size: clamp(34px, 5vw, 62px); line-height: 1.08; letter-spacing: 0; }
h2 { margin: 0 0 12px; font-size: 22px; }
.content-block { margin: 12px 0; font-size: clamp(20px, 2.1vw, 30px); line-height: 1.45; }
.content-block p { margin: 0; }
.media-zone { min-width: 0; }
.slide-image, .media-placeholder { width: 100%; aspect-ratio: 16 / 9; border-radius: 8px; border: 1px solid var(--line); background: var(--mint); }
.slide-image { object-fit: cover; }
.media-placeholder { display: grid; place-items: center; padding: 20px; color: var(--teal); font-weight: 800; text-align: center; }
.component-zone { min-height: 0; }
.component { border-top: 1px solid var(--line); padding-top: 16px; }
.component-empty { margin: 0; border: 1px dashed var(--line); border-radius: 8px; padding: 12px; color: var(--muted); background: #f8fbf8; }
.vocab-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.flip-card { min-height: 145px; width: 100%; border: 1px solid var(--line); border-radius: 8px; background: #fdfefe; color: var(--ink); padding: 0; perspective: 800px; position: relative; overflow: hidden; cursor: pointer; }
.flip-card .card-face { position: absolute; inset: 0; display: grid; place-items: center; align-content: center; gap: 8px; padding: 16px; transition: transform .22s ease, opacity .22s ease; backface-visibility: hidden; }
.flip-card strong { font-size: 36px; }
.flip-card em { font-style: normal; color: var(--teal); font-weight: 700; }
.flip-card .back { transform: rotateY(180deg); background: var(--mint); }
.flip-card.flipped .front { transform: rotateY(180deg); }
.flip-card.flipped .back { transform: rotateY(0); }
.audio-button { display: inline-flex; align-items: center; gap: 8px; color: var(--teal); font-weight: 700; }
.audio-button.unavailable { color: var(--muted); background: #f8fbf8; }
.audio-icon { width: 16px; height: 16px; border-left: 4px solid currentColor; border-top: 5px solid transparent; border-bottom: 5px solid transparent; }
.word-bank, .drop-zone, .choice-grid { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.word-chip, .choice, .match-game button { border: 1px solid var(--line); background: #fff; border-radius: 8px; padding: 10px 14px; }
.drop-zone { min-height: 58px; margin: 12px 0; padding: 10px; border: 2px dashed #9bc6c0; border-radius: 8px; background: #f5fcf8; }
.feedback { min-height: 28px; font-weight: 800; color: var(--teal); }
.match-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.match-columns > div { display: grid; gap: 10px; }
.match-game button.selected { border-color: var(--gold); box-shadow: 0 0 0 3px rgba(247, 179, 43, 0.22); }
.match-game button.matched, .choice.correct { border-color: var(--teal); background: var(--mint); }
.choice.incorrect { border-color: var(--coral); background: #fff0ef; }
.character-focus { font-size: clamp(72px, 12vw, 140px); font-weight: 900; color: var(--teal); line-height: 1; }
.formation-flow { display: inline-flex; align-items: center; gap: 14px; margin: 8px 0 12px; border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; background: #f8fbf8; font-size: 24px; font-weight: 800; }
.character-formation ul { display: flex; flex-wrap: wrap; gap: 10px; padding: 0; margin: 12px 0; list-style: none; }
.character-formation li { border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; background: var(--mint); }
[data-mode="zh"] .scaffold { display: none; }
[data-mode="scaffold"] .zh { display: none; }
@media (max-width: 900px) {
  .courseware-shell { grid-template-columns: 1fr; }
  .slide-rail { display: none; }
  .stage { padding: 10px; }
  .slide-frame { min-height: auto; max-height: none; }
  .slide { position: relative; min-height: 640px; padding: 24px; }
  .slide-content { grid-template-columns: 1fr; }
  .vocab-grid { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
}
"""


def _js() -> str:
    return r"""
const shell = document.querySelector('.courseware-shell');
const loading = document.getElementById('loadingState');
const slides = Array.from(document.querySelectorAll('.slide'));
const thumbs = Array.from(document.querySelectorAll('.thumb'));
const label = document.getElementById('pageLabel');
let current = 0;

function showSlide(index) {
  current = Math.max(0, Math.min(slides.length - 1, index));
  slides.forEach((slide, i) => slide.classList.toggle('active', i === current));
  thumbs.forEach((thumb, i) => thumb.classList.toggle('active', i === current));
  label.textContent = `${current + 1} / ${slides.length}`;
}
document.getElementById('prevBtn').addEventListener('click', () => showSlide(current - 1));
document.getElementById('nextBtn').addEventListener('click', () => showSlide(current + 1));
thumbs.forEach((thumb) => thumb.addEventListener('click', () => showSlide(Number(thumb.dataset.jump))));
document.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowLeft') showSlide(current - 1);
  if (event.key === 'ArrowRight') showSlide(current + 1);
});
document.querySelectorAll('[data-mode]').forEach((button) => {
  if (button.tagName === 'BUTTON') {
    button.addEventListener('click', () => {
      shell.dataset.mode = button.dataset.mode;
      document.querySelectorAll('.toolbar button').forEach((item) => item.classList.toggle('active', item === button));
    });
  }
});
document.getElementById('fullscreenBtn').addEventListener('click', () => {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
  else document.exitFullscreen?.();
});
document.addEventListener('click', (event) => {
  const audioButton = event.target.closest('.audio-button');
  if (audioButton) {
    if (!audioButton.dataset.audio) return;
    const original = audioButton.textContent;
    const audio = new Audio(audioButton.dataset.audio);
    audio.play().then(() => {
      audioButton.textContent = original;
    }).catch(() => {
      audioButton.textContent = '音频不可用';
      audioButton.classList.add('unavailable');
    });
    return;
  }
  const flip = event.target.closest('.flip-card');
  if (flip) flip.classList.toggle('flipped');
  const chip = event.target.closest('.word-chip');
  if (chip && !event.target.closest('.drop-zone')) {
    const builder = chip.closest('.drag-builder');
    builder.querySelector('.drop-zone').appendChild(chip);
  }
  const check = event.target.closest('[data-check="sentence"]');
  if (check) {
    const builder = check.closest('.drag-builder');
    const actual = Array.from(builder.querySelectorAll('.drop-zone .word-chip')).map((item) => item.textContent.trim());
    const expected = JSON.parse(builder.dataset.answer || '[]');
    builder.querySelector('.feedback').textContent = actual.join('') === expected.join('') ? '很好，句子正确。' : '再试一次，注意词语顺序。';
  }
  const reset = event.target.closest('[data-reset="sentence"]');
  if (reset) {
    const builder = reset.closest('.drag-builder');
    const bank = builder.querySelector('.word-bank');
    Array.from(builder.querySelectorAll('.drop-zone .word-chip')).forEach((item) => bank.appendChild(item));
    builder.querySelector('.feedback').textContent = '';
  }
  const choice = event.target.closest('.listen-choose .choice');
  if (choice) {
    const host = choice.closest('.listen-choose');
    const correct = choice.textContent.trim() === host.dataset.answer;
    choice.classList.toggle('correct', correct);
    choice.classList.toggle('incorrect', !correct);
    host.querySelector('.feedback').textContent = correct ? '回答正确。' : '再听一次。';
  }
  const matchButton = event.target.closest('.match-game button');
  if (matchButton && !matchButton.classList.contains('matched')) {
    const game = matchButton.closest('.match-game');
    const selected = game.querySelector('button.selected');
    if (!selected) {
      matchButton.classList.add('selected');
    } else if (selected !== matchButton) {
      if (selected.dataset.value === matchButton.dataset.value) {
        selected.classList.remove('selected');
        selected.classList.add('matched');
        matchButton.classList.add('matched');
        game.querySelector('.feedback').textContent = '匹配成功。';
      } else {
        selected.classList.remove('selected');
        game.querySelector('.feedback').textContent = '不匹配，请再试。';
      }
    }
  }
});
document.addEventListener('dragstart', (event) => {
  if (event.target.classList.contains('word-chip')) event.dataTransfer.setData('text/plain', event.target.textContent);
});
document.addEventListener('keydown', (event) => {
  const flip = event.target.closest('.flip-card');
  if (flip && (event.key === 'Enter' || event.key === ' ')) {
    event.preventDefault();
    flip.classList.toggle('flipped');
  }
});
document.querySelectorAll('.drop-zone').forEach((zone) => {
  zone.addEventListener('dragover', (event) => event.preventDefault());
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    const text = event.dataTransfer.getData('text/plain');
    const chip = Array.from(document.querySelectorAll('.word-chip')).find((item) => item.textContent === text && item.closest('.word-bank'));
    if (chip) zone.appendChild(chip);
  });
});
document.querySelectorAll('.slide-image').forEach((image) => {
  image.addEventListener('error', () => {
    const fallback = document.createElement('div');
    fallback.className = 'media-placeholder';
    fallback.setAttribute('role', 'img');
    fallback.textContent = image.alt || 'Demo image placeholder';
    image.replaceWith(fallback);
  });
});
showSlide(0);
window.addEventListener('load', () => loading?.classList.add('hidden'));
setTimeout(() => loading?.classList.add('hidden'), 600);
"""
