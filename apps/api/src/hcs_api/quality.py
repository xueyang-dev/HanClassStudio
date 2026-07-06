from __future__ import annotations

from pathlib import Path

from .models import AssetManifest, LessonBlueprint, QualityReport
from .components import load_component_registry


def check_quality(project_root: Path, blueprint: LessonBlueprint, manifest: AssetManifest) -> QualityReport:
    report = QualityReport()
    registry = load_component_registry()
    audio_by_id = {asset.id: asset for asset in manifest.audio}
    images_by_id = {asset.id: asset for asset in manifest.images}
    component_ids: set[str] = set()

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
            if component.id in component_ids:
                msg = f"{label} 组件 ID 重复：{component.id}"
                report.invalid_interactions.append(msg)
                _block(report, msg)
            component_ids.add(component.id)

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
        if asset.path.endswith(".svg") or asset.path.endswith(".wav"):
            _warn(report, f"资源使用占位文件：{asset.path}")

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


def _block(report: QualityReport, message: str) -> None:
    if message not in report.blocking:
        report.blocking.append(message)


def _warn(report: QualityReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)
