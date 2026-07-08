from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from pptx import Presentation

import hcs_api.main as main
import hcs_api.storage as storage
from hcs_api.main import app
from hcs_api.models import ContentBlock, LessonBlueprint, LessonSlide, QualityReport, SlideComponent
from hcs_api.strategist import build_interaction_plan, build_media_plan


def test_root_renders_chinese_console() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "后端控制台" in response.text
    assert "打开前端工作台" in response.text
    assert "模型与 API 设置" in response.text
    assert "LLM API" in response.text
    assert "文生图模型" in response.text
    assert "文生音频 / TTS" in response.text


def test_health_route() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_skill_docs_exist() -> None:
    root = Path(__file__).resolve().parents[3]
    assert "skills/hanclassstudio/SKILL.md" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert (root / "CLAUDE.md").read_text(encoding="utf-8").strip() == "See `AGENTS.md`."
    assert "Strict Pipeline" in (root / "skills" / "hanclassstudio" / "SKILL.md").read_text(encoding="utf-8")
    assert "main-generation" in (root / "skills" / "hanclassstudio" / "workflows" / "routing.md").read_text(encoding="utf-8")


def test_provider_settings_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", tmp_path / "config" / "provider_settings.json")
    client = TestClient(app)
    payload = {
        "llm": {
            "provider": "openai_compatible",
            "base_url": "https://api.example.com/v1",
            "api_key": "test-key",
            "model": "demo-llm",
        },
        "image": {
            "provider": "comfyui",
            "endpoint_url": "http://127.0.0.1:8188",
            "api_key": "",
            "model": "demo-image-workflow",
        },
        "audio": {
            "provider": "openai_tts",
            "endpoint_url": "https://api.example.com/v1/audio",
            "api_key": "audio-key",
            "model": "demo-tts",
            "voice": "demo-voice",
        },
    }

    save_response = client.put("/api/settings/providers", json=payload)
    assert save_response.status_code == 200
    assert save_response.json() == payload

    get_response = client.get("/api/settings/providers")
    assert get_response.status_code == 200
    assert get_response.json() == payload


