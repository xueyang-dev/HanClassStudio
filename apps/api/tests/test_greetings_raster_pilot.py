from __future__ import annotations

import importlib.util
from pathlib import Path

import hcs_api.storage as storage


SCRIPT = Path(__file__).parents[3] / "examples" / "greetings_raster_pilot" / "build_pilot.py"


def _pilot_module():
    spec = importlib.util.spec_from_file_location("greetings_raster_pilot", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_greetings_pilot_is_linguistically_complete_and_uses_supported_components() -> None:
    blueprint = _pilot_module()._blueprint()
    assert [item["word"] for item in blueprint.key_vocabulary] == ["你好", "您好", "老师好", "早上好", "再见"]
    assert [item["pinyin"] for item in blueprint.key_vocabulary] == [
        "nǐ hǎo", "nín hǎo", "lǎoshī hǎo", "zǎoshang hǎo", "zàijiàn",
    ]
    assert {component.component_type for slide in blueprint.slides for component in slide.components} == {
        "VocabularyFlipCard", "ListenAndChoose", "MatchGame",
    }
    raster = [slide for slide in blueprint.slides if slide.media_requirements.image_key and slide.media_requirements.media_kind == "raster"]
    assert len(raster) == 4
    assert all("no embedded words" in (slide.media_requirements.image_prompt or "") for slide in raster)


def test_diagnostic_pilot_build_uses_pipeline_and_stays_offline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "runtime" / "projects")
    module = _pilot_module()
    root = module.build_pilot(real_raster=False)

    assert (root / "learning" / "learning_state_plan.json").is_file()
    assert (root / "learning" / "evidence_plan.json").is_file()
    assert (root / "learning" / "activity_plan.json").is_file()
    assert (root / "presentation" / "presentation_blueprint.json").is_file()
    assert (root / "presentation" / "presentation_theme.json").is_file()
    assert (root / "courseware" / "lesson.html").is_file()
    assert list((root / "exports").glob("*.pptx"))
    assert list((root / "exports").glob("*.zip"))
    report = storage.read_json(module.PROJECT_ID, "diagnostics/pilot_report.json")
    assert report["provider_calls"] == 0
    assert report["remote_provider_url_in_export"] is False
    assert report["teacher_had_to_edit_json_or_code"] is False
    assert report["verdict"] == "pending_teacher_visual_review"
    theme_report = storage.read_json(module.PROJECT_ID, "diagnostics/theme_decision_report.json")
    assert theme_report["decision_source"] == "inherited_from_existing_assets"
    assert theme_report["human_review_required"] is True
