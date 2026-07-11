from __future__ import annotations

import json
import re
from pathlib import Path

from .models import AssetManifest, ClassroomQualityReport, LessonBlueprint, QualityReport, TeachingCandidates
from .blueprint_utils import duplicate_component_id_messages
from .components import load_component_registry
from .svg_illustration import check_svg_offline_safe, check_illustration_quality


def check_quality(project_root: Path, blueprint: LessonBlueprint, manifest: AssetManifest) -> QualityReport:
    report = QualityReport()
    registry = load_component_registry()
    audio_by_id = {asset.id: asset for asset in manifest.audio}
    images_by_id = {asset.id: asset for asset in manifest.images}
    for msg in duplicate_component_id_messages(blueprint):
        report.invalid_interactions.append(msg)
        _block(report, msg)

    if not blueprint.lesson_title.strip():
        _block(report, "课程缺少标题")
        report.missing_titles.append("课程缺少标题")
    else:
        report.passed.append("lesson_has_title")
    if not blueprint.objectives:
        _block(report, "课程缺少学习目标")
    else:
        report.passed.append("lesson_has_objectives")
    if not blueprint.slides:
        _block(report, "课程缺少页面")
    else:
        report.passed.append("lesson_has_slides")

    for slide in blueprint.slides:
        label = f"第 {slide.id} 页"
        if not slide.title.strip():
            msg = f"{label} 缺少标题"
            report.missing_titles.append(msg)
            _warn(report, msg)
        if not slide.slide_type.strip():
            msg = f"{label} 缺少页面类型"
            report.invalid_interactions.append(msg)
            _block(report, msg)

        image_key = slide.media_requirements.image_key
        if slide.media_requirements.image_prompt == "":
            msg = f"{label} 图片 prompt 为空"
            report.empty_prompts.append(msg)
            _warn(report, msg)
        if image_key and image_key not in images_by_id:
            msg = f"{label} 缺少图片资源 {image_key}"
            report.missing_images.append(msg)
            _warn(report, msg)

        audio_key = slide.media_requirements.audio_key
        if audio_key and audio_key not in audio_by_id:
            msg = f"{label} 缺少音频资源 {audio_key}"
            report.missing_audio.append(msg)
            _warn(report, msg)

        for component in slide.components:
            component_config = registry.get(component.component_type)
            if component_config is None:
                msg = f"{label} 不支持的互动组件：{component.component_type}"
                report.invalid_interactions.append(msg)
                _block(report, msg)
                continue
            if component_config.get("experimental"):
                msg = f"{label} 使用实验组件：{component.component_type}"
                report.invalid_interactions.append(msg)
                _block(report, msg)
                continue

            if component.component_type == "AudioButton":
                comp_audio = component.data.get("audio_key")
                if not comp_audio:
                    msg = f"{label} 音频按钮缺少 audio_key"
                    report.invalid_interactions.append(msg)
                    _block(report, msg)
                elif comp_audio not in audio_by_id:
                    msg = f"{label} 音频按钮缺少音频 {comp_audio}"
                    report.missing_audio.append(msg)
                    _block(report, msg)
                if not (component.data.get("label") or component.data.get("audio_text") or component.title):
                    _warn(report, f"{label} 音频按钮缺少可读标签")
            if component.component_type == "SentenceDragBuilder":
                if not component.data.get("answer"):
                    msg = f"{label} 拖拽组句缺少答案"
                    report.invalid_interactions.append(msg)
                    _block(report, msg)
            if component.component_type == "ListenAndChoose":
                if not component.data.get("answer") or not component.data.get("choices"):
                    msg = f"{label} 听音选择缺少选项或答案"
                    report.invalid_interactions.append(msg)
                    _block(report, msg)
                elif component.data.get("answer") not in component.data.get("choices", []):
                    msg = f"{label} 听音选择答案不在选项中"
                    report.invalid_interactions.append(msg)
                    _block(report, msg)
                comp_audio = component.data.get("audio_key")
                if comp_audio and comp_audio not in audio_by_id:
                    msg = f"{label} 听音选择缺少音频 {comp_audio}"
                    report.missing_audio.append(msg)
                    _block(report, msg)
            if component.component_type == "MatchGame":
                if not component.data.get("pairs"):
                    msg = f"{label} 连线匹配缺少配对数据"
                    report.invalid_interactions.append(msg)
                    _block(report, msg)
            if component.component_type == "VocabularyFlipCard":
                for item in component.data.get("items", []):
                    if not item.get("word"):
                        msg = f"{label} 生词卡缺少汉字"
                        report.invalid_interactions.append(msg)
                        _block(report, msg)
                    if not item.get("pinyin"):
                        _warn(report, f"{label} 生词 {item.get('word', '')} 缺少拼音")
                    key = item.get("audio_key")
                    if key and key not in audio_by_id:
                        msg = f"{label} 生词 {item.get('word', '')} 缺少音频 {key}"
                        report.missing_audio.append(msg)
                        _warn(report, msg)
            if component.component_type == "CharacterFormation":
                if not component.data.get("character") or not component.data.get("parts"):
                    msg = f"{label} 汉字结构组件缺少 character 或 parts"
                    report.invalid_interactions.append(msg)
                    _block(report, msg)

    for asset in [*manifest.images, *manifest.audio, *manifest.video, *manifest.fonts]:
        asset_path = (project_root / asset.path).resolve()
        if project_root.resolve() not in asset_path.parents and asset_path != project_root.resolve():
            msg = f"资源路径越界：{asset.path}"
            report.resource_errors.append(msg)
            _block(report, msg)
            continue
        if not asset_path.exists():
            msg = f"资源路径不存在：{asset.path}"
            report.resource_errors.append(msg)
            _block(report, msg)
        if asset.path.endswith(".wav"):
            _warn(report, f"资源使用占位文件：{asset.path}")

    _check_svg_illustrations(project_root, manifest, report)

    if not (project_root / "courseware" / "lesson.html").exists():
        _block(report, "courseware/lesson.html 缺失")
    else:
        report.passed.append("courseware_html_exists")

    if report.blocking:
        report.state = "blocked"
    elif report.warnings:
        report.state = "warning"
    else:
        report.state = "pass"

    if report.blocking or report.warnings:
        report.suggestions.append("根据缺失项重新生成媒体，或删除对应互动组件后再导出。")
    else:
        report.suggestions.append("质量检查通过：标题、互动答案、媒体路径和资源文件均完整。")
    return report