def test_project_pipeline_route_runs_full_generation(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
    projects_dir = runtime_dir / "projects"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(storage, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime_dir / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime_dir / "config" / "provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_dir)
    pptx_path = tmp_path / "lesson.pptx"
    _make_pptx(pptx_path)

    client = TestClient(app)
    with pptx_path.open("rb") as file:
        upload_response = client.post(
            "/api/projects/upload",
            files={"file": ("lesson.pptx", file, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload_response.status_code == 200
    project_id = upload_response.json()["project_id"]
    project_root = projects_dir / project_id
    for relative_dir in [
        "uploads",
        "sources",
        "analysis",
        "specs",
        "blueprints",
        "assets/images",
        "assets/audio",
        "assets/video",
        "assets/fonts",
        "assets/data",
        "courseware",
        "quality",
        "exports",
        "agent",
        "backup",
    ]:
        assert (project_root / relative_dir).is_dir()
    assert (project_root / "sources" / "source_material.json").exists()

    pipeline_response = client.post(f"/api/projects/{project_id}/pipeline")

    assert pipeline_response.status_code == 200
    body = pipeline_response.json()
    assert body["status"] == "rendered"
    assert body["route"] == "main-generation"
    assert body["quality_state"] == "warning"
    assert body["lesson_blueprint"]["slides"]
    assert body["asset_manifest"]["audio"]
    assert body["preview_url"] == f"/runtime/projects/{project_id}/courseware/lesson.html"
    assert body["export_url"] == f"/api/projects/{project_id}/export"
    assert (project_root / "specs" / "lesson_spec.md").exists()
    assert (project_root / "specs" / "spec_lock.json").exists()
    assert (project_root / "blueprints" / "lesson_blueprint.json").exists()
    assert (project_root / "blueprints" / "interaction_plan.json").exists()
    assert (project_root / "blueprints" / "media_plan.json").exists()
    assert (project_root / "courseware" / "lesson.html").exists()
    assert (project_root / "courseware" / "render_manifest.json").exists()
    assert (project_root / "quality" / "quality_report.json").exists()


def test_golden_sample_pipeline_smoke_exports_expected_artifacts(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
    projects_dir = runtime_dir / "projects"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(storage, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime_dir / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime_dir / "config" / "provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_dir)
    pptx_path = tmp_path / "hsk1_lesson_14.pptx"
    _make_pptx(pptx_path)

    client = TestClient(app)
    with pptx_path.open("rb") as file:
        upload_response = client.post(
            "/api/projects/upload",
            files={"file": ("hsk1_lesson_14.pptx", file, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload_response.status_code == 200
    project_id = upload_response.json()["project_id"]

    pipeline_response = client.post(f"/api/projects/{project_id}/pipeline")
    assert pipeline_response.status_code == 200

    project_root = projects_dir / project_id
    for directory in ["uploads", "sources", "analysis", "learning", "presentation", "specs", "blueprints", "assets", "courseware", "quality", "exports", "agent"]:
        assert (project_root / directory).is_dir()
    for artifact in [
        "learning/learning_state_plan.json",
        "learning/evidence_plan.json",
        "learning/activity_plan.json",
        "presentation/activity_bindings.json",
        "presentation/binding_quality_report.json",
        "specs/lesson_spec.md",
        "specs/spec_lock.json",
        "blueprints/lesson_blueprint.json",
        "blueprints/interaction_plan.json",
        "blueprints/media_plan.json",
        "courseware/lesson.html",
        "quality/quality_report.json",
    ]:
        assert (project_root / artifact).exists()

    quality_report = json.loads((project_root / "quality" / "quality_report.json").read_text(encoding="utf-8"))
    assert "state" in quality_report

    export_path = storage.latest_export_path(project_id)
    assert export_path is not None
    assert export_path.exists()
    with zipfile.ZipFile(export_path) as zf:
        names = set(zf.namelist())
    assert "lesson.html" in names
    assert "assets/data/lesson_blueprint.json" in names
    assert "assets/data/asset_manifest.json" in names
    assert "assets/data/activity_bindings.json" in names
    assert "assets/data/binding_quality_report.json" in names
    assert "assets/data/quality_report.json" in names

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifact_body = artifacts_response.json()
    assert artifact_body["spec_lock"]["route"] == "main-generation"
    artifact_paths = {item["path"]: item for group in artifact_body["groups"] for item in group["items"]}
    assert artifact_paths["specs/spec_lock.json"]["exists"] is True
    assert artifact_paths["presentation/activity_bindings.json"]["exists"] is True
    assert artifact_paths["presentation/binding_quality_report.json"]["exists"] is True
    assert artifact_paths["presentation/binding_quality_report.json"]["artifact_type"] == "presentation"
    assert artifact_paths["quality/quality_report.json"]["artifact_type"] == "quality"

    agent_response = client.post(f"/api/projects/{project_id}/agent/package")
    assert agent_response.status_code == 200
    agent_body = agent_response.json()
    assert "AGENTS.md" in agent_body["task_text"]
    assert "courseware/lesson.html" in agent_body["rules_text"]
    assert (project_root / "agent" / "AGENT_TASK.md").exists()
    assert (project_root / "agent" / "AGENT_RULES.md").exists()

    validation_response = client.post(f"/api/projects/{project_id}/agent/validate")
    assert validation_response.status_code == 200
    validation_body = validation_response.json()
    assert validation_body["state"] == "pass"
    assert "All blueprint components are registry-compatible" in validation_body["passed"]

    refreshed_artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    refreshed_paths = {item["path"]: item for group in refreshed_artifacts["groups"] for item in group["items"]}
    assert refreshed_paths["agent/AGENT_TASK.md"]["exists"] is True


def test_editable_pptx_export_after_pipeline_keeps_html_zip_intact(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
    projects_dir = runtime_dir / "projects"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(storage, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime_dir / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime_dir / "config" / "provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_dir)
    pptx_path = tmp_path / "editable_source.pptx"
    _make_pptx(pptx_path)

    client = TestClient(app)
    with pptx_path.open("rb") as file:
        upload_response = client.post(
            "/api/projects/upload",
            files={"file": ("editable_source.pptx", file, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload_response.status_code == 200
    project_id = upload_response.json()["project_id"]
    pipeline_response = client.post(f"/api/projects/{project_id}/pipeline")
    assert pipeline_response.status_code == 200

    pptx_response = client.post(f"/api/projects/{project_id}/export/pptx-editable")
    assert pptx_response.status_code == 200
    body = pptx_response.json()
    assert body["export_type"] == "pptx_editable"
    assert body["editable"] is True
    assert body["interaction_policy"] == "classroom_static_activity"
    assert body["filename"].endswith(".pptx")
    assert body["download_url"].endswith(body["filename"])

    project_root = projects_dir / project_id
    editable_path = project_root / "exports" / body["filename"]
    assert editable_path.exists()
    assert editable_path.stat().st_size > 0
    prs = Presentation(editable_path)
    assert len(prs.slides) >= 1
    assert any(shape.has_text_frame and shape.text.strip() for slide in prs.slides for shape in slide.shapes)
    assert (project_root / "quality" / "pptx_quality_report.json").exists()
    manifest = json.loads((project_root / "exports" / "pptx_export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["forced"] is False

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    artifact_paths = {item["path"]: item for group in artifacts_response.json()["groups"] for item in group["items"]}
    assert artifact_paths["quality/pptx_quality_report.json"]["exists"] is True
    assert artifact_paths["exports/pptx_export_manifest.json"]["exists"] is True
    assert artifact_paths[f"exports/{body['filename']}"]["exists"] is True

    zip_response = client.get(f"/api/projects/{project_id}/export")
    assert zip_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zf:
        names = set(zf.namelist())
    assert "lesson.html" in names
    assert "assets/data/quality_report.json" in names


def test_editable_pptx_export_respects_blocked_quality_and_force(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
    projects_dir = runtime_dir / "projects"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(storage, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_dir)
    project_id = "blockedpptx"
    storage.ensure_project(project_id)
    storage.write_model(
        project_id,
        "lesson_blueprint.json",
        LessonBlueprint(
            lesson_title="测试课",
            objectives=["完成练习"],
            key_vocabulary=[{"word": "学", "pinyin": "xue2", "meaning": "study"}],
            grammar_points=[],
            slides=[
                LessonSlide(
                    id=1,
                    slide_type="PracticeSlide",
                    layout_variant="basic",
                    title="练习",
                    content_blocks=[ContentBlock(id="c1", text="我学习中文。")],
                    components=[],
                )
            ],
        ),
    )
    storage.write_model(project_id, "quality_report.json", QualityReport(state="blocked", blocking=["missing answer"]))

    client = TestClient(app)
    normal_response = client.post(f"/api/projects/{project_id}/export/pptx-editable")
    assert normal_response.status_code == 409

    forced_response = client.post(f"/api/projects/{project_id}/export/pptx-editable?force=true")
    assert forced_response.status_code == 200
    body = forced_response.json()
    manifest = json.loads((projects_dir / project_id / "exports" / "pptx_export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["forced"] is True
    assert (projects_dir / project_id / "exports" / body["filename"]).exists()


def test_agent_handoff_e2e_validates_then_render_exports(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
    projects_dir = runtime_dir / "projects"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(storage, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime_dir / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime_dir / "config" / "provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_dir)
    pptx_path = tmp_path / "agent_handoff.pptx"
    _make_pptx(pptx_path)

    client = TestClient(app)
    with pptx_path.open("rb") as file:
        upload_response = client.post(
            "/api/projects/upload",
            files={"file": ("agent_handoff.pptx", file, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload_response.status_code == 200
    project_id = upload_response.json()["project_id"]
    project_root = projects_dir / project_id

    blueprint_response = client.post(f"/api/projects/{project_id}/blueprint")
    assert blueprint_response.status_code == 200
    package_response = client.post(f"/api/projects/{project_id}/agent/package")
    assert package_response.status_code == 200
    assert (project_root / "agent" / "AGENT_TASK.md").exists()
    assert (project_root / "agent" / "AGENT_RULES.md").exists()
    assert not (project_root / "courseware" / "lesson.html").exists()
    assert storage.latest_export_path(project_id) is None

    (project_root / "specs" / "lesson_spec.md").write_text(
        (project_root / "specs" / "lesson_spec.md").read_text(encoding="utf-8")
        + "\n\n## Agent Refinement\nAdd a character formation moment for 学 and an audio replay button.",
        encoding="utf-8",
    )
    blueprint = LessonBlueprint.model_validate_json((project_root / "blueprints" / "lesson_blueprint.json").read_text(encoding="utf-8"))
    next_slide_id = len(blueprint.slides) + 1
    blueprint.slides[0].components.append(
        SlideComponent(
            id="agent_audio_replay",
            component_type="AudioButton",
            title="句子复听",
            data={"audio_key": "agent_sentence_audio", "audio_text": "我在学习中文呢。", "label": "播放句子"},
        )
    )
    blueprint.slides.append(
        LessonSlide(
            id=next_slide_id,
            slide_type="CharacterFormationSlide",
            layout_variant="formation",
            title="汉字构形：学",
            content_blocks=[
                ContentBlock(
                    id="agent_char_note",
                    block_type="prompt",
                    text="看部件，想一想“学”的意思。",
                    scaffolding_text="Look at the parts and infer the meaning.",
                )
            ],
            components=[
                SlideComponent(
                    id="agent_character_xue",
                    component_type="CharacterFormation",
                    title="部件到汉字",
                    data={"character": "学", "parts": ["⺍", "冖", "子"], "explanation": "从部件观察汉字结构。"},
                )
            ],
        )
    )
    (project_root / "blueprints" / "lesson_blueprint.json").write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")
    modified_blueprint = LessonBlueprint.model_validate_json((project_root / "blueprints" / "lesson_blueprint.json").read_text(encoding="utf-8"))
    storage.write_json(project_id, "blueprints/interaction_plan.json", build_interaction_plan(modified_blueprint))
    storage.write_json(project_id, "blueprints/media_plan.json", build_media_plan(modified_blueprint))

    validate_response = client.post(f"/api/projects/{project_id}/agent/validate")
    assert validate_response.status_code == 200
    validation = validate_response.json()
    assert validation["state"] == "warning"
    assert "All blueprint components are registry-compatible" in validation["passed"]
    assert any("run render" in item for item in validation["warnings"])
    assert not (project_root / "courseware" / "lesson.html").exists()
    assert storage.latest_export_path(project_id) is None

    render_response = client.post(f"/api/projects/{project_id}/render")
    assert render_response.status_code == 200
    assert (project_root / "courseware" / "lesson.html").exists()
    assert (project_root / "quality" / "quality_report.json").exists()
    assert storage.latest_export_path(project_id) is not None

    export_response = client.get(f"/api/projects/{project_id}/export")
    assert export_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export_response.content)) as zf:
        names = set(zf.namelist())
    assert "lesson.html" in names
    assert "assets/data/lesson_blueprint.json" in names
    assert "assets/data/asset_manifest.json" in names
    assert "assets/data/quality_report.json" in names


def test_blocked_quality_prevents_normal_export_but_force_export_succeeds(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
    projects_dir = runtime_dir / "projects"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(storage, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_dir)
    project_id = "blockedproject"
    project_root = storage.ensure_project(project_id)
    (project_root / "courseware" / "lesson.html").write_text("<!doctype html><title>blocked</title>", encoding="utf-8")
    storage.write_model(
        project_id,
        "quality_report.json",
        QualityReport(state="blocked", blocking=["missing answer"]),
    )

    client = TestClient(app)
    normal_response = client.get(f"/api/projects/{project_id}/export")
    assert normal_response.status_code == 409

    forced_response = client.post(f"/api/projects/{project_id}/export?force=true")
    assert forced_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(forced_response.content)) as zf:
        names = set(zf.namelist())
        manifest = zf.read("export_manifest.json").decode("utf-8")
    assert "lesson.html" in names
    assert "assets/data/quality_report.json" in names
    assert '"forced": true' in manifest


def test_component_registry_route_exposes_supported_components() -> None:
    client = TestClient(app)
    response = client.get("/api/component-registry")
    assert response.status_code == 200
    body = response.json()
    assert "VocabularyFlipCard" in body
    assert body["ClassroomGame"]["experimental"] is True


def _make_pptx(path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "第14课 我在学习中文呢"
    slide.placeholders[1].text = "学习\n中文\n我在学习中文呢。"
    prs.save(path)