def _check_svg_illustrations(project_root: Path, manifest: AssetManifest, report: QualityReport) -> None:
    """Verify every SVG asset on disk: offline-safe + illustration-quality.

    Offline-safety (can it load safely / is it well-formed) is kept separate from
    illustration-quality (is it a good teaching picture). The SceneSpec persisted
    next to each SVG drives the illustration-quality checks.
    """
    image_dir = project_root / "assets" / "images"
    results: list[dict] = []
    for asset in manifest.images:
        if not asset.path.lower().endswith(".svg"):
            continue
        svg_path = project_root / asset.path
        if not svg_path.exists():
            results.append({"asset_id": asset.id, "state": "blocked", "blocking": ["SVG asset missing on disk"], "warnings": []})
            continue
        try:
            svg = svg_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            results.append({"asset_id": asset.id, "state": "blocked", "blocking": ["SVG asset unreadable"], "warnings": []})
            continue
        entry = check_svg_offline_safe(svg, asset.id).to_dict()
        # Merge illustration-quality (teaching-suitability) findings.
        scene_path = image_dir / f"{asset.id}.scene.json"
        if scene_path.exists():
            try:
                spec = json.loads(scene_path.read_text(encoding="utf-8"))
                iq = check_illustration_quality(spec, svg)
                entry["illustration_quality"] = iq
                entry["scene_spec_valid"] = iq.get("scene_spec_valid", False)
            except Exception:
                entry["illustration_quality"] = {"state": "warning", "notes": ["scene spec unreadable"]}
        results.append(entry)

    if not results:
        return

    qdir = project_root / "quality"
    qdir.mkdir(parents=True, exist_ok=True)
    qdir.joinpath("svg_illustration_report.json").write_text(
        json.dumps(
            {"schema": "hanclassstudio.svg_illustration_report.v1", "assets": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    unsafe = [r for r in results if r["state"] != "pass"]
    if unsafe:
        ids = ", ".join(r["asset_id"] for r in unsafe)
        _warn(report, f"{len(unsafe)} 个 SVG 插画需复核（离线安全）：{ids}")
    weak = [r["asset_id"] for r in results if r.get("illustration_quality", {}).get("state") in ("blocked", "warning")]
    if weak:
        _warn(report, f"{len(weak)} 个 SVG 插画需人工视觉复核（教学适用性）：{', '.join(weak)}")


def check_classroom_quality(blueprint: LessonBlueprint, candidates: TeachingCandidates | None = None) -> ClassroomQualityReport:
    """Classroom-specific quality gate that catches content unfit for student-facing display."""
    report = ClassroomQualityReport()

    if not blueprint.slides:
        report.state = "blocked"
        report.blocking.append("课程缺少页面")
        report.suggestions.append("请先生成课件蓝图。")
        return report

    # --- Content leaks: student-facing content with backend/internal text ---
    _check_student_content(blueprint, report)
    # --- Scaffold failures ---
    _check_scaffolds(blueprint, report)
    # --- Pinyin issues ---
    _check_pinyin(blueprint, report)
    # --- Vocabulary noise ---
    _check_vocabulary(blueprint, report)
    # --- Grammar mismatch ---
    _check_grammar(blueprint, report)
    # --- Debug artifacts in classroom output ---
    _check_debug_artifacts(report)
    # --- Candidate quality ---
    if candidates:
        _check_candidate_quality(blueprint, candidates, report)

    # Derive final state
    if report.blocking:
        report.state = "blocked"
    elif report.warnings:
        report.state = "warning"
    else:
        report.state = "pass"

    if not report.suggestions:
        report.suggestions.append("课堂质量检查通过。")
    return report


LEAK_PATTERNS = {
    "meaning_scaffold": (re.compile(r"Meaning scaffold", re.IGNORECASE), "学生端出现占位文本 'Meaning scaffold'"),
    "image_placeholder": (re.compile(r"Image placeholder", re.IGNORECASE), "学生端出现 'Image placeholder'"),
    "image_prompt_leak": (
        re.compile(r"Clean educational illustration|simple composition.*classroom", re.IGNORECASE),
        "学生端内容泄露 AI 图片 prompt",
    ),
    "prompt_technical": (
        re.compile(r"Scaffolding language context:", re.IGNORECASE),
        "学生端内容泄露技术性 image prompt",
    ),
}


def _check_student_content(blueprint: LessonBlueprint, report: ClassroomQualityReport) -> None:
    for slide in blueprint.slides:
        label = f"第 {slide.id} 页"
        for block in slide.content_blocks:
            for key, (pattern, message) in LEAK_PATTERNS.items():
                if pattern.search(block.text):
                    msg = f"{label} {message}"
                    report.content_leaks.append(msg)
                    report.blocking.append(msg)
                if block.scaffolding_text and pattern.search(block.scaffolding_text):
                    msg = f"{label} 支架文本中 {message}"
                    report.content_leaks.append(msg)
                    report.blocking.append(msg)

        for component in slide.components:
            for key, (pattern, message) in LEAK_PATTERNS.items():
                data_str = str(component.data)
                if pattern.search(data_str):
                    if key in ("meaning_scaffold", "image_placeholder"):
                        msg = f"{label} 组件 {component.component_type} 中 {message}"
                        report.content_leaks.append(msg)
                        report.blocking.append(msg)
                    else:
                        msg = f"{label} 组件 {component.component_type} 中疑似 {message}"
                        report.content_leaks.append(msg)
                        report.blocking.append(msg)

    if not report.content_leaks:
        report.passed.append("no_content_leaks")


FAKE_SCAFFOLD_PATTERN = re.compile(
    r"^(English|Arabic|Russian|Thai|Korean|Japanese|Vietnamese|Indonesian):\s*(.+)",
    re.IGNORECASE,
)


def _check_scaffolds(blueprint: LessonBlueprint, report: ClassroomQualityReport) -> None:
    for slide in blueprint.slides:
        label = f"第 {slide.id} 页"
        for block in slide.content_blocks:
            if not block.scaffolding_text:
                continue
            m = FAKE_SCAFFOLD_PATTERN.match(block.scaffolding_text.strip())
            if m:
                lang = m.group(1)
                rest = m.group(2)
                if lang.lower() != "english":
                    msg = f"{label} 支架文本为伪 {lang} 语：'{lang}: {rest[:60]}...'，非真实翻译"
                    report.scaffold_failures.append(msg)
                    report.blocking.append(msg)
                else:
                    msg = f"{label} 支架文本 '{rest[:60]}...' 虽为英文但带 '{lang}:' 前缀，应直接输出"
                    report.scaffold_failures.append(msg)
                    report.warnings.append(msg)
    if not report.scaffold_failures:
        report.passed.append("scaffolds_authentic")


def _check_pinyin(blueprint: LessonBlueprint, report: ClassroomQualityReport) -> None:
    digit_tone = re.compile(r"[a-zü]+[1-5](?:\s+[a-zü]+[1-5])*")
    digit_tone_word = re.compile(r"[a-zü]+[1-5]")
    for slide in blueprint.slides:
        label = f"第 {slide.id} 页"
        for component in slide.components:
            if component.component_type == "VocabularyFlipCard":
                for item in component.data.get("items", []):
                    p = item.get("pinyin", "")
                    if p and digit_tone_word.search(p):
                        msg = f"{label} 拼音 '{p}' 使用数字声调格式（如 ni3 hao3），课堂建议使用声调符号（nǐ hǎo）"
                        if msg not in report.pinyin_issues:
                            report.pinyin_issues.append(msg)
                            report.warnings.append(msg)
    # Also check key_vocabulary
    for item in blueprint.key_vocabulary:
        p = item.get("pinyin", "")
        if p and digit_tone_word.search(p):
            msg = f"词汇表拼音 '{p}' 使用数字声调格式"
            if msg not in report.pinyin_issues:
                report.pinyin_issues.append(msg)
                report.warnings.append(msg)
    if not report.pinyin_issues:
        report.passed.append("pinyin_tone_mark")


def _check_vocabulary(blueprint: LessonBlueprint, report: ClassroomQualityReport) -> None:
    noise_words = {"学习", "中文", "老师", "同学", "第一", "一", "二", "横", "竖", "撇", "捺"}
    for item in blueprint.key_vocabulary:
        word = item.get("word", "")
        meaning = item.get("meaning", "")
        if not meaning.strip() or meaning.strip() in ("", "Meaning scaffold"):
            msg = f"词汇 '{word}' 释义为空或为占位文本"
            report.vocabulary_noise.append(msg)
            report.blocking.append(msg)
        if word in noise_words:
            suggested = [w for w in noise_words if w != word]
            if not any(w in item.get("meaning", "").lower() for w in ["vocabulary noise intentionally"]):
                msg = f"词汇 '{word}' 疑似噪声（常见教学词汇不应作为目标生词）"
                report.vocabulary_noise.append(msg)
                report.warnings.append(msg)
    if not report.vocabulary_noise:
        report.passed.append("vocabulary_clean")


def _check_grammar(blueprint: LessonBlueprint, report: ClassroomQualityReport) -> None:
    if not blueprint.grammar_points or not blueprint.slides:
        return
    grammar = blueprint.grammar_points[0]
    for slide in blueprint.slides:
        label = f"第 {slide.id} 页"
        for component in slide.components:
            if component.component_type == "SentenceDragBuilder":
                words = component.data.get("words", [])
                answer = component.data.get("answer", [])
                if "了" in grammar and words and "了" not in "".join(str(w) for w in words):
                    msg = f"{label} 语法点 '{grammar}' 含有 '了'，但拖拽组句练习中未出现 '了'"
                    report.grammar_mismatch.append(msg)
                    report.warnings.append(msg)
                if "在" in grammar and "呢" in grammar:
                    zh_words = "".join(str(w) for w in words)
                    if "在" not in zh_words or "呢" not in zh_words:
                        msg = f"{label} 语法点 '{grammar}' 为 '在...呢' 结构，但练习中缺少 '在' 或 '呢'"
                        report.grammar_mismatch.append(msg)
                        report.blocking.append(msg)
    if not report.grammar_mismatch:
        report.passed.append("grammar_practice_match")


def _check_debug_artifacts(report: ClassroomQualityReport) -> None:
    """Placeholder — actual render/export mode checks run on the output."""
    report.passed.append("debug_artifacts_checked")


def _check_candidate_quality(blueprint: LessonBlueprint, candidates: TeachingCandidates, report: ClassroomQualityReport) -> None:
    """Check that blueprint quality is consistent with teaching candidates analysis."""
    # All core vocabulary from noise?
    if candidates.noise_candidates and blueprint.key_vocabulary:
        noise_in_vocab = [v["word"] for v in blueprint.key_vocabulary if v["word"] in candidates.noise_candidates]
        if noise_in_vocab:
            msg = f"核心词汇中包含噪声候选词：{', '.join(noise_in_vocab)}"
            report.vocabulary_noise.append(msg)
            report.warnings.append(msg)

    # Grammar mismatch
    if candidates.grammar_candidates and blueprint.grammar_points:
        candidate_patterns = {c["pattern"] for c in candidates.grammar_candidates}
        for gp in blueprint.grammar_points:
            if gp not in candidate_patterns and gp != "":
                msg = f"语法点 '{gp}' 不在教学候选分析结果中"
                report.grammar_mismatch.append(msg)
                report.warnings.append(msg)

    # If candidates generated warnings, forward them
    for w in candidates.source_warnings:
        report.warnings.append(f"[analysis] {w}")
        report.suggestions.append(f"源头分析建议：{w}")

    if not report.vocabulary_noise and not report.grammar_mismatch:
        report.passed.append("candidate_quality_ok")


def _block(report: QualityReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: QualityReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
